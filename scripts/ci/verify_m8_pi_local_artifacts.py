"""Verify selected local Pi experiment inputs without extraction or execution.

This receipt identifies bytes read, not custody of the paths after return.
Staging must independently preserve or reverify the exact verified bytes.
"""

import hashlib
import json
import os
import stat
import sys
from pathlib import Path


PINS = {
    "server": (22934007, "70df3ef8becd405b9ebc13b925387715ae7dccb0f034fd5f46a4034b350130a1"),
    "model": (639446688, "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"),
}


def verify(path, size, digest):
    """Hash the opened regular file and require its actual streamed length."""
    with path.open("rb") as source:
        fd = source.fileno()
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise ValueError("artifact is not a regular file of the pinned size")
        hashed = hashlib.sha256()
        count = 0
        while chunk := source.read(1024 * 1024):
            count += len(chunk)
            if count > size:
                raise ValueError("artifact exceeds the pinned size")
            hashed.update(chunk)
        after = os.fstat(fd)
        if (count != size or hashed.hexdigest() != digest or
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("artifact differs from the pin or changed during verification")
    return {"bytes": count, "sha256": digest}


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_m8_pi_local_artifacts.py SERVER_ARCHIVE MODEL")
    receipt = {name: verify(Path(path), *PINS[name]) for name, path in
               zip(("server", "model"), sys.argv[1:], strict=True)}
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
