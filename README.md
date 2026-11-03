# MahaVidyut / AESL Smart Meter for Home Assistant

Unofficial, read-only integration for Maharashtra smart meter accounts. Version 0.2.1 adds optional automatic sign-in when a session expires, alongside password sign-in, automatic meter discovery, electricity readings and recent billing.

User-run tests on 14 October 2026 verified login, all six reading APIs and **18 of 20 sensor fields**, including all three phase voltages, all three phase currents and the recent bill amount. The generic Voltage and Current fields had no usable numeric values for that account. The offline suite has 205 passing tests using Home Assistant 2026.2.3 classes, including session recovery during first refresh, use of the saved token in a fresh client to simulate restart, and installation/upgrade behavior. Automatic sign-in still needs verification against an expired live account session on a deployed Home Assistant server.

## Install or upgrade

Home Assistant must be able to reach `https://cportal.esami-mhcca.com`.

1. Download or clone this repository, or extract the installation ZIP.
2. From the downloaded or extracted directory, run `bash install.sh /config`. Replace `/config` with your Home Assistant configuration directory if different. The directory must already exist; omitting the argument defaults to `/config`.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **AESL Smart Meter (Unofficial)**.
5. Enter the consumer/CA number and password you use in MahaVidyut. Leave **Use SMS verification** off for the normal Maharashtra password login. Meter ID and phase are obtained automatically when the service returns them.

The installer uses the integration files beside it when present. A standalone copy downloads the current GitHub `main` branch using `curl` and `unzip`; use the full bundle to install an unpublished build. Bash is required. Only runtime files and the English translation are installed. Upgrades save the previous integration folder under `.aesl_smart_meter_backups` in your configuration directory, and restore it if replacement fails. Home Assistant settings and entries are preserved. The installer prints restart instructions; it does not restart Home Assistant automatically.

For manual installation, copy `custom_components/aesl_smart_meter` into your configuration's `custom_components` directory and replace the previous integration files before restarting.

Existing version 0.1 entries prompt for sign-in after upgrading; complete the reauthentication prompt instead of adding a duplicate entry. Existing consumer and entity IDs are retained. If login omits meter details, a second form accepts a known MID/phase or MID 0 for a setup limited to history and billing. Reauthentication preserves previously known meter details when the service omits them.

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

Use Python 3.10 or newer. Extract the standalone tester bundle, or download `tools/maha_vidyut_test.py` and `tools/requirements-standalone.txt` into the same directory. Run these commands from that directory:

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
| Session expired repeatedly after successful sign-in | Upgrade to 0.2.1, complete reauthentication, and enable **Save password for automatic sign-in** with SMS verification off. |
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

Log messages omit account payloads and authentication material. HTTPS verification is enabled. The integration performs authentication and reading operations and is not endorsed by AESL, MahaVidyut or MSEDCL.

The legacy `tools/inspect_har.py` helper reads old OTP portal captures. It is not required for current setup or the standalone tester. HAR files can contain credentials and should remain private.

## Development and protocol evidence

Use Python 3.14 for the pinned development environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
bash -n install.sh
ruff check custom_components tests tools/build_standalone.py tools/maha_vidyut_test.py
ruff format --check custom_components tests tools/build_standalone.py tools/maha_vidyut_test.py
python tools/build_standalone.py --check
```

After changing the API client, constants or sensor paths, run `python tools/build_standalone.py` to regenerate the single-file tester. CI checks for snapshot drift and runs the offline suite. The tester itself requires only the three packages in `tools/requirements-standalone.txt` and has no Home Assistant imports.

[APK protocol evidence and validation](docs/apk-protocol.md) documents the mobile routes, encryption, request contracts and verified account results. The supplied APK was inspected statically; it was never launched. The repository contains protocol constants and public-key material, with no original APKs, account credentials, tokens or personal reading values.
