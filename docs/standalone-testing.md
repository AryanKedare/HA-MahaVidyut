# MahaVidyut standalone tester

Test password login, electricity readings and recent billing without installing Home Assistant. The single Python file embeds the integration's API client and sensor paths and checks all six reading APIs once after login.

## Setup

Use Python 3.10 or newer and an India network path on the machine running the tester. An India VPN resolved the connection timeouts in the verified account tests.

Extract the tester bundle, or place `maha_vidyut_test.py` and `requirements-standalone.txt` from the repository's `tools` directory together. From that directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-standalone.txt
```

The requirements pin aiohttp 3.13.3, cryptography 46.0.5 and certifi 2026.7.22. HTTPS certificate verification remains enabled.

## Display readings and bill amounts

```bash
python maha_vidyut_test.py --show-values --report maha-report.json
```

Enter the consumer/CA number and MahaVidyut password at the private terminal prompts. The script discovers meter ID, phase and client ID from login when returned by the service.

`--show-values` prints selected sensor readings and stores them under each metric's `value` in the JSON report. Units are stored under `unit`. Billing and balance are separate fields:

| Output field | Meaning | Unit |
| --- | --- | --- |
| `recent_bill_amount` | The recent bill's `billAmount` | INR |
| `recent_bill_consumption` | Consumption recorded in the recent bill | kWh |
| `current_balance` | The dashboard's current account balance | INR |

The tester supports 20 sensor fields. User-run tests on 14 October 2026 passed login and all six reading APIs, with **18/20 fields available**, including the three phase voltages, three phase currents and recent billing. The generic `voltage` and `current` fields had no usable numeric reading for that account. Use the phase readings when the service supplies them.

## Create a report without reading values

```bash
python maha_vidyut_test.py --report maha-report.json
```

Without `--show-values`, the terminal prints `available` or `unavailable` for each metric. The report has `values_included: false` and omits each metric's `value`. It includes request paths, HTTP status/timing, known response field names, account-context availability, metric units/sources and error categories.

Both modes omit passwords, SMS codes, tokens, account identifiers and raw responses. A report created with `--show-values` contains actual meter and billing figures; use the default mode when sharing diagnostics without those figures.

## Options

| Option | Purpose |
| --- | --- |
| `--show-values` | Display selected readings and include their values in the report. |
| `--report <path>` | Save the diagnostic JSON report. |
| `--probe-only` | Check TLS and encrypted anonymous rejection without credentials; account access is not tested. |
| `--consumer <CA>` | Supply the consumer number instead of using the private prompt. |
| `--meter-id <MID> --phase <1\|2\|3>` | Override meter context when login omits it or returns incorrect details. MID must be positive. |
| `--otp` | Request and verify the optional SMS flow. It can send a verification SMS and has not been verified live for the tested Maharashtra account. |
| `--help` | Show command usage. |

`--probe-only` and `--otp` are mutually exclusive. For noninteractive password-login runs, set `MAHA_VIDYUT_CONSUMER` and `MAHA_VIDYUT_PASSWORD` in your environment. Otherwise the tester needs an interactive terminal for private credential entry. Passwords are not accepted as command-line arguments.

A connectivity-only check:

```bash
python maha_vidyut_test.py --probe-only --report probe-report.json
```

## Results and exit codes

| Code | Result |
| --- | --- |
| 0 | Passed checks, with at least one usable sensor field in an account test. |
| 1 | Authentication failure or complete check failure. |
| 2 | Partial results, warnings, skipped checks or no usable sensor fields. |
| 130 | Cancelled by the user. |

A missing optional metric does not fail otherwise successful API checks. If meter context is absent, the tester checks history and billing and skips the four meter-specific APIs unless you supply known MID/phase overrides.

The tester makes one login followed by six read requests when meter context is available. It does not poll continuously. A passing standalone run verifies the API and sensor paths for that account and network; Home Assistant installation, ongoing polling and reauthentication must be checked on the deployment itself.
