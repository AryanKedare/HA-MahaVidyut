# Repeated authentication repairs

When password sign-in restores readings but the same repair soon returns, the service is rejecting a previously accepted session. The exact token lifetime and the reason for rejection cannot be determined from the repair notification alone. Version 0.2.0 stores only the session token and immediately requests manual sign-in when any reading endpoint rejects it.

Version 0.2.1 provides optional recovery using the existing password Login API. No refresh-token endpoint is assumed.

## Enable recovery for an existing meter

1. Extract the upgraded installation ZIP, run `bash install.sh /config` from that directory (use your configuration path if different), and restart Home Assistant. The installer backs up any existing integration folder before replacing it. You can also copy `custom_components/aesl_smart_meter` manually.
2. Open **Settings → Devices & services → AESL Smart Meter (Unofficial)**.
3. Complete the existing authentication repair, or open the entry's menu and select **Reconfigure**.
4. Enter the same consumer number and password. Enable **Save password for automatic sign-in** and leave **Use SMS verification** off.

Use the existing entry to retain its entities and history. Saving the password is optional and is off by default. Home Assistant stores it in the local config entry without separate encryption, and it may be included in backups. To stop saving it, use Reconfigure, enter the password once to validate sign-in, and clear the option. That removes it from the active entry; old backups retain their contents. Passwords and tokens are not written to integration logs. SMS codes are never saved, and automatic sign-in cannot be combined with SMS verification.

## Recovery behavior

- Normal polling remains every 15 minutes.
- On HTTP 401/403 or an encrypted Unauthorized response, the coordinator waits for the current request batch to finish, signs in once, and retries readings once with the new session. Concurrent failed endpoints share that login attempt.
- The replacement token and client/meter context are saved for future polling and restart. Missing meter details preserve the known MID and phase. All reading caches are refreshed after recovery.
- An invalid password or a rejected replacement session opens manual reauthentication. A connection or protocol failure during login makes the refresh unavailable and retries at the next normal poll.
- Disabling password storage retains manual reauthentication behavior.

## Verification and remaining limits

205 offline tests pass on Python 3.14 with Home Assistant 2026.2.3. They cover HTTP 401/403 and encrypted Unauthorized recovery through the real API client and Home Assistant first-refresh runtime, a fresh client using the persisted token, concurrent failures sharing one login, bounded retries, invalid credentials, transient errors, cancellation, meter context, password opt-in/removal, and SMS restrictions. Installer tests cover local and simulated downloaded installs, backups, rollback after replacement failure, missing files, symbolic-link destinations, and configuration paths containing spaces. Shell syntax, Ruff and generated standalone-tester parity checks pass.

Responses and credentials in these tests are synthetic. No real account credentials were provided to the agent, and the deployed Home Assistant instance was not accessed. These tests do not establish the live session lifetime, the server's reason for invalidation, or that automatic re-login will work for every account. If a replacement session is immediately rejected, collect integration debug logs to identify the failing source and investigate the live account behavior.
