"""Constants for AESL Smart Meter (unofficial)."""

from datetime import timedelta

DOMAIN = "aesl_smart_meter"
NAME = "AESL Smart Meter"
BASE_URL = "https://cportal.esami-mhcca.com"
ACCOUNT_SERVICE = "SmartMeterMHAccountAPI"
DASHBOARD_SERVICE = "SmartMeterMHDashboardAPI"
PAYMENT_SERVICE = "SmartMeterMHPaymentAPI"
CONF_TOKEN = "access_token"
CONF_CLIENT_ID = "client_id"
CONF_USE_OTP = "use_otp"
CONF_LOGIN_ID = "login_id"
CONF_METER_ID = "meter_id"
CONF_PHASE = "phase"
SCAN_INTERVAL = timedelta(minutes=15)

# Fixed RESPONSE decryption key/IV compiled into the portal's CryptoHttpClient.
# These are protocol constants, NOT a user access token or user's AES request key.
RESPONSE_KEY_B64 = "KwbwSVGl080Z6GEmUtu0Yb1Bh6Lix5PLSm+rxikNeJ4="
RESPONSE_IV_B64 = "4AEItsSgM6pVBM+t+54hnw=="

# Public request-encryption key shipped in the Android APK, not a login secret.
REQUEST_PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsgIeBssM68nQVPVOXtHG\nqCJHIKCa7yq/85o/yZm2OMRS6iDiHntqbnXMzNrqubcuM0aDFNZXez1qK4s8DsUo\n2sAo2tdK0csTtEoowSHuIyXJxSpHI3vJ0xhSo16LIOJ/hnKhxj5N1T1hXB0rEFJU\nqUtmogtNJ+k0UyHs6nR7HBmzayxx9hqRWUGh6WSvW+UPoLg9O2vnYW42IqC7vokb\nIehzQU2k5Uhri9T4K0q8YqLVsEtrwwyqkiODLvMakZ1mcruSURVIjhHubLiTK6Fm\n+KQjUKhT5Olldt9n3jp7xu7JZeKLArG4zUvF0Jut0lY6tTefNfxEBhWpYshgsgu4\nwQIDAQAB\n-----END PUBLIC KEY-----"
