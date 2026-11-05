# Preparing a MahaVidyut release

The next prepared version is **0.2.5**. Building artifacts does not create a Git tag or publish a GitHub release.

1. Check the version in `custom_components/aesl_smart_meter/manifest.json`, the changelog and the README. Use the corresponding `vX.Y.Z` tag when publishing.
2. Run the development checks below on Python 3.14. Regenerate the standalone tester after changing its sources.
3. Run `python tools/build_release.py`. This writes the following files under `dist/`:
   - `MahaVidyut-v0.2.5.zip`: installer, runtime files, MIT license and user documentation.
   - `MahaVidyut-tester-v0.2.5.zip`: single-file tester, its requirements, guide and MIT license.
   - `SHA256SUMS`: SHA-256 digests for both ZIPs.
4. Extract the installation ZIP and run its `bash install.sh` against a disposable Home Assistant configuration directory. The offline tests exercise installation from this exact archive layout, upgrades and rollback.
5. Review the release notes in [CHANGELOG.md](../CHANGELOG.md). Keep the live-validation limits visible. A real Home Assistant check should cover startup, existing entries and device metadata; automatic session recovery still needs an expired live account session.
6. Merge the reviewed changes. When ready to publish, create a GitHub release for `v0.2.5` from that commit, copy the 0.2.5 changelog notes and attach both ZIPs plus `SHA256SUMS`.

CI runs the offline checks and uploads these same three files as the `MahaVidyut-release-bundles` workflow artifact. It never publishes a release automatically. The repository currently supports the installer and manual installation; HACS store inclusion has not been submitted or validated.

The builder uses explicit file lists so local environments, caches, account reports and credentials are excluded. ZIP entry timestamps and permissions are fixed, making repeated builds from the same inputs reproducible in the same Python environment.

## Development checks

Run these commands from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
bash -n install.sh
ruff check custom_components tests tools/build_standalone.py tools/build_release.py tools/maha_vidyut_test.py
ruff format --check custom_components tests tools/build_standalone.py tools/build_release.py tools/maha_vidyut_test.py
python tools/build_standalone.py --check
python tools/build_release.py
```

After changing the API client, constants or sensor paths, run `python tools/build_standalone.py` to regenerate the single-file tester. CI checks the generated snapshot and runs the offline suite. The tester itself requires Python 3.10+ and only the packages in `tools/requirements-standalone.txt`; it has no Home Assistant imports.

The [protocol evidence](apk-protocol.md) documents the API contracts and historical live verification. The 0.2.5 offline suite has 249 passing tests with Home Assistant 2026.2.3 on Python 3.14. Other Home Assistant versions, live automatic session recovery, SMS sign-in and account access through the backup host remain unverified. [Local integration brand images](https://contributors.home-assistant.io/core/integrations/brands/#brand-images-for-custom-integrations) require Home Assistant 2026.3 or newer.
