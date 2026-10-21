/* Bounded, credential-free CLI-shaped protocol peer; no vendor code or model. */
#ifndef M8_CLAUDE_WIRE_H
#define M8_CLAUDE_WIRE_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

/* claude_protocol.RECORD_BYTES includes the LF. Cumulative input is finite:
 * exactly twelve controller frames with a callback, eleven without one. */
#define WIRE_RECORD_BYTES (256 * 1024)
#define WIRE_SESSION "00000000-0000-4000-8000-000000000001"
#define WIRE_UUID "00000000-0000-4000-8000-000000000002"
#define WIRE_CHECK(value) do { if (!(value)) { \
    fprintf(stderr, "fake Claude wire refused at line %d\n", __LINE__); exit(97); \
} } while (0)

static char wire_frame[WIRE_RECORD_BYTES + 1];

static void wire_read(void) {
    WIRE_CHECK(fgets(wire_frame, sizeof(wire_frame), stdin) != NULL);
    size_t length = strlen(wire_frame);
    WIRE_CHECK(length && length <= WIRE_RECORD_BYTES && wire_frame[length - 1] == '\n');
    WIRE_CHECK(strchr(wire_frame, '\r') == NULL);
}

/* Copy one JSON string token, retaining its quoting/escapes for a wire reply.
 * The controller owns these exact compact JSON frames. This fixture is not a
 * general parser or an authority boundary; every scan has the frame bound. */
static void wire_token(const char *key, char *output, size_t capacity) {
    const char *start = strstr(wire_frame, key);
    WIRE_CHECK(start != NULL);
    start += strlen(key);
    WIRE_CHECK(*start == '"');
    const char *end = start + 1;
    while (*end && *end != '"') {
        WIRE_CHECK((unsigned char)*end >= 32);
        if (*end == '\\') { end++; WIRE_CHECK(*end && *end != '\n'); }
        end++;
    }
    WIRE_CHECK(*end == '"');
    size_t length = (size_t)(end + 1 - start);
    WIRE_CHECK(length < capacity);
    memcpy(output, start, length);
    output[length] = 0;
}

static void wire_success(const char *id, const char *body, int initialize) {
    printf("{\"type\":\"control_response\",\"response\":{\"subtype\":\"success\","
           "\"request_id\":%s,\"response\":%s%s}}\n", id, body,
           initialize ? ",\"pending_permission_requests\":[],\"pending_user_dialog_requests\":[]" : "");
}

static void wire_background(void) {
    puts("{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[],"
         "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
}

static void wire_observation(const char *kind, const char *model, int background) {
    char identifier[128];
    wire_read();
    WIRE_CHECK(strstr(wire_frame, "\"type\":\"control_request\"") != NULL);
    WIRE_CHECK(strstr(wire_frame, kind) != NULL);
    wire_token("\"request_id\":", identifier, sizeof(identifier));
    if (!strcmp(kind, "\"subtype\":\"initialize\"")) {
        wire_success(identifier,
            "{\"account\":{\"apiProvider\":\"firstParty\",\"subscriptionType\":\"Claude Pro\"},"
            "\"claude_code_version\":\"2.1.296\",\"session_state\":\"idle\"}", 1);
        if (background) wire_background();
    } else if (!strcmp(kind, "\"subtype\":\"get_settings\"")) {
        char body[2048];
        int length = snprintf(body, sizeof(body),
            "{\"effective\":{\"forceRemoteSettingsRefresh\":true,"
            "\"deniedMcpServers\":[{\"serverUrl\":\"*\"}]},\"sources\":[{"
            "\"source\":\"policySettings\",\"settings\":{\"forceRemoteSettingsRefresh\":true,"
            "\"deniedMcpServers\":[{\"serverUrl\":\"*\"}]}}],\"applied\":{\"model\":\"%s\","
            "\"effort\":\"low\",\"advisor\":null,\"ultracode\":false,"
            "\"ultracodeRequested\":false,\"ultracodeAvailable\":false}}", model);
        WIRE_CHECK(length > 0 && (size_t)length < sizeof(body));
        wire_success(identifier, body, 0);
    } else {
        /* One valid emitted catalogue row suffices for this fake projection;
         * this is not a claim about the vendor's complete builtin inventory. */
        wire_success(identifier,
            "{\"events\":[],\"hooks\":[],\"eventCatalog\":[{\"name\":\"PreToolUse\","
            "\"summary\":\"Before tool execution\",\"supportsMatcher\":true}],\"policy\":{"
            "\"disabledByPolicy\":false,\"managedOnly\":false,\"pluginOnly\":false,"
            "\"allDisabled\":false,\"policyHookCount\":0},\"safeMode\":{"
            "\"managedHooksStillApply\":true,\"exitHint\":\"restart without --safe-mode\"}}", 0);
    }
}

static void wire_mcp(const char *outer, const char *message) {
    printf("{\"type\":\"control_request\",\"request_id\":\"%s\",\"request\":{"
           "\"subtype\":\"mcp_message\",\"server_name\":\"constructicon_read\","
           "\"message\":%s}}\n", outer, message);
}

static void wire_ack(const char *outer, const char *rpc) {
    wire_read();
    WIRE_CHECK(strstr(wire_frame, "\"type\":\"control_response\"") != NULL);
    WIRE_CHECK(strstr(wire_frame, "\"subtype\":\"success\"") != NULL);
    WIRE_CHECK(strstr(wire_frame, outer) != NULL && strstr(wire_frame, rpc) != NULL);
}

static int claude_wire(int argc, char **argv) {
    if (argc != 14 || (strcmp(argv[11], "fixture-read") && strcmp(argv[11], "fixture-zero") &&
                      strcmp(argv[11], "fixture-startup") &&
                      strcmp(argv[11], "fixture-startup-subscribed")))
        return -1;
#ifdef _WIN32
    WIRE_CHECK(_setmode(_fileno(stdin), _O_BINARY) != -1);
    WIRE_CHECK(_setmode(_fileno(stdout), _O_BINARY) != -1);
#endif
    const char *fixed[] = {"--print", "--input-format", "stream-json", "--output-format",
                          "stream-json", "--verbose", "--safe-mode", "--tools", "",
                          "--model"};
    for (size_t i = 0; i < sizeof(fixed) / sizeof(fixed[0]); i++)
        WIRE_CHECK(!strcmp(argv[i + 1], fixed[i]));
    WIRE_CHECK(!strcmp(argv[12], "--effort") && !strcmp(argv[13], "low"));
    const char *model = argv[11];
    if (!strcmp(model, "fixture-startup") || !strcmp(model, "fixture-startup-subscribed")) {
        char identifier[128], expected[512];
        wire_read();
        wire_token("\"request_id\":", identifier, sizeof(identifier));
        int length = snprintf(expected, sizeof(expected),
            "{\"type\":\"control_request\",\"request_id\":%s,"
            "\"request\":{\"subtype\":\"initialize\"}}\n", identifier);
        WIRE_CHECK(length > 0 && (size_t)length < sizeof(expected));
        WIRE_CHECK(!strcmp(wire_frame, expected));
        wire_success(identifier, !strcmp(model, "fixture-startup")
            ? "{\"account\":{\"apiProvider\":\"firstParty\",\"tokenSource\":\"none\"},"
              "\"claude_code_version\":\"2.1.296\",\"session_state\":\"idle\"}"
            : "{\"account\":{\"apiProvider\":\"firstParty\",\"subscriptionType\":\"Claude Pro\"},"
              "\"claude_code_version\":\"2.1.296\",\"session_state\":\"idle\"}", 1);
        WIRE_CHECK(fgetc(stdin) == EOF && !ferror(stdin));
        return 0;
    }
    int callback = !strcmp(model, "fixture-read");
    wire_observation("\"subtype\":\"initialize\"", model, 0);
    wire_observation("\"subtype\":\"get_settings\"", model, 0);
    wire_observation("\"subtype\":\"get_hooks_listing\"", model, 0);
    wire_observation("\"subtype\":\"initialize\"", model, 0);
    WIRE_CHECK(strstr(wire_frame, "\"sdkMcpServers\":[\"constructicon_read\"]") != NULL);
    wire_mcp("outer-initialize", "{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"initialize\","
             "\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},"
             "\"clientInfo\":{\"name\":\"claude-code\",\"version\":\"2.1.296\"}}}");
    wire_background();
    wire_ack("\"request_id\":\"outer-initialize\"", "\"id\":7");
    wire_mcp("outer-notifications/initialized",
             "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}");
    wire_ack("\"request_id\":\"outer-notifications/initialized\"", "\"id\":0");
    wire_mcp("outer-tools/list", "{\"jsonrpc\":\"2.0\",\"id\":\"list-id\",\"method\":\"tools/list\"}");
    wire_ack("\"request_id\":\"outer-tools/list\"", "\"id\":\"list-id\"");
    WIRE_CHECK(strstr(wire_frame, "\"name\":\"read_file\"") != NULL);
    wire_read();
    WIRE_CHECK(strstr(wire_frame, "\"type\":\"user\"") != NULL);
    WIRE_CHECK(strstr(wire_frame, "\"client_composed\":true") != NULL);
    char user_uuid[128], result[WIRE_RECORD_BYTES + 1];
    wire_token("\"uuid\":", user_uuid, sizeof(user_uuid));
    printf("{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"" WIRE_SESSION "\","
           "\"model\":\"%s\",\"tools\":[\"mcp__constructicon_read__read_file\"],"
           "\"mcp_servers\":[{\"name\":\"constructicon_read\",\"status\":\"connected\"}],"
           "\"uuid\":\"" WIRE_UUID "\"}\n", model);
    printf("{\"type\":\"assistant\",\"session_id\":\"" WIRE_SESSION "\",\"uuid\":\"" WIRE_UUID "\","
           "\"parent_tool_use_id\":null,\"message\":{\"role\":\"assistant\",\"content\":%s}}\n",
           callback ? "[{\"type\":\"tool_use\",\"id\":\"tool-use-id\","
                      "\"name\":\"mcp__constructicon_read__read_file\",\"input\":{\"path\":\"calc.py\"}}]"
                    : "[{\"type\":\"text\",\"text\":\"zero-callback\"}]");
    if (callback) {
        wire_mcp("outer-tools/call", "{\"jsonrpc\":\"2.0\",\"id\":19,\"method\":\"tools/call\","
                 "\"params\":{\"name\":\"read_file\",\"arguments\":{\"path\":\"calc.py\"}}}");
        wire_ack("\"request_id\":\"outer-tools/call\"", "\"id\":19");
        WIRE_CHECK(strstr(wire_frame, "\"isError\":false") != NULL);
        wire_token("\"text\":", result, sizeof(result));
    } else strcpy(result, "\"zero-callback\"");
    WIRE_CHECK(strlen(result) < WIRE_RECORD_BYTES - 2048);
    printf("{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false,"
           "\"session_id\":\"" WIRE_SESSION "\",\"user_message_uuid\":%s,\"result\":%s,"
           "\"uuid\":\"" WIRE_UUID "\",\"duration_ms\":1,\"duration_api_ms\":1,\"num_turns\":1,"
           "\"stop_reason\":\"end_turn\",\"total_cost_usd\":0,\"usage\":{"
           "\"input_tokens\":1,\"output_tokens\":1},\"modelUsage\":{},\"permission_denials\":[]}\n",
           user_uuid, result);
    wire_observation("\"subtype\":\"initialize\"", model, 1);
    wire_observation("\"subtype\":\"get_settings\"", model, 0);
    wire_observation("\"subtype\":\"get_hooks_listing\"", model, 0);
    WIRE_CHECK(fgetc(stdin) == EOF && !ferror(stdin));
    return 0;
}
#endif
