/* Benign syscall fixture only. No vendor, authentication or hostile code. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#define ROOT "/opt/constructicon-m8-noexec"
#define PAYLOAD ROOT "/payload"

#ifdef LAUNCHER
int main(void) {
    execl(PAYLOAD, PAYLOAD, (char *)NULL);
    printf("initial-exec-refused:%d\n", errno);
    return 77;
}
#else
extern char **environ;

static void label(const char *key) {
    char value[256];
    FILE *stream = fopen("/proc/self/attr/current", "r");
    if (!stream || !fgets(value, sizeof(value), stream) || fclose(stream)) exit(90);
    value[strcspn(value, "\n")] = 0;
    printf("%s:%s\n", key, value);
}

static int attempt(const char *kind) {
    char *const target[] = {"/bin/true", NULL};
    if (!strcmp(kind, "direct")) execv(target[0], target);
    else if (!strcmp(kind, "shell")) execl("/bin/sh", "sh", "-c", ":", (char *)NULL);
    else if (!strcmp(kind, "self")) execl(PAYLOAD, PAYLOAD, "landed", (char *)NULL);
    else {
        int fd = open("/bin/true", O_RDONLY | O_CLOEXEC);
        if (fd < 0) exit(91); /* Opening failure is not an execution denial. */
        if (!strcmp(kind, "fd")) fexecve(fd, target, environ);
        else if (!strcmp(kind, "execveat")) syscall(SYS_execveat, fd, "", target, environ, AT_EMPTY_PATH);
        else exit(92);
        int failure = errno;
        if (close(fd)) exit(93);
        return failure;
    }
    return errno;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc == 2 && !strcmp(argv[1], "landed")) return 0;
    if (argc == 2) {
        label("control-label");
        printf("attempt:%s\n", argv[1]);
        return attempt(argv[1]) ? 94 : 95;
    }
    label("before");
    char input[16];
    if (!fgets(input, sizeof(input), stdin) || strcmp(input, "ping\n")) return 96;
    puts("exchange:pong");
    const char *kinds[] = {"direct", "shell", "self", "fd", "execveat"};
    for (size_t i = 0; i < sizeof(kinds) / sizeof(kinds[0]); i++)
        printf("%s:%d\n", kinds[i], attempt(kinds[i]));
    pid_t child = fork();
    if (child < 0) return 97;
    if (!child) {
        label("child-label");
        int failure = attempt("direct");
        printf("child-errno:%d\n", failure);
        _exit(failure == EACCES ? 0 : 98);
    }
    int status;
    if (waitpid(child, &status, 0) != child) return 99;
    printf("child-joined:%d\n", WIFEXITED(status) && WEXITSTATUS(status) == 0);
    /* Deliberate counterexample: denying exec does not deny native I/O. */
    int store = open(ROOT "/fake-store", O_RDWR);
    char byte;
    if (store < 0 || read(store, &byte, 1) != 1 || byte != 'a' ||
        lseek(store, 0, SEEK_SET) != 0 || write(store, "b", 1) != 1 || close(store)) return 100;
    puts("same-process-file:read-write");
    int pair[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) || write(pair[0], "s", 1) != 1 ||
        read(pair[1], &byte, 1) != 1 || byte != 's' || close(pair[0]) || close(pair[1])) return 101;
    puts("same-process-socket:read-write");
    label("after");
    return 0;
}
#endif
