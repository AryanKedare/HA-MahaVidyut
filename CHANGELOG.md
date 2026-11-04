# Changelog

## 0.2.2 — MahaVidyut public release preparation

- Use **MahaVidyut** throughout integration discovery, setup, device metadata, default account titles, logs, Python classes and the standalone tester.
- Set the device manufacturer to **MSEDCL Unofficial Cloud Integration** and remove the former Adani Energy Solutions attribution.
- Include the supplied Mahavitaran / MSEDCL logo in the README, local integration brand assets and installation bundle.
- Migrate generated `AESL <last four characters>` account titles to `MahaVidyut <last four characters>`, preserving custom titles, credentials, account entries, device identifiers and sensor unique IDs.
- Retain the internal `aesl_smart_meter` domain for compatibility with existing installations.
- Update the installer messages and use `.mahavidyut_backups` for upgrade backups and `.mahavidyut-install.*` for staging. Existing backups are left in place.
- Refresh installation, upgrade, automatic sign-in and troubleshooting instructions.
- Add the MIT license, maintainer metadata, reproducible installation/tester ZIPs, checksums and CI artifact builds.

### Included from 0.2.1

- Optional password storage for automatic sign-in after session rejection, with one login and one reading retry per refresh.
- Persist replacement sessions and returned meter context across polling and restarts.
- Enable or remove password storage using Reconfigure without adding another account entry.
- Install bundled files or download GitHub `main`, back up upgrades and restore the previous integration after a failed replacement.

### Validation limits

The offline suite uses synthetic accounts and Home Assistant 2026.2.3 on Python 3.14. The earlier user-run verification on 14 October 2026 confirmed password login, six reading APIs and 18 of 20 sensor fields for one account. Live automatic session recovery, SMS sign-in and behavior on other Home Assistant versions remain unverified. The naming update does not establish additional live API compatibility.

## 0.2.1

Optional automatic session recovery, password-storage reconfiguration and installation/upgrade support. See the [session recovery guide](docs/session-recovery.md).

## 0.2.0

MahaVidyut mobile API support, password sign-in, meter discovery, phase-specific measurements, recent billing and a standalone API tester. See the [protocol evidence](docs/apk-protocol.md).
