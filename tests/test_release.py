"""Exercise the actual release bundles, including installation and tester startup."""

import hashlib
import shutil
import subprocess
import sys
from zipfile import ZipFile

import pytest

from tools import build_release


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    for name in set(build_release.INSTALL_FILES) | build_release.TESTER_FILES.keys():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build_release.ROOT / name, target)
    (root / ".env").write_text("PRIVATE=test-password")
    (root / "account-report.json").write_text("private readings")
    return root


def test_bundles_are_reproducible_allowlisted_and_checksummed(source, tmp_path):
    first = build_release.build(tmp_path / "first", root=source)
    second = build_release.build(tmp_path / "second", root=source)

    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]
    installation, tester, checksums = first
    assert installation.name == "MahaVidyut-v0.2.2.zip"
    assert tester.name == "MahaVidyut-tester-v0.2.2.zip"
    with ZipFile(installation) as archive:
        assert set(archive.namelist()) == set(build_release.INSTALL_FILES)
        assert archive.getinfo("install.sh").external_attr >> 16 & 0o777 == 0o755
        assert (
            archive.read("custom_components/aesl_smart_meter/brand/icon.png")
            == (source / build_release.COMPONENT / "brand/icon.png").read_bytes()
        )
    with ZipFile(tester) as archive:
        assert set(archive.namelist()) == set(build_release.TESTER_FILES.values())
    assert checksums.read_text() == "".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in (installation, tester)
    )


def test_extracted_release_installs_without_network_and_tester_runs(source, tmp_path):
    installation, tester, _ = build_release.build(tmp_path / "bundles", root=source)
    extracted = tmp_path / "installation"
    with ZipFile(installation) as archive:
        archive.extractall(extracted)
    config = tmp_path / "HA config"
    config.mkdir()
    result = subprocess.run(
        ["bash", str(extracted / "install.sh"), str(config)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Using bundled MahaVidyut integration files" in result.stdout
    assert "Downloading" not in result.stdout
    installed = config / build_release.COMPONENT
    assert {
        p.relative_to(installed).as_posix() for p in installed.rglob("*") if p.is_file()
    } == set(build_release.RUNTIME_FILES)

    tester_dir = tmp_path / "tester"
    with ZipFile(tester) as archive:
        archive.extractall(tester_dir)
    result = subprocess.run(
        [sys.executable, str(tester_dir / "maha_vidyut_test.py"), "--help"],
        cwd=tester_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Test MahaVidyut sign-in" in result.stdout


@pytest.mark.parametrize("invalid", ["missing", "symlink"])
def test_incomplete_bundles_fail_before_writing_artifacts(source, tmp_path, invalid):
    logo = source / build_release.COMPONENT / "brand/icon.png"
    if invalid == "symlink":
        original = tmp_path / "logo.png"
        logo.rename(original)
        logo.symlink_to(original)
    else:
        logo.unlink()
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="release input"):
        build_release.build(output, root=source)

    assert not output.exists()
