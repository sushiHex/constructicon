"""Load-bearing mutations for the N4-preparation proxy bridge.

Run with ``uv run python scripts/check_m8_n4_bridge_mutations.py``. The shared
runner mutates only child-process code objects and requires an assertion
failure; a collection, runtime, or harness error does not prove a mutant was
killed. Every killing test is portable or a Linux unit test, never a
provisioned containment test. Mutant 4 (Linux's shutdown wakes a blocked
recv; Windows' does not) and the fork, readiness and exec mutants 13-17 and 20
are killed only on Linux; on Windows they report NOT PROVEN, which is expected
and is not a kill.
"""

from _mutations import run

BRIDGE = "constructicon.substrate.executors._egress_bridge:"
LAUNCHER = "constructicon.substrate.executors.linux:"
B = "tests/substrate/test_egress_bridge.py::"
L = "tests/substrate/test_egress_launch.py::"

MUTANTS = (
    (
        "1 the pump forwards exactly what it read",
        BRIDGE + "pump",
        "destination.sendall(data)",
        "destination.sendall(data[1:])",
        B + "test_bytes_cross_unchanged_in_both_directions",
    ),
    (
        "2 EOF half-closes the other side",
        BRIDGE + "pump",
        "destination.shutdown(socket.SHUT_WR)",
        "pass",
        B + "test_a_client_half_close_still_carries_the_reply",
    ),
    (
        "3 EOF closes only the sending half",
        BRIDGE + "pump",
        "destination.shutdown(socket.SHUT_WR)",
        "destination.shutdown(socket.SHUT_RDWR)",
        B + "test_a_client_half_close_still_carries_the_reply",
    ),
    (
        "4 an error wakes the opposite pump",
        BRIDGE + "forward",
        "_wake(client, upstream)",
        "pass",
        B + "test_an_upstream_reset_ends_an_idle_client",
    ),
    (
        "5 a failed leaf dial authors no reply",
        BRIDGE + "forward",
        "    except OSError:\n        client.close()\n        return",
        "    except OSError:\n        client.sendall(b'HTTP/1.1 502 Bad Gateway\\r\\n\\r\\n')\n"
        "        client.close()\n        return",
        B + "test_a_failed_leaf_dial_closes_the_client_with_no_byte",
    ),
    (
        "6 a failed leaf dial closes the client",
        BRIDGE + "forward",
        "    except OSError:\n        client.close()\n        return",
        "    except OSError:\n        return",
        B + "test_a_failed_leaf_dial_closes_the_client_with_no_byte",
    ),
    (
        "7 the vendor environment carries the proxy",
        BRIDGE + "environment",
        '{**inherited, "HTTPS_PROXY": f"http://{PROXY_HOST}:{PROXY_PORT}"}',
        "{**inherited}",
        B + "test_the_vendor_environment_adds_exactly_the_proxy",
    ),
    (
        "8 the proxy names the forwarder's port",
        BRIDGE + "environment",
        'f"http://{PROXY_HOST}:{PROXY_PORT}"',
        '"http://127.0.0.1:3128"',
        B + "test_the_vendor_environment_adds_exactly_the_proxy",
    ),
    (
        "9 no second proxy variable",
        BRIDGE + "environment",
        '"HTTPS_PROXY": f"http://{PROXY_HOST}:{PROXY_PORT}"}',
        '"HTTPS_PROXY": f"http://{PROXY_HOST}:{PROXY_PORT}", "ALL_PROXY": "x"}',
        B + "test_the_vendor_environment_adds_exactly_the_proxy",
    ),
    (
        "10 a regular-file leaf is not a socket",
        BRIDGE + "leaf_is_socket",
        "return stat.S_ISSOCK(os.lstat(LEAF).st_mode)",
        "return os.lstat(LEAF) is not None",
        B + "test_the_leaf_check_refuses_anything_but_a_socket[regular-file]",
    ),
    (
        "11 an absent leaf is not a socket",
        BRIDGE + "leaf_is_socket",
        "    except OSError:\n        return False",
        "    except OSError:\n        return True",
        B + "test_the_leaf_check_refuses_anything_but_a_socket[absent]",
    ),
    (
        "12 the script refuses without a leaf",
        BRIDGE + "main",
        "if not leaf_is_socket():",
        "if False:",
        B + "test_the_script_refuses_before_binding_without_a_leaf[regular-file]",
    ),
    (
        "13 EOF is never readiness",
        BRIDGE + "start_forwarder",
        "if ready != READY:",
        "if ready not in (READY, b''):",
        B + "test_a_forwarder_that_cannot_isolate_is_never_ready",
    ),
    (
        "14 readiness is required at all",
        BRIDGE + "start_forwarder",
        "if ready != READY:",
        "if False:",
        B + "test_a_forwarder_that_cannot_isolate_is_never_ready",
    ),
    (
        "15 readiness follows isolation",
        BRIDGE + "start_forwarder",
        "            _isolate(listener.fileno(), write_end)\n"
        "            os.write(write_end, READY)",
        "            os.write(write_end, READY)\n"
        "            _isolate(listener.fileno(), write_end)",
        B + "test_a_forwarder_that_cannot_isolate_is_never_ready",
    ),
    (
        "16 isolation replaces the payload's stdout",
        BRIDGE + "_isolate",
        "for fd in (0, 1, 2):",
        "for fd in (0, 2):",
        B + "test_the_script_execs_only_after_the_forwarder_is_ready",
    ),
    (
        "17 the parent drops its listener before exec",
        BRIDGE + "main",
        "        listener.close()",
        "        pass",
        B + "test_the_script_execs_only_after_the_forwarder_is_ready",
    ),
    (
        "18 the launcher adds the bridge only with a leaf",
        LAUNCHER + "LinuxLauncher.argv",
        '"--setenv", "CODEX_HOME", NATIVE_HOME,\n        ]',
        '"--setenv", "CODEX_HOME", NATIVE_HOME,\n        ]\n'
        '        command = ("/usr/bin/python3", "-I", BRIDGE_SCRIPT, *command)',
        L + "test_no_egress_socket_means_no_leaf_and_the_namespace_stays_unshared",
    ),
    (
        "19 the launcher adds the bridge with a leaf",
        LAUNCHER + "LinuxLauncher.argv",
        'command = ("/usr/bin/python3", "-I", BRIDGE_SCRIPT, *command)',
        "pass",
        L + "test_a_current_egress_socket_gets_one_read_only_leaf",
    ),
    (
        "20 exec restores the interpreter's ignored signals",
        BRIDGE + "_restore_signals",
        "for kind in (signal.SIGPIPE, signal.SIGXFSZ):",
        "for kind in ():",
        B + "test_the_script_execs_only_after_the_forwarder_is_ready",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
