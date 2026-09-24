"""Constants for the ZTE Kids integration."""

DOMAIN = "zte_kids"

BASE_URL = "https://care-api.nubia.com/"

# Client keys from the international build (eb.b when both region flags are false).
APP_KEY = "U7yJRy5eO0DKTlNVrnx4z5ICm5y16a4S"
APP_SECRET = "fR1gX2AEiYxflz8sVsLFzfwTOfk8NzBu"
PASSWORD_KEY = b"YNSSFWTeip5M2hSzmpoW4dXr0rWTc0Wr"

CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_CODE = "code"
CONF_ACCESS_TOKEN = "accesstoken"
CONF_OPENID = "openid"
CONF_USER_NAME = "user_name"
CONF_DEVICES = "devices"

ATTR_IMEI = "imei"
ATTR_NAME = "name"

# Asking the watch for a fix is rate limited. History polling is separate.
MIN_REFRESH_SECONDS = 60
HISTORY_UPDATE_SECONDS = 300

PLATFORMS = ["device_tracker"]
SERVICE_REFRESH_LOCATION = "refresh_location"
