"""Run the installer against disposable config directories and offline downloads."""

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "aesl_smart_meter"
RUNTIME = (
    "__init__.py",
    "api.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "manifest.json",
    "sensor.py",
    "strings.json",
    "translations/en.json",
    "brand/icon.png",
    "brand/README.md",
)


def files_under(path):
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


@pytest.fixture
def bundle(tmp_path):
    folder = tmp_path / "source bundle"
    folder.mkdir()
    shutil.copy2(ROOT / "install.sh", folder / "install.sh")
    for name in RUNTIME:
        destination = folder / "custom_components" / DOMAIN / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "custom_components" / DOMAIN / name, destination)
    (folder / "custom_components" / DOMAIN / "not-runtime.txt").write_text("metadata")
    return folder


@pytest.fixture
def config(tmp_path):
    folder = tmp_path / "HA config with spaces"
    (folder / ".storage").mkdir(parents=True)
    (folder / ".storage/core.config_entries").write_text("private existing entries")
    (folder / "configuration.yaml").write_text("default_config:\n")
    unrelated = folder / "custom_components/unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "manifest.json").write_text("unrelated integration")
    return folder


def run_installer(bundle, config, **kwargs):
    return subprocess.run(
        ["bash", str(bundle / "install.sh"), str(config)],
        capture_output=True,
        text=True,
        check=False,
        **kwargs,
    )


@pytest.mark.parametrize("upgrade", [False, True])
def test_local_install_and_upgrade_preserve_config_and_backup(bundle, config, upgrade):
    destination = config / "custom_components" / DOMAIN
    if upgrade:
        destination.mkdir()
        (destination / "old.py").write_text("previous code")
    entries = (config / ".storage/core.config_entries").read_bytes()
    result = run_installer(bundle, config, umask=0o077)

    assert result.returncode == 0, result.stderr
    assert "Using bundled MahaVidyut integration files" in result.stdout
    assert "Restart Home Assistant" in result.stdout
    assert "MahaVidyut by MSEDCL Unofficial Cloud Integration" in result.stdout
    assert "New installation: add MahaVidyut" in result.stdout
    assert "AESL Smart Meter" not in result.stdout
    assert files_under(destination) == {
        name: (bundle / "custom_components" / DOMAIN / name).read_bytes()
        for name in RUNTIME
    }
    assert destination.stat().st_mode & 0o777 == 0o755
    assert (destination / "translations").stat().st_mode & 0o777 == 0o755
    assert (destination / "brand").stat().st_mode & 0o777 == 0o755
    assert (destination / "api.py").stat().st_mode & 0o777 == 0o644
    assert (config / ".storage/core.config_entries").read_bytes() == entries
    assert (config / "configuration.yaml").read_text() == "default_config:\n"
    assert (config / "custom_components/unrelated/manifest.json").exists()
    backups = list((config / ".mahavidyut_backups").glob(f"*/{DOMAIN}"))
    if upgrade:
        assert len(backups) == 1
        assert files_under(backups[0]) == {"old.py": b"previous code"}
    else:
        assert not backups
    assert not list((config / "custom_components").glob(".mahavidyut-install.*"))


@pytest.mark.parametrize("missing", ["translations/en.json", "brand/icon.png"])
def test_missing_runtime_file_leaves_existing_installation_untouched(
    bundle, config, missing
):
    destination = config / "custom_components" / DOMAIN
    destination.mkdir()
    (destination / "old.py").write_text("previous code")
    before = files_under(config)
    (bundle / "custom_components" / DOMAIN / missing).unlink()

    result = run_installer(bundle, config)

    assert result.returncode != 0
    assert "Required integration file" in result.stderr
    assert files_under(config) == before
    assert not (config / ".mahavidyut_backups").exists()


def test_nonexistent_config_is_not_created(bundle, tmp_path):
    config = tmp_path / "missing config"
    result = run_installer(bundle, config)
    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert not config.exists()


def test_symlink_destination_is_preserved(bundle, config, tmp_path):
    target = tmp_path / "linked integration"
    target.mkdir()
    (target / "keep.py").write_text("preserve")
    destination = config / "custom_components" / DOMAIN
    destination.symlink_to(target, target_is_directory=True)

    result = run_installer(bundle, config)

    assert result.returncode != 0
    assert "symbolic link" in result.stderr
    assert destination.is_symlink()
    assert (target / "keep.py").read_text() == "preserve"


def test_failure_after_backup_restores_previous_installation(bundle, config, tmp_path):
    destination = config / "custom_components" / DOMAIN
    destination.mkdir()
    (destination / "old.py").write_text("previous code")
    before = files_under(config)
    commands = tmp_path / "mock commands"
    commands.mkdir()
    mover = commands / "mv"
    mover.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${2##*/}" == .mahavidyut-install.* ]]; then exit 1; fi\n'
        'exec "$INSTALL_TEST_REAL_MV" "$@"\n'
    )
    mover.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "INSTALL_TEST_REAL_MV": shutil.which("mv"),
    }

    result = run_installer(bundle, config, env=env)

    assert result.returncode != 0
    assert "Restored the previous installation" in result.stdout
    assert files_under(config) == before
    assert not list((config / "custom_components").glob(".mahavidyut-install.*"))


@pytest.mark.parametrize("mode", ["success", "download-failure", "bad-layout"])
def test_standalone_downloads_main_and_preserves_existing_files_on_failure(
    bundle, config, tmp_path, mode
):
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    shutil.copy2(ROOT / "install.sh", standalone / "install.sh")
    archive = tmp_path / "download fixture.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name in RUNTIME:
            zipped.write(
                bundle / "custom_components" / DOMAIN / name,
                f"{'wrong-root' if mode == 'bad-layout' else 'HA-MahaVidyut-main'}"
                f"/custom_components/{DOMAIN}/{name}",
            )
    destination = config / "custom_components" / DOMAIN
    destination.mkdir()
    (destination / "old.py").write_text("previous code")
    before = files_under(config)
    commands = tmp_path / "mock commands"
    commands.mkdir()
    downloader = commands / "curl"
    downloader.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$@" > "$INSTALL_TEST_CURL_LOG"\n'
        'if [[ "$INSTALL_TEST_MODE" == download-failure ]]; then exit 28; fi\n'
        'while [[ "$#" -gt 0 ]]; do\n'
        '  if [[ "$1" == -o ]]; then cp "$INSTALL_TEST_ZIP" "$2"; exit; fi\n'
        "  shift\n"
        "done\n"
        "exit 1\n"
    )
    downloader.chmod(0o755)
    log = tmp_path / "curl.log"
    env = {
        **os.environ,
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "INSTALL_TEST_ZIP": str(archive),
        "INSTALL_TEST_MODE": mode,
        "INSTALL_TEST_CURL_LOG": str(log),
    }

    result = run_installer(standalone, config, env=env)

    assert (
        "https://github.com/AryanKedare/HA-MahaVidyut/archive/refs/heads/main.zip"
        in log.read_text()
    )
    if mode == "success":
        assert result.returncode == 0, result.stderr
        assert set(files_under(destination)) == set(RUNTIME)
        assert len(list((config / ".mahavidyut_backups").glob(f"*/{DOMAIN}"))) == 1
    else:
        assert result.returncode != 0
        assert files_under(config) == before
        assert not (config / ".mahavidyut_backups").exists()


def test_help_and_argument_validation_have_no_side_effects(bundle, config):
    before = files_under(config)
    help_result = run_installer(bundle, "--help")
    assert help_result.returncode == 0
    assert "Default config directory: /config" in help_result.stdout
    invalid_result = subprocess.run(
        ["bash", str(bundle / "install.sh"), str(config), "unexpected"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid_result.returncode != 0
    assert "Usage:" in invalid_result.stderr
    assert files_under(config) == before
