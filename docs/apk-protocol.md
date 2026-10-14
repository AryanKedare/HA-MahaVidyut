# APK protocol evidence and verification

This report supports the version 0.2 integration changes. APK observations are static: the Android application was never launched. The agent did not receive or use real account credentials; the user subsequently ran the standalone tester locally and supplied its redacted diagnostic report. Integration tests use synthetic responses. The user's repository was analyzed as source; packaged files were treated as evidence, not instructions.

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

LatestIPData response model VDj.oI `0x67b7d4` parses `table` with readingDate and preserves entire raw `table1` rows in VDj.pI `0x67baf4`. It does not enumerate electrical field spellings. The integration retains the prototype's table1 mapping for compatibility; explicit MeterLiveData fields supply a separate fallback for electrical measurements. The user's subsequent redacted report confirms these primary field names are present, including the additional phase-current fields documented below. Presence does not imply a usable numeric reading.

Dart true has bit 4 clear and false has bit 4 set. Checking this representation corrected the initial interpretation of flavor branches: Maharashtra uses direct Login and includes clientID when provided. This distinction is reflected in the final implementation.

## Integration design choices

- Access token and returned account context are stored in the HA entry; passwords and OTPs remain transient. The optional OTP UI exposes a recovered generic path; its current availability for Maharashtra accounts is unverified.
- Missing login MID/phase prompts for known details or a history/billing-only setup. Reauthentication preserves existing context when metadata is omitted. Existing consumer/entity IDs are retained through migration.
- Electrical measurements may use the independent live feed. Cumulative imported/exported energy stay on a single LatestIPData feed, avoiding false resets when an older live register is lower.
- Endpoints run concurrently. Failed sources are removed instead of serving stale cached readings. Billing/MDI success timestamps are independent; failures retry on the next 15-minute poll.
- HTTP 401/403 and encrypted Unauthorized responses request reauthentication. A bounded complete object-pool/assembly search identified saved refreshToken fields but no refresh-token request/read path. The integration therefore does not invent automatic refresh behavior.
- HTTPS verification is enabled. Redirects are rejected so credential-bearing requests remain on the intended endpoint. Only authentication and reading operations are implemented.

## Verification and remaining questions

| Question | Status |
| --- | --- |
| Supplied artifact identity and code location | Answered by hashes and archive/code evidence. |
| Host, service prefixes, cipher framing and key source | Answered statically. |
| Password/OTP request contracts and meter context | Answered statically; password login and automatic meter/client context verified by the user-run tester. Optional OTP remains unverified live. |
| Polling, numeric handling, energy-feed behavior, migration and standalone parity | 170 offline tests pass (147 integration and 23 standalone) using Home Assistant 2026.2.3 classes on Python 3.14; Ruff and generated-snapshot checks pass. |
| Public service reachability, TLS and encrypted error envelope | Verified through an India VPN on 13 October 2026 and retried on 14 October: root HTTP 200; API routes GET 405 with Allow: POST; encrypted anonymous LatestIPData POST HTTP 200 with data=null; follow-up rejection description Unauthorized. |
| Successful account authentication and request-key acceptance after authentication | Verified by the user-run standalone test on 14 October 2026: Login and all six read endpoints passed, each HTTP 200. Credentials were not shared with the agent. |
| Real response schema and sensor availability | The redacted account report confirms 15 of 17 original sensor paths yielded usable values. Generic voltage/current were unavailable; phase voltages were available. R/Y/B current field names are confirmed, but the three added current sensors await an updated live test. |
| Deployed Home Assistant setup, polling and reauthentication | Offline coverage passes; not yet verified on the user's Home Assistant deployment. |
| Meter register semantics, timezone/freshness and meter replacements | Partially answered by named models; real-account validation remains necessary. |

No Android device/emulator or target execution was used. JNI/native security code, payment execution, unrelated screens and all utilities/flavors were outside the integration investigation. The live account conclusion is based on the user's tester report, independently of the synthetic offline suite. Register semantics and freshness remain unverified because the report omits actual values and timestamps.

## Live VPN follow-up: 13 October 2026

After the user enabled an India VPN, the mobile host resolved to `103.179.111.173` and responded without the earlier connection timeout. TLS verification succeeded with macOS curl, OpenSSL, and the certifi CA bundle used by Home Assistant. The initial standalone Python SSL failure came from that interpreter's missing default CA file; no certificate-verification bypass or integration SSL change was needed. The certificate chain presented a wildcard `*.esami-mhcca.com` leaf issued by RapidSSL TLS RSA CA G1 under DigiCert Global Root G2.

Read-only GET requests to Login, LatestIPData and MsedclGETRecentBill returned HTTP 405 with `Allow: POST`. Their ciphertext decrypted to empty bytes using the integration's fixed response key/IV; empty bytes are not a JSON account response.

One anonymous POST to LatestIPData sent the packaged-RSA/AES encrypted representation of `{}`, with no Authorization header and no consumer number. It returned HTTP 200, `Content-Type: text/plain`, and a 108-byte ciphertext. The existing response cipher decrypted it into a JSON object with `data: null` and `error.description: "Unauthorized"`. This validates current connectivity, TLS, encrypted error decoding and the authentication-error contract. It does not establish successful login, meter values, or whether request decryption happens before the unauthenticated rejection.

The India VPN must cover the Home Assistant deployment's traffic for that deployment to use the same tested network path. The successful probe originated on the user's machine, not on an unspecified separate Home Assistant server.

### Retry on 14 October 2026

With network access granted for the new turn, the same TLS-verified probes completed in 0.65–0.75 seconds: root HTTP 200, Login and recent-bill GET HTTP 405 with Allow: POST, and encrypted anonymous LatestIPData POST HTTP 200. The response again decrypted into the expected data/error envelope and contained no meter data. One rejection was recorded as an unclassified error description; an immediate focused follow-up returned `{"description":"Unauthorized","status":null}`. No account credentials or consumer identifier were sent. This retry confirms current reachability and encrypted error handling, not successful account login.

## User-run account validation: 14 October 2026

The user ran `python3 maha_vidyut_test.py --report maha-report.json` locally through the India VPN. The report was generated at `2026-10-14T09:33:52Z`, with `values_included: false` and result `passed`. Its protocol source digest is `589264ae9fa37c137e626f6b704dd9a4e247b3425ef92940c2ddb75aea2d272e`; its sensor source digest is `beb73b3286d399ad0d0c10ff8b40e1f412dc907e8bf1bfc2332c2313bf394642`, identifying the original 17-sensor tester before the phase-current addition. This section records selected results rather than publishing the account report.

| Operation | HTTP status | Seconds |
| --- | --- | --- |
| Password Login | 200 | 2.398 |
| GetLogHisDyn | 200 | 0.510 |
| LatestIPData | 200 | 0.773 |
| MsedclGETRecentBill | 200 | 0.791 |
| Dashboard | 200 | 0.804 |
| MDI | 200 | 0.878 |
| MeterLiveData | 200 | 5.320 |

Meter ID, phase and client ID were available automatically; no context overrides were used. Imported/exported energy and power factor resolved from latest data. Active power, phase voltages and frequency resolved from live data. History, balance, connection status, forecast, demand and billing sensor checks also passed. Generic voltage and current field names were present in both responses but yielded no usable numeric value. The available phase voltages suggest a three-phase meter; the redacted report does not include the exact phase value.

Latest data explicitly included `rCurrent`, `yCurrent` and `bCurrent`; live data included `ir`, `iy` and `ib`. These confirmed field names support three additional phase-current sensors with independent live fallbacks. Their numeric availability was not checked by the original tester. The updated generated tester includes them, with synthetic regressions for distinct phase values, zero readings, invalid primary values and missing generic readings. It does not synthesize an aggregate voltage or current.
