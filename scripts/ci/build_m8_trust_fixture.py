"""A test-only image whose trust store also admits one throwaway CA.

It is the accepting control for the zone's trust store (#77, S3). The image is
the given base image with one change: its ``etc/ssl/certs/ca-certificates.crt``
ends with a CA generated here. The production recipe is unchanged. The CA and
two leaves go to ``PKI``, readable by the service. They are a disposable
runner's fixture and are never archived:
- ``issuer`` names ``auth.openai.com``, the pinned client's device-login host;
- ``stranger`` names another host, the wrong-name control.

Usage: build_m8_trust_fixture.py BASE DEST PKI
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from constructicon.substrate.executors.linux import TRUST_BUNDLE, runtime_digest, runtime_inventory

LEAVES = {"issuer": "auth.openai.com", "stranger": "stranger.invalid"}


def openssl(directory: Path, *arguments: str) -> None:
    subprocess.run(["openssl", *arguments], cwd=directory, check=True, capture_output=True)


def pki(directory: Path) -> bytes:
    directory.mkdir(mode=0o755)
    (directory / "ca.cnf").write_text(
        "[req]\ndistinguished_name = dn\nprompt = no\nx509_extensions = ca\n"
        "[dn]\nCN = n4-trust-throwaway-ca\n[ca]\nbasicConstraints = critical,CA:TRUE\n"
        "keyUsage = critical,keyCertSign,cRLSign\nsubjectKeyIdentifier = hash\n"
    )
    openssl(directory, "req", "-x509", "-new", "-nodes", "-newkey", "ec", "-pkeyopt",
            "ec_paramgen_curve:prime256v1", "-keyout", "ca.key", "-out", "ca.pem", "-days", "1",
            "-config", "ca.cnf")
    for name, host in LEAVES.items():
        (directory / f"{name}.cnf").write_text(
            f"[req]\ndistinguished_name = dn\nprompt = no\n[dn]\nCN = {host}\n"
        )
        (directory / f"{name}.ext").write_text(
            f"subjectAltName = DNS:{host}\nbasicConstraints = critical,CA:FALSE\n"
            "keyUsage = critical,digitalSignature\nextendedKeyUsage = serverAuth\n"
        )
        openssl(directory, "req", "-new", "-nodes", "-newkey", "ec", "-pkeyopt",
                "ec_paramgen_curve:prime256v1", "-keyout", f"{name}.key", "-out", f"{name}.csr",
                "-config", f"{name}.cnf")
        openssl(directory, "x509", "-req", "-in", f"{name}.csr", "-CA", "ca.pem", "-CAkey",
                "ca.key", "-CAcreateserial", "-days", "1", "-out", f"{name}.pem",
                "-extfile", f"{name}.ext")
    (directory / "ca.key").unlink()
    for path in directory.iterdir():
        path.chmod(0o644)
    return (directory / "ca.pem").read_bytes()


def main() -> None:
    if os.getuid() != 0 or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("the trust fixture requires the authorized disposable runner")
    base, destination, directory = map(Path, sys.argv[1:])
    for path in (destination, directory):
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise SystemExit("trust fixture paths must be fresh and absolute")
    runtime_inventory(base)
    shutil.copytree(base, destination, symlinks=True)
    bundle = destination / TRUST_BUNDLE.lstrip("/")
    bundle.chmod(0o644)
    roots = bundle.read_bytes()
    # A bundle may end at its last END line; the appended BEGIN must start a line.
    bundle.write_bytes(roots + (b"" if roots.endswith(b"\n") else b"\n") + pki(directory))
    for path in [*destination.rglob("*"), destination]:
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444)
    print(json.dumps({
        "runtime_digest": str(runtime_digest(destination)),
        "entries": runtime_inventory(destination),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
