"""Constants for the ZTE Kids integration.

aiohttp, cryptography, and voluptuous already ship with Home Assistant, so
manifest.json keeps requirements empty. These client keys are from the app
binary; they are not account secrets and the user does not enter them.
"""

DOMAIN = "zte_kids"

BASE_URL = "https://care-api.nubia.com/"

# Public client credentials from the international build (eb.b when both region flags are false).
APP_KEY = "U7yJRy5eO0DKTlNVrnx4z5ICm5y16a4S"
APP_SECRET = "fR1gX2AEiYxflz8sVsLFzfwTOfk8NzBu"
# AES-GCM key the Android app uses before it sends the password.
PASSWORD_KEY = b"YNSSFWTeip5M2hSzmpoW4dXr0rWTc0Wr"

# Stored account id. Older entries used "phone"; reauth still reads that key.
CONF_EMAIL = "email"
CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_CODE = "code"
CONF_ACCESS_TOKEN = "accesstoken"
CONF_OPENID = "openid"
CONF_USER_NAME = "user_name"
CONF_DEVICES = "devices"

ATTR_IMEI = "imei"
ATTR_NAME = "name"

# request_location can wake the watch, so refresh_location waits at least this
# long between calls for the same IMEI. History polling does not use this limit.
MIN_REFRESH_SECONDS = 60
# How often stored location history is read. That call does not wake the watch.
HISTORY_UPDATE_SECONDS = 300

PLATFORMS = ["binary_sensor", "button", "device_tracker", "select", "sensor", "switch"]

# api/device/save/systemconfig type values used by the parent app.
CONFIG_LOCATION_MODE = 1
CONFIG_FIND_WATCH = 4
CONFIG_DO_NOT_DISTURB = 6
CONFIG_SPORTS = 17
SERVICE_REFRESH_LOCATION = "refresh_location"
