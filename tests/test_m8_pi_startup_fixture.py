"""The release image builder fails closed before executing anything."""

import io
import tarfile

import pytest
from scripts.ci import build_m8_pi_startup_fixture as fixture


def test_unpinned_archive_is_refused_before_extraction(tmp_path):
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"foreign archive")
    destination = tmp_path / "runtime"
    with pytest.raises(ValueError, match="archive digest differs"):
        fixture.stage_release(archive, destination)
    assert not destination.exists()


def test_pinned_archive_cannot_install_a_link_in_the_runtime_allowlist(tmp_path, monkeypatch):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        ignored = tarfile.TarInfo("pi/examples/never-installed.js")
        ignored.size = 4
        tar.addfile(ignored, io.BytesIO(b"bait"))
        link = tarfile.TarInfo("pi/pi")
        link.type = tarfile.SYMTYPE
        link.linkname = "/usr/bin/python3"
        tar.addfile(link)
    monkeypatch.setattr(fixture, "ARCHIVE_SHA", fixture.sha(archive))
    destination = tmp_path / "runtime"
    with pytest.raises(ValueError, match="unique regular file"):
        fixture.stage_release(archive, destination)
    assert not destination.exists()


def test_startup_libraries_use_the_existing_sparse_image_loader_path(tmp_path):
    host = tmp_path / "host/usr/lib/x86_64-linux-gnu"
    host.mkdir(parents=True)
    runtime = tmp_path / "runtime"
    library = runtime / "lib/x86_64-linux-gnu"
    library.mkdir(parents=True)
    expected = {
        "libpthread.so.0", "libdl.so.2", "libxcb.so.1", "libXau.so.6",
        "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0",
    }
    for name in expected | {"unreviewed.so"}:
        (host / name).write_text(name, encoding="ascii")
    (library / "libdl.so.2").write_bytes(b"already curated")
    observed = fixture.stage_libraries(host, runtime)
    assert observed == {
        f"lib/x86_64-linux-gnu/{name}": fixture.sha(library / name) for name in expected
    }
    assert {item.name for item in library.iterdir()} == expected
    assert (library / "libdl.so.2").read_bytes() == b"already curated"
    assert not (runtime / "usr").exists()
