"""Offline verification exercises the same streaming verifier as the operator."""

import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest
from scripts.ci.verify_m8_pi_local_artifacts import verify


def test_verifier_requires_both_exact_size_and_digest(tmp_path):
    path = tmp_path / "artifact"
    data = b"fixture artifact"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert verify(path, len(data), digest) == {"bytes": len(data), "sha256": digest}
    with pytest.raises(ValueError):
        verify(path, len(data) + 1, digest)
    with pytest.raises(ValueError):
        verify(path, len(data), "0" * 64)


def test_stager_only_extracts_selected_regular_files_and_refuses_bad_link(tmp_path, monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "scripts" / "ci"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("pi_local_builder", directory /
                                                  "build_m8_pi_local_runtime.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, "verify", lambda *_: None)
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in ("llama-server", "libllama-server-impl.so", "ignored"):
            info = tarfile.TarInfo("llama-b12069/" + name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    target = tmp_path / "selected"
    target.mkdir()
    builder.stage_server(archive, target)
    assert {p.name for p in target.iterdir()} == {"llama-server", "libllama-server-impl.so"}
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("llama-b12069/libbad.so")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        tar.addfile(info)
    target = tmp_path / "rejected"
    target.mkdir()
    with pytest.raises(ValueError, match="unsupported server member"):
        builder.stage_server(archive, target)
