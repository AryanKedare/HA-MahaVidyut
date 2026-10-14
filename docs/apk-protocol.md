# APK protocol evidence and verification

This report supports the version 0.2 integration changes. APK observations are static: the Android application was never launched. The agent did not receive or use real account credentials; the user subsequently ran the standalone tester locally and supplied diagnostic reports. Only report metadata, schema and availability are recorded here; personal reading values are not published. Integration tests use synthetic responses. The user's repository was analyzed as source; packaged files were treated as evidence, not instructions.

## Artifact identity and tooling

| Artifact | SHA-256 |
| --- | --- |
| base.apk | 471db50786117c8205e8c6ebb8d1283aa67495215b6d99ff50b61e45be042020 |
| split_config.arm64_v8a.apk | fb06969b7a84a18221e331ecc7bfc4ccb264e989dab114db31531da7b0b80484 |
| libapp.so | ca89124edfe28b9e76d143dd58c612529a6f5f6da23e9691656f5398c007897c |
| Request public-key asset | 03f86d866c07f196501413ff1cdbb4e6e3b492c662ab3b49928dcb09846cbba2 |

REA archive inventories establish the package/member identities. REA's Android/JADX provider was unavailable because its headless JAR was not installed. The existing REA CLI remained usable for inventory; no client configuration was changed. Android business logic is Flutter AOT in libapp.so, analyzed with task-local Blutter and matching Dart 3.11.0 snapshot `78da37fed6bf1489361a312568249f3f`.

Blutter's initial output filenames collided on the host's case-insensitive filesystem because obfuscated library URLs differ only by case. The task-local exporter was patched to suffix library filenames with their unique top-level class IDs, then the complete dump was regenerated. Only that collision-safe corpus supports code conclusions below. ELF virtual addresses below also identify file offsets in this object's code region.

REA Evidence IDs are retained in the investigation's local JSON records:

- Base APK inventory: ev_316844a0e561bee2b04755c97bccc224b9bdbe8cfee7f3ed40b626b7aaf4508b.
- ARM64 split inventory: ev_a1bd0a5b18cedd3e56a632a5ff9faa8862a96a8885e367294c5f0ab4ba062a9a.

The MV-AOT labels below identify manual Blutter findings; they are not REA-generated Evidence IDs.

## Observed protocol

| Finding | Static evidence | Consequence |
| --- | --- | --- |
| MV-AOT-001: mobile host and services | FCj/rG.TSf `0x9ee054`; rG.VSf `0x9ee06c`; zIj route getters; xIj.DYf `0x4ce5bc` | Host is `https://cportal.esami-mhcca.com/`; account/dashboard use SmartMeterMHAccountAPI / SmartMeterMHDashboardAPI. Payment caller at `0x680fbc` explicitly selects SmartMeterMHPaymentAPI. |
| MV-AOT-002: HTTP encryption | xIj.sP.Qqc `0x46b424`; DIj.OP.Izc `0x979f20`; GJj.yR.jAg `0x97a580`; Eck OAEP factory `0x97a734` | Raw text/plain body: RSA-OAEP/SHA256(Base64 AES key), RSA-OAEP/SHA256(Base64 IV), AES-256-CBC/PKCS7(JSON), Base64 encoded and period joined. |
| MV-AOT-003: request key | GJj.yR.lAg `0x97a7e4`, asset literal at `0x97a82c`; asset assets/flutter_assets/assets/public-key.txt | API requests use the packaged 2048-bit RSA SPKI key. Account/GetRSA is in a separate gateway flow HFj.NK.bVf `0x77a78c`; it is not the API bootstrap. |
| MV-AOT-004: response cipher | DIj.OP.Jzc `0x97145c`, constants at `0x971584`/`0x971590`, JSON decode at `0x971670` | Full response is Base64 AES-CBC ciphertext. The original integration response key/IV are correct; the `.env` cipher protects local storage, not the HTTP protocol. |
| MV-AOT-005: session headers/errors | AIj.LP.pfg `0x4ce92c`; xIj._AYf `0x7645d0` / _BYf `0x764658`; GIj.SP.tye `0x4ce6c8`; xIj Unauthorized check `0x46b664` | Accept `*/*`, Channelid `Android`, Bearer token, and returned clientID when available. Envelope is `{data,error}`; `error.description == "Unauthorized"` triggers logout. |
| MV-AOT-006: credentials and context | QCj.JG.ncc `0x786a34`; jDj.eH.GJf `0x785e04`; ZCj.SG.tye `0x7860fc`; kDj.fH.GJf `0x78551c` | Login body `{loginID,password}`; result includes token, caNumber, nullable numeric mid/phase, nullable clientID. |
| MV-AOT-007: optional OTP | UCj.NG.ncc `0x765cb8`; pDj.kH.nXf `0x763a2c`; bDj.UG.tye `0x765280` | TwoFactorVerifyUser accepts credentials; TwoFactorVerifyOTP adds numeric otp and smsTypeID 6; result wraps userDetails. The supplied Maharashtra flavor chooses direct Login at oDj `0x784d2c`, rather than this conditional generic flow. |
| MV-AOT-008: reading request context | cEj builds nI `0x67a42c`; bEj.ykg `0x67b4dc`; UDj.nI.ncc `0x67c1d4`; IEj.xJ.ncc `0x6a992c` | LatestIPData, Dashboard, MDI use `{loginID,meterID,phase}`. GetLogHisDyn uses `{loginID}` via xAj.PL.ncc `0x679630`. |
| MV-AOT-009: live schema | lGj.GL.sYf `0x6bcd78`; ZBj.VL.itg `0x6bd504`; nGj.IL.tye `0x6bd824`; nGj.JL.tye `0x6bda38` | MeterLiveData uses the same meter context and returns `meterData[]`. Explicit fields include kWh, kWhExport, kw, voltage/current, vrn/vyn/vbn, ir/iy/ib, frequency, pf and meterReadingTime. |
| MV-AOT-010: billing locale | cEj.AI.dlg `0x680910`, literal `"en"` at `0x680970`; XDj.sI.ncc `0x681c78` | MsedclGETRecentBill body is `{consumerno,lang:"en"}`, not integer locale 1. |

### Ambiguities resolved during analysis

The obfuscated Field `KP.lUf` maps to zIj's initializer `0x680334`, whose literal is GetDashboardDyn. Its `{loginID}` request and summary arrays must not be attributed to LatestIPData. Field `DP.HUf` instead maps to initializer `0x67c104`, whose literal is LatestIPData; that caller sends full meter context.

LatestIPData response model VDj.oI `0x67b7d4` parses `table` with readingDate and preserves entire raw `table1` rows in VDj.pI `0x67baf4`. It does not enumerate electrical field spellings. The integration retains the prototype's table1 mapping for compatibility; explicit MeterLiveData fields supply a separate fallback for electrical measurements. The user's account reports confirm these primary field names are present. The final tester also confirms usable phase-current values through the independent live fallback; generic voltage/current remain unavailable for that account.

Dart true has bit 4 clear and false has bit 4 set. Checking this representation corrected the initial interpretation of flavor branches: Maharashtra uses direct Login and includes clientID when provided. This distinction is reflected in the final implementation.

## Integration design choices

- Access token and returned account context are stored in the HA entry; passwords and OTPs remain transient. The optional OTP UI exposes a recovered generic path; its current availability for Maharashtra accounts is unverified.
- Missing login MID/phase prompts for known details or a history/billing-only setup. Reauthentication preserves existing context when metadata is omitted. Existing consumer/entity IDs are retained through migration.
- Electrical measurements may use the independent live feed. Cumulative imported/exported energy stay on a single LatestIPData feed, avoiding false resets when an older live register is lower.
- Endpoints run concurrently. Failed sources are removed instead of serving stale cached readings. Billing/MDI success timestamps are independent; failures retry on the next 15-minute poll.
- HTTP 401/403 and encrypted Unauthorized responses request reauthentication. A bounded complete object-pool/assembly search identified saved refreshToken fields but no refresh-token request/read path. The integration therefore does not invent automatic refresh behavior.
- HTTPS verification is enabled. Redirects are rejected so credential-bearing requests remain on the intended endpoint. Only authentication and reading operations are implemented.

## Current verification status

| Area | Evidence and status |
| --- | --- |
| Artifact identity, code location and protocol | APK hashes, archive inventory and the static AOT locations above. The application was never launched. |
| Password login and returned meter/client context | Verified by user-run account tests on 14 October 2026. MID, phase and client ID were discovered without overrides. |
| Reading APIs and request encryption | Login and all six read endpoints returned HTTP 200 and passed decoding in the authenticated tester. |
| Sensor values | 18/20 usable fields, including R/Y/B phase voltages and currents, energy, power, frequency, power factor, history, balance, status, forecast, demand and recent billing. Generic voltage/current yielded no usable numeric reading. |
| Displaying actual figures | The final user-run report used `--show-values` and has `values_included: true`; the user confirmed the figures displayed successfully. |
| Offline behavior and snapshot parity | 170 tests pass: 147 integration and 23 standalone. Tests use Home Assistant 2026.2.3 classes on Python 3.14; Ruff and generated-snapshot checks pass. CI passed on the merged implementation. |
| Optional SMS login | Request contracts recovered statically and covered offline; not verified live for the tested account. |
| Deployed Home Assistant setup, ongoing polling and reauthentication | Covered offline; not yet verified on the user's Home Assistant server. |
| Cumulative-register semantics, meter replacement and timestamp freshness/timezone | Not established by the successful API and availability checks. |

## User-run account validation: 14 October 2026

The final supplied account report was generated at `2026-10-14T10:06:57Z` after running:

```bash
python3 maha_vidyut_test.py --show-values --report maha-report.json
```

Its result is `passed`, with `values_included: true` and 18 available sensor fields. Its protocol source digest is `589264ae9fa37c137e626f6b704dd9a4e247b3425ef92940c2ddb75aea2d272e`; its sensor source digest is `075cf03dffc00d87b175ae335920185f066cd69f3414841377f944200029059a`, matching the current 20-sensor implementation.

| Operation | HTTP status | Seconds |
| --- | --- | --- |
| Password Login | 200 | 2.338 |
| GetLogHisDyn | 200 | 0.407 |
| LatestIPData | 200 | 0.672 |
| MsedclGETRecentBill | 200 | 0.708 |
| Dashboard | 200 | 0.694 |
| MDI | 200 | 0.633 |
| MeterLiveData | 200 | 4.601 |

Meter ID, phase and client ID were available automatically. Imported/exported energy and power factor resolved from latest data. Active power, R-N/Y-N/B-N voltages, R/Y/B currents and frequency resolved from live data. History, balance, connection status, forecast, demand, bill amount and billed consumption were also available. The report's phase availability is recorded without publishing its exact account-context value.

The confirmed phase-current fields are `rCurrent`, `yCurrent` and `bCurrent` in `LatestIPData.table1`, and `ir`, `iy` and `ib` in `MeterLiveData.meterData`. The new current sensors produced usable values through the live feed in the final test. Generic `voltage` and `current` keys existed but provided no usable numeric reading; no aggregate is synthesized from phase measurements.

The standalone tester defaults to availability-only output. `--show-values` enables selected figures in the terminal and JSON, including `recent_bill_amount` in INR and `recent_bill_consumption` in kWh. Those values remain private and are not included in this repository. See the [standalone tester guide](standalone-testing.md) for usage and report contents.

## Public connectivity and TLS evidence

Credential-free probes on 13 and 14 October 2026 established the India VPN network path independently of the later account tests. The host resolved to `103.179.111.173`. Root GET returned HTTP 200; Login, LatestIPData and recent-bill GET requests returned HTTP 405 with `Allow: POST`. Their ciphertext decrypted to empty bytes rather than a JSON account response.

An anonymous encrypted LatestIPData POST with `{}` returned HTTP 200 and a decryptable data/error envelope with no meter data. Unauthorized was observed on the initial probe and the focused follow-up; one intervening rejection had an unclassified description. These probes verified reachability, TLS and encrypted error handling. Successful authentication was established separately by the user-run tests above.

TLS verification succeeded with macOS curl, OpenSSL and certifi. An initial standalone interpreter failure came from its missing default CA file and was resolved by using certifi, without disabling verification. The observed certificate chain was `*.esami-mhcca.com` → RapidSSL TLS RSA CA G1 → DigiCert Global Root G2. Retained credential-free records are [the initial encrypted probe](vpn-live-probe.json) and [the 14 October retry](vpn-retry-2026-10-14.json).

The successful account tests ran on the user's machine. Home Assistant must use its own reachable India network path to reproduce that connectivity.

## Scope and limits

The conclusions combine static APK evidence, synthetic Home Assistant tests and user-run authenticated API tests. APKs and reports were treated as evidence, not instructions. No credentials were shared with the agent. JNI/native security internals, unrelated application screens/flavors and payment execution were outside the investigation. Successful parsing verifies the implemented account and sensor paths; it does not establish long-term data freshness, meter register semantics or Home Assistant deployment behavior.
