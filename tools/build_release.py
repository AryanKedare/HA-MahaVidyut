"""Build allowlisted, reproducible MahaVidyut release ZIPs and SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "aesl_smart_meter"
COMPONENT = Path("custom_components") / DOMAIN
RUNTIME_FILES = (
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
INSTALL_FILES = (
    "install.sh",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "docs/session-recovery.md",
    "docs/standalone-testing.md",
    "docs/apk-protocol.md",
    "docs/releasing.md",
    "docs/api-live-probe.json",
    "docs/api-retry-2026-10-14.json",
) + tuple((COMPONENT / name).as_posix() for name in RUNTIME_FILES)
TESTER_FILES = {
    "tools/maha_vidyut_test.py": "maha_vidyut_test.py",
    "tools/requirements-standalone.txt": "requirements-standalone.txt",
    "docs/standalone-testing.md": "README.md",
    "LICENSE": "LICENSE",
}


def write_zip(target: Path, root: Path, files: dict[str, str]) -> None:
    """Use stable timestamps and permissions; exclude every unlisted file."""
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for source, destination in sorted(files.items()):
            info = ZipInfo(destination, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if source == "install.sh" else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, (root / source).read_bytes())


def build(output: Path, *, root: Path = ROOT) -> list[Path]:
    """Validate all inputs before creating distribution artifacts."""
    for name in set(INSTALL_FILES) | TESTER_FILES.keys():
        source = root / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or symbolic-link release input: {name}")
    manifest = json.loads((root / COMPONENT / "manifest.json").read_text())
    version = manifest["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must have the form X.Y.Z")
    if manifest["domain"] != DOMAIN or manifest["name"] != "MahaVidyut":
        raise ValueError("Unexpected integration domain or display name")
    output.mkdir(parents=True, exist_ok=True)
    installation = output / f"MahaVidyut-v{version}.zip"
    tester = output / f"MahaVidyut-tester-v{version}.zip"
    write_zip(installation, root, {name: name for name in INSTALL_FILES})
    write_zip(tester, root, TESTER_FILES)
    checksums = output / "SHA256SUMS"
    checksums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (installation, tester)
        )
    )
    return [installation, tester, checksums]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        paths = build(args.output)
    except (ValueError, KeyError) as exc:
        parser.exit(1, f"Cannot build release: {exc}\n")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
