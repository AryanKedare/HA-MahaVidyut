# Preparing a MahaVidyut release

The next prepared version is **0.2.2**. Building artifacts does not create a Git tag or publish a GitHub release.

1. Check the version in `custom_components/aesl_smart_meter/manifest.json`, the changelog and the README. Use the corresponding `vX.Y.Z` tag when publishing.
2. Run the development checks listed in the README on Python 3.14 with `requirements-dev.txt` installed. Regenerate the standalone tester after changing its sources.
3. Run `python tools/build_release.py`. This writes the following files under `dist/`:
   - `MahaVidyut-v0.2.2.zip`: installer, runtime files, MIT license and user documentation.
   - `MahaVidyut-tester-v0.2.2.zip`: single-file tester, its requirements, guide and MIT license.
   - `SHA256SUMS`: SHA-256 digests for both ZIPs.
4. Extract the installation ZIP and run its `bash install.sh` against a disposable Home Assistant configuration directory. The offline tests exercise installation from this exact archive layout, upgrades and rollback.
5. Review the release notes in [CHANGELOG.md](../CHANGELOG.md). Keep the live-validation limits visible. A real Home Assistant check should cover startup, existing entries and device metadata; automatic session recovery still needs an expired live account session.
6. Merge the reviewed changes. When ready to publish, create a GitHub release for `v0.2.2` from that commit, copy the 0.2.2 changelog notes and attach both ZIPs plus `SHA256SUMS`.

CI runs the offline checks and uploads these same three files as the `MahaVidyut-release-bundles` workflow artifact. It never publishes a release automatically. The repository currently supports the installer and manual installation; HACS store inclusion has not been submitted or validated.

The builder uses explicit file lists so local environments, caches, account reports and credentials are excluded. ZIP entry timestamps and permissions are fixed, making repeated builds from the same inputs reproducible in the same Python environment.
