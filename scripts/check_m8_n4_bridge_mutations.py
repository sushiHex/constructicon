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
RELAY = "constructicon.substrate.executors.egress:EgressRelay."
LANE = "constructicon.substrate.executors.codex_lane:"
E = "tests/substrate/test_egress.py::"
T = "tests/substrate/test_codex_lane.py::"
V = "tests/substrate/test_native_vendor.py::"
VENDOR = LAUNCHER + "NativeVendor.check"

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
    # --- N4 lane evidence (M8-N4-state-review.md, sections 4 and 5) ---------
    (
        "N4-L1 an accepted sealed destination is counted by its policy name",
        RELAY + "_handle",
        'self.destinations["accepted:" + sealed] += 1',
        "pass",
        E + "test_a_sealed_destination_is_counted_accepted_and_relayed_by_its_policy_name",
    ),
    (
        "N4-L2 relayed bytes are counted once per connection",
        RELAY + "_pump",
        "        relayed = None",
        "        pass",
        E + "test_a_sealed_destination_is_counted_accepted_and_relayed_by_its_policy_name",
    ),
    (
        "N4-L3 relayed is counted only after an upstream byte moved",
        RELAY + "_pump",
        # The runner dedents the method, so its body sits at four spaces.
        "    while True:\n        data = await _receive(source, CHUNK_BYTES)",
        "    if relayed is not None:\n        self.destinations[relayed] += 1\n"
        "        relayed = None\n"
        "    while True:\n        data = await _receive(source, CHUNK_BYTES)",
        E + "test_a_sealed_destination_is_counted_accepted_and_relayed_by_its_policy_name",
    ),
    (
        "N4-L4 a lane directory must be fresh",
        LANE + "launch",
        "lane_dir.mkdir(mode=0o700)",
        "lane_dir.mkdir(mode=0o700, exist_ok=True)",
        T + "test_an_existing_lane_directory_refuses_before_anything_opens",
    ),
    (
        "N4-L5 any denial in a clean lane is a fault",
        LANE + "run_startup",
        "if bool(launched.denied) != expect_denial:",
        "if False:",
        T + "test_any_denial_in_a_clean_startup_is_a_fault",
    ),
    (
        "N4-L6 a measured refresh needs the credential write",
        LANE + "run_startup",
        'and launched.credential["mtime_changed"] and not faults',
        "and not faults",
        T + "test_a_connection_without_a_write_is_not_a_measured_refresh",
    ),
    (
        "N4-L7 evidence marks completed only as its last act",
        LANE + "EvidenceFile.publish",
        'complete = {**evidence, "completed": True}',
        'complete = {"completed": True, **evidence}',
        T + "test_evidence_is_create_exclusive_completed_last_and_content_addressed",
    ),
    (
        "N4-L8 evidence is linked into place, never replacing a file",
        LANE + "EvidenceFile.publish",
        "os.link(self.temporary, self.path)",
        "os.replace(self.temporary, self.path)",
        T + "test_a_reservation_never_replaces_an_existing_file",
    ),
    (
        "N4-L9 a failed login is a fault",
        LANE + "run_login",
        "faults += launch_faults(launched)",
        "pass",
        T + "test_a_failed_or_denied_login_is_a_fault",
    ),
    (
        "N4-L10 the launch spawns only after its custody check",
        LANE + "launch",
        "before_spawn=custody.check",
        "before_spawn=lambda: None",
        T + "test_the_login_code_reaches_the_operator_and_never_the_evidence",
    ),
    # --- the lane's side of an inherited maintenance (interface item 4) ---
    (
        "N4-L11 the lane proves its parent took the lock",
        LANE + "main",
        "parent=os.getppid()",
        "parent=os.getpid()",
        T + "test_a_maintenance_lane_proves_the_custody_its_parent_passed",
    ),
    (
        "N4-L12 a maintenance lane requires an inherited lock and floor",
        LANE + "main",
        'if options.custody == "maintenance" and (options.lock_fd is None',
        'if False and (options.lock_fd is None',
        T + "test_a_maintenance_lane_never_starts_without_an_inherited_lock",
    ),
    # --- the lane review's findings (2026-09-24) ---
    (
        "N4-L13 a login runs only inside maintenance (CC-1)",
        LANE + "run_login",
        'if custody.kind != "maintenance":',
        "if False:",
        T + "test_a_login_never_runs_under_the_active_selection",
    ),
    (
        "N4-L14 the command line refuses an active-selection login (CC-1)",
        LANE + "main",
        'if login and options.custody != "maintenance":',
        "if False:",
        T + "test_the_command_line_never_runs_a_login_under_the_active_selection",
    ),
    *(
        (
            f"N4-L{number} a startup pass requires: {fact}",
            LANE + "run_startup",
            anchor,
            "(True,",
            T + test,
        )
        for number, (fact, anchor, test) in enumerate((
            ("a completed gate", "(conversation.gate_completed,",
             "test_a_startup_passes_only_on_affirmative_facts[never-conversed]"),
            ("exactly the four methods",
             "(methods == [named_method(method) for method in STARTUP_METHODS],",
             "test_the_four_methods_are_compared_not_assumed"),
            ("a judged readback", "(conversation.before_spend is not None,",
             "test_a_startup_passes_only_on_affirmative_facts[never-conversed]"),
            ("no session damage",
             "(not observation.malformed_records and observation.first_error is None,",
             "test_session_damage_is_a_startup_fault"),
        ), start=15)
    ),
    *(
        (
            f"N4-L{number} every lane requires: {fact}",
            LANE + "launch_faults",
            anchor,
            "(True,",
            T + f"test_a_startup_passes_only_on_affirmative_facts[{case}]",
        )
        for number, (fact, anchor, case) in enumerate((
            ("an exchange that did not raise", "(not launched.exchange_failed,",
             "exchange-raised"),
            ("no timeout", "(not result.timed_out,", "timed-out"),
            ("no exceeded bound", "(result.bound_exceeded is None,", "bound"),
            ("a clean exit",
             "(result.returncode == 0 and result.payload_returncode == 0,", "killed"),
            ("a closed relay", "(launched.relay_closed,", "relay-unclosed"),
            ("a passing terminal check", '(launched.credential["checked"],', "terminal-check"),
            ("one regular 0600 credential",
             '(launched.credential["present"] and launched.credential["regular_0600"],',
             "credential-mode"),
        ), start=19)
    ),
    (
        "N4-L26 a clean exit needs the trusted reaper's status too",
        LANE + "launch_faults",
        "result.returncode == 0 and result.payload_returncode == 0",
        "result.returncode == 0",
        T + "test_a_startup_passes_only_on_affirmative_facts[no-payload-status]",
    ),
    (
        "N4-L27 the exchange's own failure is recorded",
        LANE + "launch",
        "result, exchange_failed = exc.result, True",
        "result, exchange_failed = exc.result, False",
        T + "test_a_startup_passes_only_on_affirmative_facts[exchange-raised]",
    ),
    (
        "N4-L28 the relay's closure is measured",
        LANE + "launch",
        "relay_closed=relay.closed is True,",
        "relay_closed=True,",
        T + "test_a_startup_passes_only_on_affirmative_facts[relay-unclosed]",
    ),
    (
        "N4-L29 the terminal custody check runs after the exchange (CC-2)",
        LANE + "launch",
        "custody.check()",
        "pass",
        T + "test_a_startup_passes_only_on_affirmative_facts[terminal-check]",
    ),
    (
        "N4-L30 the credential's link count is measured",
        LANE + "launch",
        '"present": links == 1,',
        '"present": True,',
        T + "test_a_startup_passes_only_on_affirmative_facts[credential-unlinked]",
    ),
    (
        "N4-L31 the credential's mode is measured",
        LANE + "launch",
        '"regular_0600": stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600,',
        '"regular_0600": True,',
        T + "test_a_startup_passes_only_on_affirmative_facts[credential-mode]",
    ),
    (
        "N4-L32 a login must write the credential (CC-2)",
        LANE + "run_login",
        'if not launched.credential["mtime_changed"]:',
        "if False:",
        T + "test_a_login_that_wrote_nothing_is_a_fault",
    ),
    (
        "N4-L33 a first login creates its credential under the same custody",
        LANE + "run_login",
        "custody.create_credential()",
        "pass",
        T + "test_the_first_login_creates_the_empty_credential_under_the_same_custody",
    ),
    (
        "N4-L34 the evidence records the client it ran (CC-3)",
        LANE + "_base",
        '"sha256": executable.sha256},',
        '"sha256": ""},',
        T + "test_a_clean_startup_records_the_four_methods_and_nothing_identifying",
    ),
    (
        "N4-L35 a lane runs only the bound vendor client",
        LANE + "vendor_executable",
        "if launcher.vendor is None:",
        "if False:",
        T + "test_a_launcher_without_the_bound_vendor_runs_no_lane",
    ),
    (
        "N4-L36 an existing evidence path refuses at reservation (RL-2)",
        LANE + "EvidenceFile.__init__",
        "if os.path.lexists(path):",
        "if False:",
        T + "test_an_unusable_evidence_path_refuses_before_any_launch",
    ),
    (
        "N4-L37 the record is synced before it is published (RL-6)",
        LANE + "EvidenceFile.publish",
        "os.fsync(self._fd)",
        "pass",
        T + "test_a_failed_evidence_write_leaves_no_file_at_all[fsync]",
    ),
    (
        "N4-L38 a failure after the link removes the published name",
        LANE + "EvidenceFile.abandon",
        "if self._linked:",
        "if False:",
        T + "test_a_failure_after_the_link_removes_the_published_name_too",
    ),
    (
        "N4-L39 the startup hold lies inside the deadline",
        LANE + "run_startup",
        "if not 0 <= hold_s < deadline_s:",
        "if False:",
        T + "test_a_hold_outside_the_deadline_refuses_before_launch[-1.0]",
    ),
    (
        "N4-L40 the login's default deadline covers the device flow (RL-7)",
        LANE + "main",
        "LOGIN_DEADLINE_S if login else STARTUP_DEADLINE_S",
        "STARTUP_DEADLINE_S",
        T + "test_the_login_deadline_covers_the_vendors_device_flow",
    ),
    (
        "N4-L41 the command line bounds the hold",
        LANE + "main",
        "if not 0 <= options.hold < deadline or (options.hold and login):",
        "if False:",
        T + "test_startup_options_are_bounded_and_lane_specific[hold-at-deadline]",
    ),
    # --- the bound vendor tree (orchestrator decision, 2026-09-24) ---
    (
        "N4-V1 the catalog is custody-checked",
        VENDOR,
        "_require_root_fixed(os.lstat(self.catalog), kind=stat.S_IFREG)",
        "pass",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[catalog-not-root]",
    ),
    (
        "N4-V2 the tree's own root is custody-checked",
        VENDOR,
        "_require_root_fixed(os.lstat(self.tree), kind=stat.S_IFDIR)",
        "pass",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[tree-not-root]",
    ),
    (
        "N4-V3 every file in the tree is custody-checked",
        VENDOR,
        "_require_root_fixed(info, kind=stat.S_IFREG)",
        "pass",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[file-not-root]",
    ),
    (
        "N4-V4 every directory in the tree is custody-checked",
        VENDOR,
        "_require_root_fixed(info, kind=stat.S_IFDIR)",
        "pass",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[directory-not-root]",
    ),
    (
        "N4-V5 the walk descends",
        VENDOR,
        "pending.append(Path(entry.path))",
        "pass",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[file-not-root]",
    ),
    (
        "N4-V6 every ancestor is root-owned and not writable",
        VENDOR,
        "if info.st_uid != 0 or info.st_mode & 0o022:",
        "if False:",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[writable-ancestor]",
    ),
    (
        "N4-V7 group or other write refuses",
        LAUNCHER + "_require_root_fixed",
        "info.st_mode & 0o6022",
        "info.st_mode & 0o6000",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[group-writable-file]",
    ),
    (
        "N4-V8 a set-id bit refuses",
        LAUNCHER + "_require_root_fixed",
        "info.st_mode & 0o6022",
        "info.st_mode & 0o0022",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[set-id-file]",
    ),
    (
        "N4-V9 an owner other than root refuses",
        LAUNCHER + "_require_root_fixed",
        "info.st_uid != 0 or ",
        "",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[file-not-root]",
    ),
    (
        "N4-V10 a link or device refuses",
        LAUNCHER + "_require_root_fixed",
        "stat.S_IFMT(info.st_mode) != kind or ",
        "",
        V + "test_a_vendor_tree_or_catalog_out_of_root_custody_refuses[link-in-tree]",
    ),
    (
        "N4-V11 every probe checks the vendor's custody",
        LAUNCHER + "LinuxLauncher.check_artifacts",
        "self.vendor.check()",
        "pass",
        V + "test_every_probe_checks_the_vendor_custody",
    ),
    (
        "N4-V12 the vendor tree is bound read-only",
        LAUNCHER + "LinuxLauncher.argv",
        '"--ro-bind", str(self.vendor.tree), VENDOR_MOUNT,',
        '"--bind", str(self.vendor.tree), VENDOR_MOUNT,',
        V + "test_a_native_launch_binds_the_vendor_tree_and_catalog_read_only",
    ),
    (
        "N4-V13 the launch revision names the bound tree",
        LAUNCHER + "LinuxLauncher.revision",
        "str(self.vendor.tree), str(self.vendor.catalog),",
        "str(self.vendor.catalog), str(self.vendor.catalog),",
        V + "test_the_launch_revision_names_the_bound_vendor",
    ),
    (
        "N4-V14 the installed lane binds the launch set's vendor",
        LANE + "_launcher",
        'vendor=NativeVendor(root / "native-codex", root / "codex-models.json"),',
        "",
        T + "test_the_installed_launcher_binds_the_launch_sets_vendor",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
