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

/* Maintenance closes input after its final observation; READ continues. */
static int wire_input_closed(void) {
    int byte = fgetc(stdin);
    if (byte == EOF) {
        WIRE_CHECK(!ferror(stdin));
        return 1;
    }
    WIRE_CHECK(ungetc(byte, stdin) != EOF);
    return 0;
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

static void wire_ui(void) {
    puts("{\"type\":\"system\",\"subtype\":\"ui_invalidate\",\"event\":\"ui.render\","
         "\"uuid\":\"plain-id\",\"session_id\":\"\",\"instances\":[]}");
}

static void wire_thinking(const char *user_uuid, int tokens, int delta) {
    printf("{\"type\":\"system\",\"subtype\":\"thinking_tokens\",\"estimated_tokens\":%d,"
           "\"estimated_tokens_delta\":%d,\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\",\"user_message_uuid\":%s}\n",
           tokens, delta, user_uuid);
}

/* Pinned 2.1.296 U0 schema and ordinary engine/Rk forwarding: an upstream
 * request will retry, not a terminal READ failure. This peer does not retry a
 * request or wait; it emits source-shaped framing for the real consumer. */
static void wire_retry(void) {
    puts("{\"type\":\"system\",\"subtype\":\"api_retry\",\"attempt\":1,"
         "\"max_retries\":2,\"retry_delay_ms\":1,\"error_status\":null,"
         "\"error\":\"server_error\",\"no_response\":{\"waited_ms\":1,\"retry_wait_ms\":2},"
         "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
}

/* Pinned q9e wait notices and aDo title push. Tool labels are display data,
 * not JSON-RPC ids; title pushes may precede the authoritative init snapshot. */
static void wire_permission_check(const char *status) {
    printf("{\"type\":\"system\",\"subtype\":\"permission_check_status\","
           "\"tool_use_id\":\"tool-use-id\",\"status\":\"%s\","
           "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}\n", status);
}

static void wire_title(const char *session) {
    printf("{\"type\":\"system\",\"subtype\":\"session_title_changed\","
           "\"title\":\"scripted title\",\"uuid\":\"" WIRE_UUID "\","
           "\"session_id\":\"%s\"}\n", session);
}

static int wire_read_sidebands = 0;

static void wire_lifecycle(const char *user_uuid, const char *state) {
    printf("{\"type\":\"command_lifecycle\",\"command_uuid\":%s,\"state\":\"%s\","
           "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}\n",
           user_uuid, state);
}

static void wire_observation(const char *kind, const char *model, int background) {
    char identifier[128];
    wire_read();
    WIRE_CHECK(strstr(wire_frame, "\"type\":\"control_request\"") != NULL);
    WIRE_CHECK(strstr(wire_frame, kind) != NULL);
    wire_token("\"request_id\":", identifier, sizeof(identifier));
    if (wire_read_sidebands) {
        wire_title(WIRE_SESSION);
        wire_permission_check("done");
    }
    if (!strcmp(kind, "\"subtype\":\"initialize\"")) {
        wire_success(identifier,
            "{\"account\":{\"apiProvider\":\"firstParty\",\"subscriptionType\":\"Claude Team\"},"
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
    if (argc != 18 || (strcmp(argv[15], "fixture-read") && strcmp(argv[15], "fixture-ready") &&
                      strcmp(argv[15], "fixture-zero") &&
                      strcmp(argv[15], "fixture-startup") &&
                      strcmp(argv[15], "fixture-startup-subscribed") &&
                      strcmp(argv[15], "fixture-startup-ui") &&
                      strcmp(argv[15], "fixture-startup-ui-overflow")))
        return -1;
#ifdef _WIN32
    WIRE_CHECK(_setmode(_fileno(stdin), _O_BINARY) != -1);
    WIRE_CHECK(_setmode(_fileno(stdout), _O_BINARY) != -1);
#endif
    const char *fixed[] = {"--print", "--input-format", "stream-json", "--output-format",
                          "stream-json", "--verbose", "--safe-mode", "--tools", "",
                          "--permission-mode", "default", "--allowedTools",
                          "mcp__constructicon_read__read_file", "--model"};
    for (size_t i = 0; i < sizeof(fixed) / sizeof(fixed[0]); i++)
        WIRE_CHECK(!strcmp(argv[i + 1], fixed[i]));
    WIRE_CHECK(!strcmp(argv[16], "--effort") && !strcmp(argv[17], "low"));
    const char *model = argv[15];
    int ui = !strcmp(model, "fixture-startup-ui") ||
             !strcmp(model, "fixture-startup-ui-overflow");
    if (!strcmp(model, "fixture-startup") || !strcmp(model, "fixture-startup-subscribed") || ui) {
        char identifier[128], expected[512];
        wire_read();
        wire_token("\"request_id\":", identifier, sizeof(identifier));
        int length = snprintf(expected, sizeof(expected),
            "{\"type\":\"control_request\",\"request_id\":%s,"
            "\"request\":{\"subtype\":\"initialize\"}}\n", identifier);
        WIRE_CHECK(length > 0 && (size_t)length < sizeof(expected));
        WIRE_CHECK(!strcmp(wire_frame, expected));
        if (ui) for (int i = 0; i < 4; i++) wire_ui();
        wire_success(identifier, strcmp(model, "fixture-startup-subscribed")
            ? "{\"account\":{\"apiProvider\":\"firstParty\",\"tokenSource\":\"none\"},"
              "\"claude_code_version\":\"2.1.296\",\"session_state\":\"idle\"}"
            : "{\"account\":{\"apiProvider\":\"firstParty\",\"subscriptionType\":\"Claude Team\"},"
              "\"claude_code_version\":\"2.1.296\",\"session_state\":\"idle\"}", 1);
        WIRE_CHECK(fgetc(stdin) == EOF && !ferror(stdin));
        if (ui) {
            int count = !strcmp(model, "fixture-startup-ui-overflow") ? 5 : 4;
            for (int i = 0; i < count; i++) wire_ui();
        }
        return 0;
    }
    int ready = !strcmp(model, "fixture-ready");
    int callback = ready || !strcmp(model, "fixture-read");
    wire_observation("\"subtype\":\"initialize\"", model, 0);
    if (wire_input_closed()) return 0;
    wire_observation("\"subtype\":\"get_settings\"", model, 0);
    wire_observation("\"subtype\":\"get_hooks_listing\"", model, 0);
    if (wire_input_closed()) return 0;
    wire_read_sidebands = 1;
    wire_title(WIRE_UUID); /* Pre-snapshot session is deliberately not authoritative. */
    wire_observation("\"subtype\":\"initialize\"", model, 0);
    WIRE_CHECK(strstr(wire_frame, "\"sdkMcpServers\":[\"constructicon_read\"]") != NULL);
    wire_mcp("outer-initialize", "{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"initialize\","
             "\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},"
             "\"clientInfo\":{\"name\":\"claude-code\",\"version\":\"2.1.296\"}}}");
    wire_title(WIRE_UUID);
    wire_background();
    wire_permission_check("checking");
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
    wire_lifecycle(user_uuid, "queued");
    wire_lifecycle(user_uuid, "started");
    printf("{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"" WIRE_SESSION "\","
           "\"model\":\"%s\",\"tools\":[\"mcp__constructicon_read__read_file\"],"
           "\"mcp_servers\":[{\"name\":\"constructicon_read\",\"status\":\"connected\",\"source\":\"sdk\"}],"
           "\"uuid\":\"" WIRE_UUID "\"}\n", model);
    printf("{\"type\":\"assistant\",\"session_id\":\"" WIRE_SESSION "\",\"uuid\":\"" WIRE_UUID "\","
           "\"parent_tool_use_id\":null,\"message\":{\"id\":\"message-id\",\"role\":\"assistant\",\"content\":%s}}\n",
           ready ? "[{\"type\":\"tool_use\",\"id\":\"tool-use-id\","
                   "\"name\":\"mcp__constructicon_read__read_file\",\"input\":{\"path\":\"ready.txt\"}}]"
             : callback ? "[{\"type\":\"tool_use\",\"id\":\"tool-use-id\","
                      "\"name\":\"mcp__constructicon_read__read_file\",\"input\":{\"path\":\"calc.py\"}}]"
                    : "[{\"type\":\"text\",\"text\":\"zero-callback\"}]");
    wire_thinking(user_uuid, 3, 3);
    if (callback) {
        wire_mcp("outer-tools/call", ready
                 ? "{\"jsonrpc\":\"2.0\",\"id\":19,\"method\":\"tools/call\","
                   "\"params\":{\"name\":\"read_file\",\"arguments\":{\"path\":\"ready.txt\"},"
                   "\"_meta\":{\"progressToken\":19,\"claudecode/toolUseId\":\"tool-use-id\"}}}"
                 : "{\"jsonrpc\":\"2.0\",\"id\":19,\"method\":\"tools/call\","
                   "\"params\":{\"name\":\"read_file\",\"arguments\":{\"path\":\"calc.py\"},"
                   "\"_meta\":{\"progressToken\":19,\"claudecode/toolUseId\":\"tool-use-id\"}}}");
        puts("{\"type\":\"assistant\",\"session_id\":\"" WIRE_SESSION "\","
             "\"uuid\":\"00000000-0000-4000-8000-000000000003\",\"parent_tool_use_id\":null,"
             "\"message\":{\"id\":\"message-id\",\"role\":\"assistant\","
             "\"content\":[{\"type\":\"text\",\"text\":\"Reading the file.\"}]}}");
        /* Scripted elapsed fixture data; this peer does not wait 30 seconds. */
        puts("{\"type\":\"tool_progress\",\"tool_use_id\":\"tool-use-id-heartbeat-1\","
             "\"tool_name\":\"mcp__constructicon_read__read_file\",\"parent_tool_use_id\":\"tool-use-id\","
             "\"elapsed_time_seconds\":30,\"heartbeat\":true,\"session_id\":\"" WIRE_SESSION "\","
             "\"uuid\":\"00000000-0000-4000-8000-000000000004\"}");
        puts("{\"type\":\"rate_limit_event\",\"rate_limit_info\":{\"status\":\"allowed\","
             "\"isUsingOverage\":false},\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
        /* 2.1.296 task summary is an observation, not a callback result. */
        puts("{\"type\":\"system\",\"subtype\":\"task_summary\",\"detail\":\"Task observation\","
             "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
        wire_permission_check("done");
        wire_title(WIRE_SESSION);
        wire_ack("\"request_id\":\"outer-tools/call\"", "\"id\":19");
        WIRE_CHECK(strstr(wire_frame, "\"isError\":false") != NULL);
        wire_token("\"text\":", result, sizeof(result));
    } else strcpy(result, "\"zero-callback\"");
    WIRE_CHECK(strlen(result) < WIRE_RECORD_BYTES - 2048);
    wire_permission_check("done");
    wire_title(WIRE_SESSION);
    wire_retry();
    wire_thinking(user_uuid, 5, 2);
    wire_lifecycle(user_uuid, "completed");
    /* 2.1.296 permits an empty summarized UUID; it is not result identity. */
    puts("{\"type\":\"system\",\"subtype\":\"post_turn_summary\",\"summarizes_uuid\":\"\","
         "\"status_category\":\"complete\",\"status_detail\":\"done\",\"needs_action\":\"none\","
         "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
    printf("{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false,"
           "\"session_id\":\"" WIRE_SESSION "\",\"user_message_uuid\":%s,\"result\":%s,"
           "\"uuid\":\"" WIRE_UUID "\",\"duration_ms\":1,\"duration_api_ms\":1,\"num_turns\":1,"
           "\"stop_reason\":\"end_turn\",\"total_cost_usd\":0,\"usage\":{"
           "\"input_tokens\":1,\"output_tokens\":1},\"modelUsage\":{},\"permission_denials\":[]}\n",
           user_uuid, result);
    puts("{\"type\":\"system\",\"subtype\":\"task_summary\",\"detail\":null,"
         "\"uuid\":\"" WIRE_UUID "\",\"session_id\":\"" WIRE_SESSION "\"}");
    wire_observation("\"subtype\":\"initialize\"", model, 1);
    wire_observation("\"subtype\":\"get_settings\"", model, 0);
    wire_observation("\"subtype\":\"get_hooks_listing\"", model, 0);
    WIRE_CHECK(fgetc(stdin) == EOF && !ferror(stdin));
    return 0;
}
#endif
