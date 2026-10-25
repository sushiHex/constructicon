/* Fixed credential-free peer. Native qualification is deliberately not claimed. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "m8_claude_wire.h"

#define SELF "/opt/claude/claude"
#define CREDENTIAL "/tmp/claude-storage/secure/.credentials.json"
#define ADMIN "/etc/claude-code"
#define POLICY "/etc/claude-code/managed-settings.json"
#define MCP "/etc/claude-code/managed-mcp.json"
extern char **environ;

static void require(int condition) { if (!condition) exit(90); }

static void label(const char *key) {
    char value[512];
    FILE *stream = fopen("/proc/self/attr/current", "r");
    require(stream && fgets(value, sizeof(value), stream) && !fclose(stream));
    value[strcspn(value, "\n")] = 0;
    printf("%s:%s\n", key, value);
}

static int attempt(const char *kind) {
    char *const target[] = {"/usr/bin/python3", "-I", "-c", "pass", NULL};
    if (!strcmp(kind, "direct")) execv(target[0], target);
    else if (!strcmp(kind, "shell")) execl("/bin/sh", "sh", "-c", ":", (char *)NULL);
    else if (!strcmp(kind, "self")) execl(SELF, SELF, "--landed", (char *)NULL);
    else {
        int fd = open(target[0], O_RDONLY | O_CLOEXEC);
        require(fd >= 0);
        if (!strcmp(kind, "fd")) fexecve(fd, target, environ);
        else if (!strcmp(kind, "execveat")) syscall(SYS_execveat, fd, "", target, environ, AT_EMPTY_PATH);
        else exit(91);
        int failure = errno;
        require(!close(fd));
        return failure;
    }
    return errno;
}

static int attach(pid_t pid) {
    errno = 0;
    if (ptrace(PTRACE_ATTACH, pid, NULL, NULL) == -1) return errno;
    int status;
    require(waitpid(pid, &status, 0) == pid && WIFSTOPPED(status));
    require(!ptrace(PTRACE_DETACH, pid, NULL, NULL));
    return 0;
}

static int child_ptrace(void) {
    int ready[2];
    require(!pipe(ready));
    pid_t child = fork();
    require(child >= 0);
    if (!child) {
        close(ready[0]);
        require(write(ready[1], "r", 1) == 1);
        close(ready[1]);
        for (;;) pause();
    }
    close(ready[1]);
    char byte;
    require(read(ready[0], &byte, 1) == 1 && byte == 'r');
    close(ready[0]);
    int failure = attach(child);
    require(!kill(child, SIGKILL));
    int status;
    require(waitpid(child, &status, 0) == child && WIFSIGNALED(status));
    return failure;
}

static void absence(void) {
    DIR *workspace = opendir("/workspace");
    int count = 0;
    if (workspace) {
        struct dirent *item;
        while ((item = readdir(workspace)))
            if (strcmp(item->d_name, ".") && strcmp(item->d_name, "..")) count++;
        closedir(workspace);
    } else require(errno == ENOENT);
    printf("workspace-entries:%d\n", count);
    DIR *descriptors = opendir("/proc/self/fd");
    require(descriptors != NULL);
    struct dirent *item;
    int private_count = 0;
    while ((item = readdir(descriptors))) {
        char path[512], target[512];
        if (item->d_name[0] == '.') continue;
        require(snprintf(path, sizeof(path), "/proc/self/fd/%s", item->d_name) > 0);
        ssize_t size = readlink(path, target, sizeof(target) - 1);
        if (size < 0) continue;
        target[size] = 0;
        if (strstr(target, "retained.lock") || strstr(target, "/guards/") ||
            strstr(target, "memfd:") || strstr(target, ".credentials.json")) private_count++;
    }
    closedir(descriptors);
    printf("private-fds:%d\n", private_count);
}

static void canonical_file(const char *path, const char *fact) {
    int fd = open(path, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    struct stat original, reopened;
    require(fd >= 0 && !fstat(fd, &original));
    char descriptor[64], target[512], first[4096], second[4096];
    require(snprintf(descriptor, sizeof(descriptor), "/proc/self/fd/%d", fd) > 0);
    ssize_t length = readlink(descriptor, target, sizeof(target) - 1);
    require(length > 0 && length < (ssize_t)sizeof(target) - 1);
    target[length] = 0;
    const char *classification = !strcmp(target, path) ? "exact" :
        (length >= 10 && !strcmp(target + length - 10, " (deleted)")) ? "deleted" : "unexpected";
    printf("%s-canonical-path:%s\n", fact, classification);
    require(!strcmp(target, path));
    require(S_ISREG(original.st_mode) && (original.st_mode & 07777) == 0600 &&
            original.st_nlink == 1);
    /* Reopen both the actual O_PATH descriptor and the returned pathname.
     * This is the fd-to-path primitive Bun realpath uses on Linux. */
    FILE *from_fd = fopen(descriptor, "rb"), *from_name = fopen(target, "rb");
    require(from_fd && from_name && !fstat(fileno(from_name), &reopened));
    require(original.st_dev == reopened.st_dev && original.st_ino == reopened.st_ino);
    size_t size = fread(first, 1, sizeof(first), from_fd);
    size_t named_size = fread(second, 1, sizeof(second), from_name);
    require(size > 0 && size < sizeof(first) && named_size == size &&
            feof(from_fd) && feof(from_name) && !ferror(from_fd) && !ferror(from_name) &&
            !memcmp(first, second, size));
    require(!fclose(from_fd) && !fclose(from_name) && !close(fd));
    printf("%s-canonical:linked-0600-reopened\n", fact);
}

static void file_content(const char *path, const char *fact) {
    /* The trusted fixture sends the recipe's canonical sealed bytes, avoiding
     * a second policy definition in this peer. Both reads are strictly bounded. */
    char expected[4096], actual[4096];
    require(fgets(expected, sizeof(expected), stdin) != NULL);
    size_t expected_size = strlen(expected);
    require(expected_size > 1 && expected[expected_size - 1] == '\n');
    FILE *stream = fopen(path, "rb");
    require(stream != NULL);
    size_t size = fread(actual, 1, sizeof(actual), stream);
    require(!ferror(stream) && feof(stream) && size < sizeof(actual));
    require(!fclose(stream));
    require(size == expected_size && !memcmp(actual, expected, size));
    printf("%s:exact\n", fact);
}

static void policy_content(void) {
    file_content(POLICY, "policy-content");
    file_content(MCP, "mcp-content");
}

static void persistence(void) {
    int existing = open(CREDENTIAL, O_RDONLY | O_NOFOLLOW);
    char initial[32];
    require(existing >= 0 && read(existing, initial, sizeof(initial)) == 13 &&
            !memcmp(initial, "fake-initial\n", 13) && !close(existing));
    puts("credential-initial:fake-initial");
    const char *staged = "/tmp/claude-storage/secure/.credentials.json.tmp.12345678";
    int fd = open(staged, O_WRONLY | O_CREAT | O_EXCL, 0600);
    require(fd >= 0 && write(fd, "fake-refreshed\n", 15) == 15 && !close(fd));
    errno = 0;
    int renamed = rename(staged, CREDENTIAL);
    int failure = errno;
    printf("credential-rename:%d\n", renamed == -1 ? failure : 0);
    require(renamed == -1 && failure == EBUSY);
    fd = open(CREDENTIAL, O_WRONLY | O_TRUNC | O_NOFOLLOW | O_NONBLOCK);
    require(fd >= 0 && write(fd, "fake-refreshed\n", 15) == 15 && !fchmod(fd, 0600));
    require(!fsync(fd) && !close(fd) && !unlink(staged));
    const char *sibling = "/tmp/claude-storage/secure.lock";
    fd = open(sibling, O_WRONLY | O_CREAT | O_EXCL, 0600);
    require(fd >= 0 && write(fd, "disposable\n", 11) == 11 && !close(fd));
    puts("credential-fallback:written-synced-chmod");
    canonical_file(POLICY, "policy");
    canonical_file(MCP, "mcp");
    policy_content();
    errno = 0;
    fd = open(POLICY, O_WRONLY | O_TRUNC);
    failure = errno;
    if (fd >= 0) close(fd);
    printf("policy-write:%d\n", fd < 0 ? failure : 0);
    require(fd < 0 && failure == EROFS);
    errno = 0;
    fd = open(MCP, O_WRONLY | O_TRUNC);
    failure = errno;
    if (fd >= 0) close(fd);
    printf("mcp-write:%d\n", fd < 0 ? failure : 0);
    require(fd < 0 && failure == EROFS);
    errno = 0;
    fd = open(ADMIN "/unexpected", O_WRONLY | O_CREAT | O_EXCL, 0600);
    failure = errno;
    if (fd >= 0) close(fd);
    printf("admin-create:%d\n", fd < 0 ? failure : 0);
    require(fd < 0 && failure == EROFS);
    errno = 0;
    int changed = rename(POLICY, ADMIN "/renamed");
    failure = errno;
    printf("admin-rename:%d\n", changed < 0 ? failure : 0);
    require(changed < 0 && failure == EROFS);
    errno = 0;
    changed = unlink(POLICY);
    failure = errno;
    printf("policy-unlink:%d\n", changed < 0 ? failure : 0);
    require(changed < 0 && failure == EROFS);
    errno = 0;
    changed = unlink(MCP);
    failure = errno;
    printf("mcp-unlink:%d\n", changed < 0 ? failure : 0);
    require(changed < 0 && failure == EROFS);
}

static void network(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    require(fd >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(443)};
    require(inet_pton(AF_INET, "192.0.2.1", &address.sin_addr) == 1);
    errno = 0;
    int connected = connect(fd, (struct sockaddr *)&address, sizeof(address));
    int failure = errno;
    close(fd);
    printf("direct-network:%d\n", connected == -1 ? failure : 0);
    fd = socket(AF_INET, SOCK_STREAM, 0);
    require(fd >= 0);
    address.sin_port = htons(18080);
    require(inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1);
    require(!connect(fd, (struct sockaddr *)&address, sizeof(address)));
    require(write(fd, "bridge-ping\n", 12) == 12 && !shutdown(fd, SHUT_WR));
    char reply[32];
    size_t received = 0;
    ssize_t size;
    while ((size = read(fd, reply + received, sizeof(reply) - received)) > 0) {
        received += (size_t)size;
        require(received < sizeof(reply));
    }
    require(size == 0 && received == 12 && !memcmp(reply, "bridge-pong\n", 12) && !close(fd));
    puts("bridge-exchange:pong");
}

static void bootstrap(void) {
    printf("parent-ptrace:%d\n", attach(getppid()));
    errno = 0;
    int sent = kill(getppid(), SIGSTOP);
    printf("parent-stop:%d\n", sent == -1 ? errno : 0);
    char path[128];
    require(snprintf(path, sizeof(path), "/proc/self/task/%ld/children", (long)getpid()) > 0);
    FILE *stream = fopen(path, "r");
    long child;
    require(stream && fscanf(stream, "%ld", &child) == 1 && !fclose(stream));
    printf("forwarder-ptrace:%d\n", attach((pid_t)child));
    errno = 0;
    sent = kill((pid_t)child, SIGSTOP);
    printf("forwarder-stop:%d\n", sent == -1 ? errno : 0);
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    int wire_status = claude_wire(argc, argv);
    if (wire_status >= 0) return wire_status;
    if (argc == 2 && !strcmp(argv[1], "--landed")) return 0;
    if (argc == 3 && !strcmp(argv[1], "--control")) {
        label("control-label");
        printf("attempt:%s\n", argv[2]);
        return attempt(argv[2]) ? 92 : 93;
    }
    if (argc == 2 && !strcmp(argv[1], "--ptrace-control")) {
        printf("child-ptrace:%d\n", child_ptrace());
        return 0;
    }
    char input[32];
    require(fgets(input, sizeof(input), stdin) != NULL);
    if (!strcmp(input, "reload\n")) {
        label("reload-label");
        int fd = open(CREDENTIAL, O_RDONLY | O_NOFOLLOW);
        char value[32];
        require(fd >= 0 && read(fd, value, sizeof(value)) == 15 &&
                !memcmp(value, "fake-refreshed\n", 15) && !close(fd));
        puts("credential-reload:fake-refreshed");
        return 0;
    }
    require(!strcmp(input, "ping\n"));
    label("native-label");
    const char *kinds[] = {"direct", "shell", "self", "fd", "execveat"};
    for (size_t i = 0; i < sizeof(kinds) / sizeof(kinds[0]); i++)
        printf("%s:%d\n", kinds[i], attempt(kinds[i]));
    pid_t child = fork();
    require(child >= 0);
    if (!child) {
        label("child-label");
        int failure = attempt("self");
        printf("child-exec:%d\n", failure);
        _exit(failure == EACCES ? 0 : 94);
    }
    int status;
    require(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    puts("child-joined:1");
    printf("child-ptrace:%d\n", child_ptrace());
    bootstrap();
    absence();
    persistence();
    network();
    label("final-label");
    return 0;
}
