"""Assertion mutants for the native tool inventory on production's own launch path.

The placement lane proves what the sealed bytes offer the model; these prove
production mounts those bytes. They run inside the provisioned zone, beside
``tests/substrate/test_native_egress_bridge.py`` (M8-N5-native-tool-inventory.md).
"""

from _mutations import run

LAUNCH = "constructicon.substrate.executors.linux:LinuxLauncher._launch"
ZONE = (
    "tests/substrate/test_native_egress_bridge.py::"
    "test_a_vendored_native_zone_reads_the_seal_never_the_installed_catalog"
)

MUTANTS = (
    (
        "N5-Z1 production mounts the seal, not the installed catalog",
        LAUNCH,
        "layout = None if native_store is None else NativeLayout.seal(self.vendor)",
        "layout = None if native_store is None else NativeLayout("
        "sealed_data_fd(NATIVE_ENVIRONMENTS), sealed_data_fd(self.vendor.catalog.read_bytes()))",
        ZONE,
    ),
    (
        "N5-Z2 production mounts the launcher's environment file",
        LAUNCH,
        "layout = None if native_store is None else NativeLayout.seal(self.vendor)",
        "layout = None if native_store is None else replace("
        "NativeLayout.seal(self.vendor), environments_fd=sealed_data_fd(b''))",
        ZONE,
    ),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
