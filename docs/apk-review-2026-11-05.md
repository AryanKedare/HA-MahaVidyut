# APK review and Live Data availability — 5 November 2026

The supplied APKs are byte-for-byte identical to those behind the earlier [protocol analysis](https://github.com/AryanKedare/HA-MahaVidyut/blob/main/docs/apk-protocol.md). The latest account report and portal screenshot point to an unavailable provider Live Data service. They do not establish a new request contract or a client change that could restore those readings.

## Artifact verification

The APKs were hashed again, and their members were inventoried with REA CLI 6.4.0. The public-key asset was compared with the integration's request key and matches after PEM normalization.

| Artifact | SHA-256 |
| --- | --- |
| base.apk | `471db50786117c8205e8c6ebb8d1283aa67495215b6d99ff50b61e45be042020` |
| split_config.arm64_v8a.apk | `fb06969b7a84a18221e331ecc7bfc4ccb264e989dab114db31531da7b0b80484` |
| lib/arm64-v8a/libapp.so | `ca89124edfe28b9e76d143dd58c612529a6f5f6da23e9691656f5398c007897c` |
| Request public-key asset | `03f86d866c07f196501413ff1cdbb4e6e3b492c662ab3b49928dcb09846cbba2` |

Fresh REA inventory evidence IDs:

- Base APK: `ev_63e69f959604647af82381c4ef2a0ad32e08e7773f8746566c65d2ce203513fd`; inventory substep `ev_19cce0719a34a115c164bea259b6db7af615a97f41e7c2905df48c9a779997bd`.
- ARM64 split: `ev_a70f58f7538586f71590bbcc0934a3b3db1c6fd5f29944e715b533941a1b1ad9`; inventory substep `ev_47ea367c6edb7900c2b7bf9514cfa852197d9349b3ea0cdaa52d13f6438fc366`.

The Android/JADX provider was unavailable because its required headless JAR was absent. No new native decompilation was performed. Native code conclusions below reuse the earlier documented analysis of these exact artifacts; the previous collision-safe Blutter dump was not available for reinspection. The application was not launched, and APK contents were treated as evidence rather than instructions.

## Protocol comparison

The previous analysis identifies the mobile host, RSA-OAEP/AES request envelope, response decryption, `{loginID,password}` login body, optional returned `clientID`, and `{loginID,meterID,phase}` reading context. Its `MeterLiveData` caller and model locations are `0x6bcd78`, `0x6bd504`, `0x6bd824` and `0x6bda38` in the matching `libapp.so`.

These contracts agree with the current client. The APK does not establish the backup web gateway's routing; that was independently verified in the [portal investigation](https://github.com/AryanKedare/HA-MahaVidyut/blob/main/docs/web-portal-routing.md). There is no evidence here to change phase values, fabricate a missing client ID, alter the cipher or replace field names.

## Current service evidence

The user-run report at `2026-11-05T12:33:24Z` uses the corrected 0.2.5 client, with protocol source digest `a5b7974d69f3fad3a28c8ca95c7d6fad4569ac915f28512e253247b7842c838c`.

| Check | Observation |
| --- | --- |
| Password login | Passed through the backup gateway; meter ID and phase were returned. |
| History, latest readings, dashboard, maximum demand and recent bill | All five checks passed. |
| Live Data | Backup returned HTTP 500; the primary returned HTTP 200 headers followed by `ClientPayloadError` while reading its body. The old report does not retain its deeper cause. |
| Sensor availability | 10 of 20 fields available. Energy, balance, billing and other summary fields remain usable. Live-dependent electrical measurements are unavailable. |
| Official portal | The supplied Live Data screenshot says: “Due to the technical issue, we are not able to fetch the live data.” |

No account identifiers, tokens, passwords or actual reading values are reproduced here.

Eight credential-free encrypted POST probes also compared the two hosts, `LatestIPData` and `MeterLiveData`, and default versus `identity` encoding negotiation. The primary returned complete HTTP 502 responses in all four cases. The backup returned complete, decryptable HTTP 200 Unauthorized envelopes in all four cases, with no `Content-Encoding`. These probes verify anonymous transport and error handling only; they do not reproduce the authenticated body failure or establish live meter availability. They provide no basis for changing compression settings or installing another decoder.

## Resulting changes and limits

The standalone tester now separates response-header receipt from completed body reads, records sanitized encoding/framing metadata, and retains a bounded chain of exception class names. This lets a future report distinguish truncated bodies from content-decoding failures without publishing exception text or raw responses. Local HTTP-server tests cover complete bodies, truncated bodies and invalid gzip responses.

The integration already handles a Live Data failure independently of successful sources and removes failed readings rather than serving stale measurements. Existing outage regressions cover that behavior. No runtime API or sensor changes are made by this review, and the integration version remains 0.2.5. The provider must restore the missing data before those measurements can become available; recovery has not been verified.
