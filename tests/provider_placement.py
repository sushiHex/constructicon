"""Test-only composition: the parent recipe plus exactly one read-only leaf."""

import hashlib
import inspect
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from constructicon.core.identity import digest
from constructicon.substrate.executors.linux import LinuxLauncher
from tests import native_provider
from tests.substrate import _provider_transport
from tests.substrate._provider_transport import ENDPOINT

BOOTSTRAP = "/opt/native-startup/_provider_bootstrap.py"
PLACEMENT_PROMPT = "Return the inert placement fixture response."


@dataclass(frozen=True, kw_only=True)
class PlacementLauncher(LinuxLauncher):
    endpoint: Path
    endpoint_identity: tuple[int, int]

    def argv(self, command, *, workspace, posture):
        if workspace is not None:
            raise ValueError("placement fixture has no workspace")
        endpoint = self.endpoint.lstat()
        if (not self.endpoint.is_absolute() or self.endpoint.resolve() != self.endpoint
                or not stat.S_ISSOCK(endpoint.st_mode)
                or endpoint.st_uid != os.getuid()
                or (endpoint.st_dev, endpoint.st_ino) != self.endpoint_identity):
            raise ValueError("fixture endpoint changed or is not an owned socket")
        argv = LinuxLauncher.argv(self, command, workspace=None, posture=posture)
        index = argv.index("--")
        return (*argv[:index], "--ro-bind", str(self.endpoint), ENDPOINT, *argv[index:])

    @property
    def revision(self):
        return digest("test-provider-placement", 1, {
            "parent": super().revision, "composition": inspect.getsource(PlacementLauncher),
            "endpoint": ENDPOINT,
            "peer": hashlib.sha256(Path(native_provider.__file__).read_bytes()).hexdigest(),
            "transport": hashlib.sha256(
                Path(_provider_transport.__file__).read_bytes(),
            ).hexdigest(),
        })
