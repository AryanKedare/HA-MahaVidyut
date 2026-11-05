# MahaVidyut for Home Assistant

[![Tests](https://github.com/AryanKedare/HA-MahaVidyut/actions/workflows/tests.yml/badge.svg)](https://github.com/AryanKedare/HA-MahaVidyut/actions/workflows/tests.yml)
[![GitHub issues](https://img.shields.io/github/issues/AryanKedare/HA-MahaVidyut.svg)](https://github.com/AryanKedare/HA-MahaVidyut/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="custom_components/aesl_smart_meter/brand/icon.png" width="280" alt="Mahavitaran / MSEDCL logo">
</p>

**by MSEDCL Unofficial Cloud Integration**

An unofficial Home Assistant integration for MahaVidyut smart meters. View electricity readings, consumption, account balance and recent billing from your MSEDCL account.

> This community project is not affiliated with or endorsed by MSEDCL / Mahavitaran or the MahaVidyut service.

## Supported sensors

| Readings | Sensors |
| --- | --- |
| Energy | Imported and exported energy |
| Power | Active power |
| Voltage | Voltage and R/Y/B phase voltages |
| Current | Current and R/Y/B phase currents |
| Frequency and power factor | Frequency and power factor |
| Consumption | Energy consumed today and current month forecast |
| Account | Current balance and connection status |
| Demand | Assigned maximum demand |
| Billing | Recent bill amount and billed consumption |

Sensor availability depends on your meter and account.

## Installation

### Installer

Run in a terminal with access to your Home Assistant configuration directory:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/AryanKedare/HA-MahaVidyut/main/install.sh)
```

The default configuration directory is `/config`. For a different location:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/AryanKedare/HA-MahaVidyut/main/install.sh) /path/to/homeassistant/config
```

For a downloaded installation bundle or source checkout, run `bash install.sh /config` from its directory.

### Manual installation

Copy `custom_components/aesl_smart_meter` from this repository into:

```text
<home-assistant-config>/custom_components/aesl_smart_meter/
```

Restart Home Assistant after installing or updating. When upgrading, keep your existing integration entry.

## Configuration

1. Open **Settings → Devices & services → Add integration**.
2. Search for **MahaVidyut**.
3. Enter your MahaVidyut consumer/CA number and app password.
4. Leave **Use SMS verification** off for normal password sign-in and complete setup.

Optionally enable **Save password for automatic sign-in** during setup or through **Reconfigure**.

## Cloud access and privacy

Home Assistant needs internet access to the MahaVidyut [primary](https://cportal.esami-mhcca.com/) and [backup](https://cportal.aeslami-mh.com/) servers. Access tokens are stored locally. Your password is saved only when automatic sign-in is enabled; it is stored in the local configuration and may be included in backups.

## Troubleshooting

Check that the MahaVidyut app works for the same account, then restart Home Assistant and sign in again if prompted.

[Report an issue](https://github.com/AryanKedare/HA-MahaVidyut/issues) with your Home Assistant version, integration version and relevant logs with personal information removed.

## Documentation

- [Standalone tester](docs/standalone-testing.md)
- [Session recovery](docs/session-recovery.md)
- [Development and release guide](docs/releasing.md)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) — Copyright 2026 Aryan Kedare. Mahavitaran / MSEDCL logo and trademark rights remain with their respective owners.
