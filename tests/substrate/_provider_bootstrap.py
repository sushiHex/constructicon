"""Observe this namespace, start one bridge, then replace ourselves.

The existing supervisor owns the bootstrap, native payload, bridge, and every
descendant. Only trusted test setup is read before exec, never model commands.
"""

import json
import os
import select
import socket
import stat
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

# Fixed immutable imports; isolated Python does not search the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _provider_transport import ENDPOINT


def topology(expected):
    endpoint = Path(ENDPOINT)
    observed = endpoint.lstat()
    if not stat.S_ISSOCK(observed.st_mode) or [observed.st_dev, observed.st_ino] != expected:
        raise ValueError("mounted endpoint differs")
    mounts = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()]
    leaf = [row for row in mounts if row[4] == ENDPOINT]
    if len(leaf) != 1 or "ro" not in leaf[0][5].split(","):
        raise ValueError("endpoint must be one read-only leaf mount")
    required = {"/", "/proc", "/dev", "/tmp", ENDPOINT}
    device_mounts = {
        "/dev/" + name for name in ("null", "zero", "full", "random", "urandom", "tty")
    }
    allowed = required | device_mounts | {"/dev/pts", "/dev/shm"}
    points = [row[4] for row in mounts]
    if not required <= set(points) or not set(points) <= allowed or len(points) != len(set(points)):
        raise ValueError("unexpected mount inventory: " + json.dumps(mounts))
    for row in mounts:
        point, flags, filesystem = row[4], row[5].split(","), row[row.index("-") + 1]
        if point == "/" and "ro" not in flags:
            raise ValueError("runtime root is not read-only")
        expected = {"/proc": "proc", "/tmp": "tmpfs", "/dev": "tmpfs", "/dev/pts": "devpts"}
        if point in expected and filesystem != expected[point]:
            raise ValueError("unexpected mount filesystem")
        if point in device_mounts and not stat.S_ISCHR(Path(point).stat().st_mode):
            raise ValueError("unexpected device mount")
    interfaces = {line.split(":")[0].strip() for line in
                  Path("/proc/net/dev").read_text().splitlines()[2:]}
    routes = Path("/proc/net/route").read_text().splitlines()[1:]
    ipv6_routes = Path("/proc/net/ipv6_route").read_text().splitlines()
    if interfaces != {"lo"} or routes or any(row.split()[-1] != "lo" for row in ipv6_routes):
        raise ValueError("external interface or route")
    fds = {}
    for entry in Path("/proc/self/fd").iterdir():
        # The descriptor used by iterdir itself is already closed.
        with suppress(FileNotFoundError):
            fds[entry.name] = os.readlink(entry)
    if set(fds) != {"0", "1", "2"}:
        raise ValueError("unexpected inherited descriptor")
    return {
        "endpoint": ENDPOINT, "identity": expected, "mount": leaf[0],
        "mounts": mounts, "interfaces": sorted(interfaces), "routes": routes,
        "ipv6_routes": ipv6_routes, "fds_before_setup": fds,
        "namespaces": {name: os.readlink(f"/proc/self/ns/{name}")
                       for name in ("net", "pid", "mnt", "user")},
    }


def main():
    from bootstrap import launch, prepare

    setup = json.loads(sys.stdin.buffer.readline(256 * 1024))
    placement = setup.pop("placement")
    if set(placement) != {"identity", "deadline", "probe", "fault"}:
        raise ValueError("unexpected placement fields")
    if placement["fault"] not in {"none", "before_ready", "request", "response", "response_eof"}:
        raise ValueError("unexpected bridge fault control")
    observed = topology(placement["identity"])
    setup = prepare(setup)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            port = listener.getsockname()[1]
            # close_fds removes guards and supervisor descriptors. Only this
            # fixed listener and readiness pipe supplement private stdio.
            child = subprocess.Popen(
                ["/usr/bin/python3", "-I", "/opt/native-startup/_provider_bridge.py",
                 str(listener.fileno()), str(write_fd), str(placement["deadline"]),
                 placement["fault"]],
                pass_fds=(listener.fileno(), write_fd), close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            )
        os.close(write_fd)
        write_fd = -1
        remaining = placement["deadline"] - time.monotonic()
        if remaining <= 0 or not select.select([read_fd], [], [], remaining)[0]:
            raise ValueError("bridge readiness deadline")
        if os.read(read_fd, 2) != b"R":
            raise ValueError("bridge not ready")
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
    observed.update({"port": port, "bridge_pid": child.pid})
    print(json.dumps({"placement": observed}), flush=True)
    # The descriptor is a setup observation, not an observed bridge outcome.
    # No wait(), signal handler, or process owner is added here.
    if placement["probe"] is not None:
        os.execv("/usr/bin/python3", ["python3", "-I", "-c", placement["probe"], str(port)])
    setup["arguments"].extend(["-c", f'model_providers.probe.base_url="http://127.0.0.1:{port}/v1"'])
    launch(setup)


if __name__ == "__main__":
    main()
