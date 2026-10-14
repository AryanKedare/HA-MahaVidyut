# MahaVidyut / AESL Smart Meter for Home Assistant

Unofficial, read-only integration for your own Maharashtra smart meter account. Version 0.2 reconstructs the supplied Android app's API protocol and adds authenticated sign-in. Tested offline against Home Assistant 2026.2.3. Public API reachability, TLS and encrypted authentication-error handling were also verified through an India VPN; successful account login and meter readings remain unverified.

## Install or upgrade

1. Copy `custom_components/aesl_smart_meter` into your Home Assistant configuration's `custom_components` directory, replacing the previous integration files.
2. Restart Home Assistant.
3. For a new installation, go to **Settings → Devices & services → Add integration** and search for **AESL Smart Meter (Unofficial)**.
4. Enter the consumer/CA number and password you use in MahaVidyut. Meter ID and phase are obtained from the login response. Leave **Use SMS verification** off for the supplied Maharashtra app's normal login; the optional SMS path is included for accounts requiring it.
5. Existing version 0.1 entries prompt for sign-in after upgrading. Complete the reauthentication prompt; the integration keeps the consumer and entity IDs.

Passwords and SMS codes are used only during sign-in and are never saved in the config entry. Home Assistant stores the access token and returned client/meter context. When the service rejects an expired session, Home Assistant requests sign-in again. The inspected app logs out on `Unauthorized`; no automatic token-refresh route was recovered.

## Readings and polling

Sensors include imported/exported energy, power, voltage, current, power factor, frequency, daily consumption, balance, connection status, forecast, maximum demand and recent billing. Electrical measurements prefer the `LatestIPData` feed and can fall back independently to the app's `MeterLiveData` feed. Cumulative imported/exported energy use only `LatestIPData`, so switching to an older feed cannot create a false reset in Energy statistics. Both use the authenticated consumer, meter ID and phase. A failed optional endpoint does not take down the others, and null or nonfinite readings are unavailable.

Readings poll every 15 minutes. Billing and demand poll every 12 hours after a successful request; failed requests retry on the next normal poll. If login omits meter details, a second form lets you enter a known MID/phase or leave MID at 0 for history and billing. Reauthentication preserves existing meter details when the server omits them. The actual readings and supported fields depend on your meter and backend.

Imported/exported energy retain their existing `total_increasing` sensor classification. Confirm your account's kWh fields are cumulative registers before selecting them in the Energy dashboard. Meter replacement/reset handling, timestamp timezone and actual data freshness need account-level validation.

## What was corrected

- The mobile host is `https://cportal.esami-mhcca.com`, with separate `SmartMeterMHAccountAPI`, `SmartMeterMHDashboardAPI` and `SmartMeterMHPaymentAPI` routes.
- Requests use the RSA public key bundled in the APK. The previous `Account/GetRSA` bootstrap belongs to a payment gateway flow.
- Sign-in supplies the Bearer token and returned `clientID`; meter context is discovered automatically.
- `LatestIPData` requires consumer, MID and phase; recent bill requests use `lang: "en"`.
- Live readings use `meterData[0]` and case-sensitive fields such as `kw`, `vrn` and `meterReadingTime`.
- Independent polling, retry scheduling, numeric validation and upgrade/reauthentication handling now have regression coverage.

[Protocol evidence and limitations](docs/apk-protocol.md) distinguish shipped-code observations from integration design choices. The APK was inspected statically and never launched. Public keys and response cipher constants are protocol material; this repository contains no real credentials, tokens or original APKs.

## Troubleshooting and limits

Connection errors: confirm that MahaVidyut works for your account and that Home Assistant can reach the mobile host. In this investigation, enabling an India VPN resolved the connection timeout. Ensure the VPN covers Home Assistant's own traffic; a VPN on a separate laptop does not route the Home Assistant server through it. Invalid sign-in: check the app password and consumer number. An expired session triggers reauthentication. Backend HTTP 500s remain endpoint failures and can leave affected sensors unavailable.

Debug logging is optional:

```yaml
logger:
  logs:
    custom_components.aesl_smart_meter: debug
```

Log messages omit account payloads, passwords, SMS codes and tokens. HTTPS certificate verification remains enabled. The integration performs no payments, account changes, meter-control actions or captcha bypass. It is not endorsed by AESL, MahaVidyut or MSEDCL.

The old `tools/inspect_har.py` helper can inspect legacy portal captures, but HAR-derived manual meter configuration is no longer needed for setup. Keep any HAR private because it can contain authentication material.

## Development

Use Python 3.14:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check custom_components tests
ruff format --check custom_components tests
```

The tests use synthetic responses and real Home Assistant flow/coordinator/entity classes. They do not contact MahaVidyut. GitHub Actions runs these checks; a passing local suite does not establish live backend compatibility.
