"""Pins and transport shape for the additive, read-only discovery continuation."""

import hashlib
import re
import subprocess
from pathlib import Path

from tests.test_m8_operator_commands import _bash

ROOT = Path(__file__).parents[1]
DOCUMENT = ROOT / "docs/plans/handoffs/M8-maintenance-diagnosis-discovery.md"


def test_discovery_helper_pin_matches_reviewed_bytes():
    text = DOCUMENT.read_text(encoding="utf-8")
    pins = re.findall(r"\b[0-9a-f]{64}\b", text)
    digest = hashlib.sha256((ROOT / "scripts/m8_vm_address.py").read_bytes()).hexdigest()
    assert len(pins) == 2 and set(pins) == {digest}
    assert "UNREVIEWED" not in text


def test_discovery_checkout_preserves_pinned_lf_bytes():
    attributes = subprocess.run(
        ["git", "check-attr", "eol", "--", "scripts/m8_vm_address.py"], cwd=ROOT,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
    )
    assert attributes.returncode == 0, attributes.stderr
    assert attributes.stdout.strip() == "scripts/m8_vm_address.py: eol: lf"
    assert b"\r" not in (ROOT / "scripts/m8_vm_address.py").read_bytes()


def test_local_discovery_and_boot_transport_have_closed_stdin_and_parse():
    text = DOCUMENT.read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    assert len(blocks) == 3
    for block in blocks:
        assert block.startswith("exec </dev/null\n")
        checked = subprocess.run([_bash(), "-n", "-c", block],
                                 stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
        assert checked.returncode == 0, checked.stderr
    assert blocks[1] == (
        "exec </dev/null\n/c/Python314/python.exe -I -S -B scripts/m8_vm_address.py\n"
    )
    assert "-o BatchMode=yes -o StrictHostKeyChecking=yes" in blocks[2]
    assert '"HostKeyAlias=$SSH_HOST_KEY_ALIAS"' in blocks[2]
    assert '"$SSH_TARGET" /usr/bin/cat /proc/sys/kernel/random/boot_id' in blocks[2]


def test_boot_transport_invokes_only_fixed_read_with_explicit_identity():
    block = re.findall(r"```bash\n(.*?)```", DOCUMENT.read_text(encoding="utf-8"), re.S)[2]
    fake = """ssh() {
        test "$#" -eq 12 || return 42
        test "$1" = -T || return 42
        test "$2" = -o && test "$3" = BatchMode=yes || return 42
        test "$4" = -o && test "$5" = StrictHostKeyChecking=yes || return 42
        test "$6" = -o && test "$7" = HostKeyAlias=pinned-alias || return 42
        test "$8" = -o && test "$9" = ConnectTimeout=15 || return 42
        test "${10}" = operator@192.168.1.2 || return 42
        test "${11}" = /usr/bin/cat || return 42
        test "${12}" = /proc/sys/kernel/random/boot_id || return 42
        if read -r unexpected; then return 42; fi
        printf '%s\\n' 11111111-2222-3333-4444-555555555555
    }
    SSH_TARGET=operator@192.168.1.2
    SSH_HOST_KEY_ALIAS=pinned-alias
    """
    result = subprocess.run([_bash(), "-c", fake + block], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "11111111-2222-3333-4444-555555555555\n"
    assert result.stderr == ""
