"""Load-bearing mutations for N3b acquisition-scoped egress.

Run with ``uv run python scripts/check_m8_n3b_mutations.py``. The shared runner
mutates only child-process code objects and requires an assertion failure; a
collection, runtime, or harness error does not prove a mutant was killed.
Every killing test is portable or a Linux unit test, never a provisioned
containment test. The ancillary mutant is killed only on Linux; on Windows it
reports NOT PROVEN, which is expected and is not a kill.
"""

from _mutations import run

EGRESS = "constructicon.substrate.executors.egress:"
RELAY = EGRESS + "EgressRelay."
CODEX = "constructicon.substrate.executors.codex:"
LAUNCHER = "constructicon.substrate.executors.linux:"
E = "tests/substrate/test_egress.py::"
C = "tests/substrate/test_codex_egress.py::"
L = "tests/substrate/test_egress_launch.py::"

MUTANTS = (
    (
        "1 the first hello must name the CONNECT host",
        RELAY + "_open",
        "if client_hello_sni(bytes(buffer[:total])) != host:",
        "if client_hello_sni(bytes(buffer[:total])) is None:",
        E + "test_a_refused_hello_reaches_no_peer[other-sni]",
    ),
    (
        "2 a hello without server_name is refused",
        EGRESS + "client_hello_sni",
        "if name is None:",
        "if False:",
        E + "test_client_hello_refusals[no-sni]",
    ),
    (
        "3 an ECH extension is refused",
        EGRESS + "client_hello_sni",
        "if kind == _ECH:",
        "if False:",
        E + "test_client_hello_refusals[ech]",
    ),
    (
        "4 an ECH extension after server_name is refused too",
        EGRESS + "client_hello_sni",
        "if kind == _ECH:",
        "if kind == _ECH and name is None:",
        E + "test_client_hello_refusals[ech-after-sni]",
    ),
    (
        "5 only a ClientHello handshake is judged",
        EGRESS + "client_hello_sni",
        "if body[0] != 1:",
        "if False:",
        E + "test_client_hello_refusals[not-client-hello]",
    ),
    (
        "6 the hello is contained exactly in one record",
        EGRESS + "client_hello_sni",
        'if int.from_bytes(body[1:4], "big") != len(body) - 4:',
        "if False:",
        E + "test_client_hello_refusals[fragmented]",
    ),
    (
        "7 the legacy record version has an upper bound",
        EGRESS + "_record_length",
        "if version < 0x0301 or version > 0x0303:",
        "if version < 0x0301:",
        E + "test_client_hello_refusals[version-high]",
    ),
    (
        "8 a duplicated extension is refused",
        EGRESS + "client_hello_sni",
        "if kind in seen:",
        "if False:",
        E + "test_client_hello_refusals[duplicate-extension]",
    ),
    (
        "9 server_name names exactly one host_name",
        EGRESS + "_server_name",
        "if not entries.done:",
        "if False:",
        E + "test_client_hello_refusals[two-host-names]",
    ),
    (
        "10 a CONNECT outside the sealed policy is refused",
        RELAY + "_open",
        "if destination is None:",
        "if False:",
        E + "test_a_refused_connect_reaches_no_peer[non-member]",
    ),
    (
        "11 hello bytes pipelined after the head stay in the one buffer",
        RELAY + "_open",
        "del buffer[:end + 4]",
        "buffer.clear()",
        E + "test_a_pipelined_connect_and_hello_is_forwarded_byte_identical",
    ),
    (
        "12 the dial uses the pinned address, never the CONNECT host",
        RELAY + "_open",
        "(destination.address, destination.port)",
        "(host, destination.port)",
        E + "test_a_pipelined_connect_and_hello_is_forwarded_byte_identical",
    ),
    (
        "13 every handler await is bounded by the acquisition deadline",
        RELAY + "_handle",
        "asyncio.timeout_at(self._deadline)",
        "asyncio.timeout_at(self._deadline + 3600)",
        E + "test_the_deadline_cuts_an_idle_handler",
    ),
    (
        "14 an accept after stop is closed unread",
        RELAY + "_accept_loop",
        "self._require_live(loop)",
        "pass",
        E + "test_an_accept_after_stop_is_closed_unread",
    ),
    (
        "15 control is checked before the dial",
        RELAY + "_open",
        "self._admit(loop)\n    pinned = ",
        "pinned = ",
        E + "test_a_control_raise_before_the_dial_is_a_denial_and_stops_the_relay",
    ),
    (
        "16 control is rechecked after the dial resumes",
        RELAY + "_open",
        "self._admit(loop)\n        await loop.sock_sendall(upstream, bytes(buffer))",
        "await loop.sock_sendall(upstream, bytes(buffer))",
        E + "test_control_lost_during_the_dial_closes_the_upstream_before_any_byte",
    ),
    (
        "17 the pump rechecks liveness after every read",
        RELAY + "_pump",
        "self._require_live(loop)",
        "pass",
        E + "test_ownership_loss_leaves_an_established_stream_until_the_relay_stops",
    ),
    (
        "18 teardown cancels and joins every handler",
        RELAY + "__aexit__",
        "tasks = [self._accept, *self._handlers]",
        "tasks = [self._accept]",
        E + "test_teardown_delivers_peer_eof_once_exit_returns",
    ),
    (
        "19 the connection bound binds at its limit",
        RELAY + "_accept_loop",
        "if self._connections > self._policy.connections:",
        "if self._connections >= self._policy.connections:",
        E + "test_the_connection_bound_binds_at_its_limit",
    ),
    (
        "20 exit raises recorded relay failures",
        RELAY + "__aexit__",
        "if failures:",
        "if False:",
        E + "test_an_unclassified_handler_failure_is_fatal_at_exit",
    ),
    (
        "21 exit never suppresses the body's exception",
        RELAY + "__aexit__",
        "self.closed = True",
        "self.closed = True\n    return True",
        E + "test_the_relay_never_suppresses_the_body_exception",
    ),
    (
        "22 the payload directory is created exclusively",
        RELAY + "__aenter__",
        "self._directory.mkdir(mode=0o700)",
        "self._directory.mkdir(mode=0o700, exist_ok=True)",
        E + "test_an_existing_payload_is_refused_and_left_untouched",
    ),
    (
        "23 exit unlinks only the socket it bound",
        RELAY + "_release_path",
        "if (info.st_dev, info.st_ino) != self._socket.identity:",
        "if False:",
        E + "test_a_replaced_socket_is_not_unlinked_and_exit_raises",
    ),
    (
        "24 the CONNECT head bound binds at its limit",
        RELAY + "_open",
        "if len(buffer) >= CONNECT_HEAD_BYTES:",
        "if len(buffer) > CONNECT_HEAD_BYTES:",
        E + "test_the_connect_head_bound_binds_at_its_limit",
    ),
    (
        "25 a destination host's final label begins with a letter",
        EGRESS + "_is_host",
        "and labels[-1][0] in _LETTERS",
        "and True",
        E + "test_a_policy_refuses_ambiguous_or_mutable_input[numeric-host]",
    ),
    (
        "26 the policy is an immutable tuple before it is digested",
        EGRESS + "EgressPolicy.__post_init__",
        "if type(self.destinations) is not tuple or not self.destinations or not all(",
        "if not self.destinations or not all(",
        E + "test_a_policy_refuses_ambiguous_or_mutable_input[list]",
    ),
    (
        "27 allocation errors never publish their own text",
        RELAY + "__aenter__",
        "raise ContractViolation(ALLOCATION_FAILED) from exc",
        "raise",
        C + "test_no_private_locator_reaches_the_outcome[existing-payload]",
    ),
    (
        "28 relay failures never publish their own text",
        RELAY + "__aexit__",
        "failure = _fixed(RELAY_FAILED, failures)",
        "failure = ContractViolation(repr(failures))",
        C + "test_no_private_locator_reaches_the_outcome[handler-failure]",
    ),
    (
        "29 ancillary descriptors are refused (Linux only)",
        EGRESS + "_receive",
        "if ancillary or flags & socket.MSG_CTRUNC:",
        "if False:",
        E + "test_ancillary_descriptors_are_closed_and_refused",
    ),
    (
        "30 a close latched after the task is created allocates nothing",
        CODEX + "CodexOperatorHandle._exchange",
        "self._check_control()\n    async with EgressRelay",
        "async with EgressRelay",
        C + "test_a_close_latched_after_the_task_is_created_allocates_nothing",
    ),
    (
        "31 the published egress identity matches the sealed policy",
        CODEX + "CodexOperatorProvider.__init__",
        "if getattr(identity.egress, field) != value:",
        "if False:",
        C + "test_a_drifted_egress_identity_is_refused[destination_policy_digest]",
    ),
    (
        "32 the acquisition root budget binds at its limit",
        CODEX + "CodexOperatorProvider.__init__",
        "if len(os.fsencode(longest / SOCKET_NAME)) > MAX_SOCKET_PATH_BYTES:",
        "if len(os.fsencode(longest / SOCKET_NAME)) >= MAX_SOCKET_PATH_BYTES:",
        C + "test_the_acquisition_root_budget_binds_at_its_limit",
    ),
    (
        "33 the egress leaf has one fixed in-zone destination",
        LAUNCHER + "LinuxLauncher.argv",
        "str(native_store.egress.path), ZONE_SOCKET]",
        'str(native_store.egress.path), "/changed-egress.sock"]',
        L + "test_a_current_egress_socket_gets_one_read_only_leaf",
    ),
    (
        "34 argv re-identifies the socket before mounting it",
        LAUNCHER + "LinuxLauncher.argv",
        "native_store.egress.require_current()",
        "pass",
        L + "test_a_changed_or_foreign_egress_socket_is_refused[identity]",
    ),
    (
        "35 the re-identified path must still be a socket",
        EGRESS + "EgressSocket.require_current",
        "or not stat.S_ISSOCK(info.st_mode)",
        "or False",
        L + "test_a_changed_or_foreign_egress_socket_is_refused[regular-file]",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
