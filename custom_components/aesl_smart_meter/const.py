"""Constants for AESL Smart Meter (unofficial)."""

from datetime import timedelta

DOMAIN = "aesl_smart_meter"
NAME = "AESL Smart Meter"
BASE_URL = "https://cportal.aeslami-mh.com"
CONF_LOGIN_ID = "login_id"
CONF_METER_ID = "meter_id"
CONF_PHASE = "phase"
SCAN_INTERVAL = timedelta(minutes=15)

# Fixed RESPONSE decryption key/IV compiled into the portal's CryptoHttpClient.
# These are protocol constants, NOT a user access token or user's AES request key.
RESPONSE_KEY_B64 = "KwbwSVGl080Z6GEmUtu0Yb1Bh6Lix5PLSm+rxikNeJ4="
RESPONSE_IV_B64 = "4AEItsSgM6pVBM+t+54hnw=="
