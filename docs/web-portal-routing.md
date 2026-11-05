# Backup portal routing verification

## Observed on 5 November 2026

The login page at `https://cportal.aeslami-mh.com/` loads as a Blazor WebAssembly application. The integration's original mobile request layout is not interchangeable with this website gateway.

| Request | Observed response |
| --- | --- |
| Primary `/SmartMeterMHDashboardAPI/api/Dashboard/LatestIPData`, `Channelid: Android` | HTTP 502 during the investigation |
| Backup with the same mobile path and header | HTTP 500 |
| Backup `/api/Dashboard/LatestIPData`, no `Channelid` header | HTTP 200; encrypted response decrypts to an Unauthorized envelope |

The successful request sent an encrypted empty object, with no account identifier, password, token or selected consumer. TLS verification remained enabled and redirects were disabled. An anonymous Unauthorized response verifies reachability and response compatibility; it does not verify account sign-in, meter readings or session recovery.

The corrected standalone tester also passed an end-to-end anonymous failover check: the primary returned HTTP 502, then the backup gateway returned HTTP 200 with a decoded Unauthorized envelope. See the [sanitized probe report](web-api-probe-2026-11-05.json).

## Public client evidence

The browser loaded [ADL.SmartMeter.Client.wasm](https://cportal.aeslami-mh.com/_framework/ADL.SmartMeter.Client.wasm), SHA-256 `85fd5fa05e37f34af0338cee56288ba37d034d0545b9cedf3961c5d6abc336b1`. Static string observations include `api/`, the Account/Dashboard route names, and the response cipher/public request key already used by the integration. Strings alone do not establish execution or every request contract; the live anonymous probe independently verifies the corrected route and cipher compatibility.

The artifact uses the [Webcil container format](https://github.com/dotnet/runtime/blob/main/docs/design/mono/webcil.md). A synthetic PE carrier retaining the CLI section bytes and RVAs was used only for static inspection, never executed. Its SHA-256 is `74363809f120d4ad0f704e1c4c1ba0b3bcab74afadf45151fba49d915e3ac811`.

REA identity evidence `ev_027b3009be86aba9f3519abbfb9fb962a14dc4cfddb81006c6c67f09c3e2ded0` identifies managed CIL and complete metadata identity. Member inspection evidence `ev_c102e498bd0187c68e841b881c48035d604357a8739fb1582d6580d3b1aafa4c` is unavailable because the metadata representation exceeded its 64 MiB resource budget. No C# decompilation or complete member/call reconstruction is claimed.

## Integration change

Version 0.2.5 selects the path/header profile by host: the primary retains its mobile service prefixes and Android channel; the backup uses `/api/` without that channel header. Request encryption, authentication/session headers, TLS verification and the bounded failover rules are retained. Account sign-in through the corrected gateway still needs verification on the Home Assistant deployment.
