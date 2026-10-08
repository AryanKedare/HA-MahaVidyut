# AESL Smart Meter — unofficial Home Assistant integration (prototype)

**Status: protocol reconstructed and tested offline; live Home Assistant / portal compatibility has not been verified.** It is read-only and works exclusively against `https://cportal.aeslami-mh.com/`. You must only use it with your own AESL consumer account. It is not endorsed by AESL, MahaVidyut, or MSEDCL.

## What is included

- Home Assistant UI config flow with CA/consumer number, optional internal MID and phase.
- AES-256-CBC + RSA-OAEP/SHA-256 portal API client reconstructed from the supplied web client.
- Sensors for import/export energy, instantaneous power, voltage, current, power factor, frequency, daily consumption, billing and (when MID is configured) balance and demand.
- 15-minute polling for readings, 12-hour polling for billing and maximum demand.
- Graceful partial outage handling; intentionally no polling of `MeterLiveData` because both captured requests returned HTTP 500.
- Local HAR inspection helper that extracts *only* CA number, MID and phase; does not copy tokens or OTPs into the integration.

## Installation

1. Extract the ZIP and copy **`custom_components/aesl_smart_meter`** to **`<Home Assistant config>/custom_components/aesl_smart_meter`**.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration**, search for **AESL Smart Meter (Unofficial)**.
4. Enter your own CA number. MID and phase are optional but needed for dashboard/balance and maximum demand sensors.
5. If it fails setup: check your CA number, confirm the portal works in a browser, and see **Limitations** below.

**To identify MID and phase from your own attached HAR**, run locally:

```bash
python tools/inspect_har.py "cportal.aeslami-mh.com(1).har"
```

The tool will show the last 4 digits of CA plus the internal MID and phase. Use `--show-consumer` to print your CA number in full. Do not upload the HAR publicly: it also contains an encrypted login response with usable authentication material, and the portal's response encryption key is embedded in its client.

## How the protocol works (verified from the supplied artifacts)

- `GET /api/Account/GetRSA` is referenced in the Blazor WebCIL as a source of the RSA SPKI `rsa_key`; its live response has *not* been seen in the HAR, so its current behavior still requires validation.
- `POST /api/Dashboard/GetLogHisDyn`: body model `{ "loginID": "<consumer number>" }`.
- `POST /api/Dashboard/LatestIPData`: empty request model.
- `POST /api/Dashboard/`: request model `loginID`, `meterID`, `phase`.
- `POST /api/Dashboard/MDI`: request model `loginID`, `meterID`, `phase` (inferred; test against live portal).
- `POST /api/Payment/MsedclGETRecentBill`: request model `consumerno`, `lang` (language value `1` is provisional).
- POST body is a dot-separated triple of base64 RSA-OAEP-wrapped AES key, base64 RSA-OAEP-wrapped IV, and base64 AES-CBC ciphertext.
- Responses are AES-CBC encrypted with a client-embedded fixed response key and IV. The code includes these protocol constants; neither is the user's login token.

## Energy dashboard

`Imported energy` is modeled as kWh **total_increasing** (also `Exported energy`). Verify the portal's `table1.kWh` field is truly a cumulative meter register before selecting it in **Settings > Dashboards > Energy**; if it is an interval rather than cumulative reading, **do not** use it as an energy-dashboard source. `Energy consumed today` is a daily reading and is **not** configured as total_increasing.

## Limitations and security

- No automated OTP/reCAPTCHA flow is implemented. The captured web client logs in using reCAPTCHA, `TwoFactorVerifyUser`, and `TwoFactorVerifyOTP`, but subsequent meter-data requests in the capture do **not** include an Authorization or Cookie header. Whether the server allows these queries for a previously authenticated consumer in a new Home Assistant session requires live verification. **Do not interpret a working request as permission to access any other consumer's data.**
- This is not a production-ready authentication implementation. If the server enforces OTP-linked sessions, the config flow will correctly report a connection error rather than bypassing the check. A future version should implement an official login mechanism or a supported token/session flow.
- AES-CBC alone is not authenticated encryption; the TLS-verified HTTPS connection is still essential. No SSL verification bypass or untrusted host option is supported.
- The captures show `MeterLiveData` returning 500; this endpoint is intentionally excluded from polling.
- Some real portal readings were `null` (e.g., voltage/current for this capture); these entities correctly become unavailable rather than fabricating values.
- The sample HAR appears to contain a historical `inst_date` of `2025-11`. Do not assume its readings are current.
- The GitHub APK decompilation is not necessarily the same frontend as the Blazor portal. This implementation uses the portal HAR, `ADL.SmartMeter.Client.wasm`, `ADL.SmartMeter.Shared.wasm`, and its captured `scripts/Interop.js`, **not** the reverse-engineered Android application.

## Troubleshooting

Turn on debug logging:

```yaml
logger:
  logs:
    custom_components.aesl_smart_meter: debug
```

Log messages omit decrypted account data, tokens, request bodies and responses. Look for `GetRSA response does not contain rsa_key`, HTTP errors or missing sensor values. A 401/403 indicates session/authentication is needed; 500 may be a backend issue. This module never makes bill payments or writes to the consumer account.

## For maintainers

The `tests` folder contains offline cryptography, parsing and API checks. Run `pytest -q` from this extracted directory. They don't contact the live portal. This repository/package intentionally does **not** contain the user's original HAR, WASM assemblies or JWTs.
