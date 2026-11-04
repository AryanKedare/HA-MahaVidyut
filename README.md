# MahaVidyut for Home Assistant

<p align="center">
  <img src="custom_components/aesl_smart_meter/brand/icon.png" alt="Mahavitaran / MSEDCL logo" width="240" />
</p>

**by MSEDCL Unofficial Cloud Integration**

An unofficial, read-only cloud integration for Maharashtra smart meter accounts using MahaVidyut. Sign in with your consumer/CA number to see electricity readings, consumption, account balance and recent billing in Home Assistant.

## What's new in 0.2.2

- **MahaVidyut** is the name in integration discovery, setup, account titles, device metadata and logs.
- Devices show **by MSEDCL Unofficial Cloud Integration**. The supplied Mahavitaran logo is included in the README and local integration brand assets.
- Existing generated account titles are updated on upgrade. Account entries, device identifiers, sensor unique IDs and custom account titles are preserved.
- The installer uses MahaVidyut naming and saves upgrade backups under `.mahavidyut_backups`.
- Versioned installation and standalone tester bundles, checksums and an MIT license are included in release preparation.

This version includes 0.2.1's optional automatic sign-in after session expiry, saved session persistence and Reconfigure controls. See the [changelog](CHANGELOG.md) for details.

## Requirements and validation

You need a MahaVidyut account with a supported smart meter and a Home Assistant server that can reach `https://cportal.esami-mhcca.com`. The integration is validated offline with **Home Assistant 2026.2.3 on Python 3.14**; other Home Assistant versions have not been validated. [Local brand images](https://contributors.home-assistant.io/core/integrations/brands/#brand-images-for-custom-integrations) are supported by Home Assistant 2026.3 and newer; older versions can show a placeholder icon.

User-run tests on 14 October 2026 verified password login, all six reading APIs and **18 of 20 sensor fields** for one account, including three phase voltages, three phase currents and the recent bill amount. Generic Voltage and Current had no usable numeric values for that account. The 0.2.2 offline suite has **217 passing tests** covering session recovery, persistence, naming migration, installation/upgrade behavior and release bundles. **Automatic sign-in after live session expiry and optional SMS sign-in remain unverified on a deployed Home Assistant server.**

## Install or upgrade

### Installation bundle or source checkout

1. Download or clone this repository, or extract the versioned `MahaVidyut-v0.2.2.zip` installation bundle when published on the [Releases page](https://github.com/AryanKedare/HA-MahaVidyut/releases). For a source checkout, run commands from the repository root.
2. From the downloaded or extracted directory, run `bash install.sh /config`. Replace `/config` with your Home Assistant configuration directory if different. The directory must already exist; omitting the argument defaults to `/config`.
3. Restart Home Assistant.
4. For a new installation, go to **Settings → Devices & services → Add integration** and search for **MahaVidyut**. On upgrade, keep your existing entry.
5. Enter the consumer/CA number and password you use in MahaVidyut. Leave **Use SMS verification** off for the normal Maharashtra password login. Meter ID and phase are obtained automatically when the service returns them.

The installer uses the integration files beside it when present. A standalone copy downloads the current GitHub `main` branch using `curl` and `unzip`; use the full installation bundle for a specific version or an unpublished build. Bash is required. Runtime files, the English translation and the brand image are installed. Upgrades save the previous integration folder under `.mahavidyut_backups` in your configuration directory and restore it if replacement fails. Backups made by earlier installers remain in their original location. The installer prints restart instructions; restart Home Assistant yourself after installation.

### Manual installation and upgrades

Copy `custom_components/aesl_smart_meter` into your configuration's `custom_components` directory, replacing the previous integration files, then restart Home Assistant.

The internal folder/domain remains **`aesl_smart_meter`** so existing entries, device associations, entity IDs and history continue to work. The public name is **MahaVidyut**. Keep this folder name, and use your existing entry after upgrading. Generated account titles such as `AESL 1234` become `MahaVidyut 1234`; custom account titles are retained.

Existing version 0.1 entries prompt for sign-in after upgrading; complete the reauthentication prompt instead of adding a duplicate entry. Existing consumer and entity IDs are retained. If login omits meter details, a second form accepts a known MID/phase or MID 0 for a setup limited to history and billing. Reauthentication preserves previously known meter details when the service omits them.

### Automatic sign-in and credential storage

Home Assistant stores the access token and returned client/meter context. Password storage is off by default. To recover expired sessions automatically, open the existing integration entry's **Reconfigure** menu or its repair dialog, sign in, and enable **Save password for automatic sign-in**. Leave **Use SMS verification** off. This saves the password in Home Assistant's local config entry without separate encryption; it may also be included in backups. SMS codes are never saved. Turning the option off through Reconfigure removes the saved password from the active config entry; existing backups retain their contents.

With automatic sign-in enabled, a session rejection causes one password login and one reading retry per refresh. A new token and meter context are saved for subsequent polls and restarts. Rejected credentials or a rejected replacement session request manual sign-in; connection failures retry on normal polling. Without the option, an expired session requests manual sign-in. See the [session recovery guide](docs/session-recovery.md).

## Sensors and polling

The integration creates 20 sensors. Availability depends on the meter and the values returned by the service.

| Readings | Sensors | Unit |
| --- | --- | --- |
| Imported and exported energy | Imported energy; Exported energy | kWh |
| Power | Active power | kW |
| Voltage | Voltage; R-N voltage; Y-N voltage; B-N voltage | V |
| Current | Current; R phase current; Y phase current; B phase current | A |
| Frequency and power factor | Frequency; Power factor | Hz; unitless |
| Daily consumption and forecast | Energy consumed today; Current month forecast | kWh |
| Account balance and status | Current balance; Connection status | INR; text |
| Demand | Assigned maximum demand | Service value; no unit assigned |
| Recent bill | Recent bill amount; Recent billed consumption | INR; kWh |

Three-phase meters can supply separate phase voltages and currents while the generic Voltage and Current sensors remain unavailable. The integration uses the available phase measurements directly and does not calculate generic readings from them.

Readings poll every 15 minutes. Billing and demand poll every 12 hours after a successful request; failures retry at the next normal poll. Electrical measurements prefer `LatestIPData` and can fall back to `MeterLiveData`. Imported/exported energy use only `LatestIPData` to avoid false resets when an older live register is lower. Failed sources and null, malformed or nonfinite readings are unavailable.

Imported/exported energy use Home Assistant's `total_increasing` classification. Confirm that your account's kWh readings are cumulative registers before selecting them in the Energy dashboard. Register behavior after meter replacement, timestamp timezone and reading freshness have not been validated by the standalone tests.

## Test without Home Assistant

Use Python 3.10 or newer. Extract `MahaVidyut-tester-v0.2.2.zip`, or download `tools/maha_vidyut_test.py` and `tools/requirements-standalone.txt` into the same directory. Run these commands from that directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-standalone.txt
python maha_vidyut_test.py --show-values --report maha-report.json
```

The consumer number and password are prompted without echo. **`--show-values` displays actual readings and bill amounts and includes them in the JSON report.** Omit it for a diagnostic report that shows only availability, response field names and request status/timing. Credentials, tokens, account identifiers and raw responses are omitted in both modes.

The user-run test passed with 18/20 available fields. A missing optional sensor does not make successful API checks fail; accounts and meters can expose different fields. The tester checks all six reading APIs once after login.

See the [standalone tester guide](docs/standalone-testing.md) for options, exit codes, billing fields and report contents.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Connection timeout | Check that Home Assistant or the tester can reach the API host, and that the MahaVidyut app works for the same account. |
| Sign-in rejected | Check the consumer number and app password. Normal Maharashtra login uses password sign-in; optional SMS login has not been verified live. |
| Session expired repeatedly after successful sign-in | Upgrade to 0.2.2, complete reauthentication, and enable **Save password for automatic sign-in** with SMS verification off. See the [recovery guide](docs/session-recovery.md). |
| Old integration/device name after upgrade | Restart Home Assistant after replacing the files and refresh the browser. Existing custom names are preserved. |
| Generic voltage/current unavailable | Use the R/Y/B phase sensors when phase readings are supplied. |
| Tester prints `available` instead of figures | Add `--show-values`; this also includes readings and billing values in the report. |
| One endpoint fails | Other successful sources remain usable. A failed reading source retries at the next poll. |
| All expected sensor values are absent | Inspect the failed/skipped checks and meter context. The tester reports this as a partial result. |

Optional debug logging:

```yaml
logger:
  logs:
    custom_components.aesl_smart_meter: debug
```

Log messages omit account payloads and authentication material. HTTPS verification is enabled. This is a community integration and is not affiliated with or endorsed by MSEDCL / Mahavitaran or the MahaVidyut service.

The legacy `tools/inspect_har.py` helper reads old OTP portal captures. It is not required for current setup or the standalone tester. HAR files can contain credentials and should remain private.

## Development and protocol evidence

Use Python 3.14 for the pinned development environment:

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

After changing the API client, constants or sensor paths, run `python tools/build_standalone.py` to regenerate the single-file tester. CI checks for snapshot drift and runs the offline suite. The tester itself requires only the three packages in `tools/requirements-standalone.txt` and has no Home Assistant imports.

[APK protocol evidence and validation](docs/apk-protocol.md) documents the mobile routes, encryption, request contracts and verified account results. The supplied APK was inspected statically; it was never launched. The repository contains protocol constants and public-key material, with no original APKs, account credentials, tokens or personal reading values.

## Release artifacts

`python tools/build_release.py` writes the installation ZIP, standalone tester ZIP and `SHA256SUMS` to `dist/`. CI also uploads them as the `MahaVidyut-release-bundles` artifact after the checks pass. Builds include only explicitly listed files. See the [release guide](docs/releasing.md) for the publication steps. Creating a build does not publish a GitHub release.

## License and attribution

The integration code is released under the [MIT license](LICENSE), copyright 2026 Aryan Kedare. The Mahavitaran / MSEDCL logo is supplied for identification; logo and trademark rights remain with their respective owners and are not covered by the code license.
