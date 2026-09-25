"""Client for the ZTE Kids parent API used by the phone app."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import urljoin

# Both are Home Assistant core dependencies, so they stay out of manifest requirements.
import aiohttp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .const import APP_KEY, APP_SECRET, BASE_URL, PASSWORD_KEY

_LOGGER = logging.getLogger(__name__)
_SUCCESS_CODES = {0, 200, "0", "200"}


class ZteKidsError(Exception):
    """API call failed."""


class ZteKidsAuthError(ZteKidsError):
    """Login was rejected."""


class ZteKidsCodeRequired(ZteKidsAuthError):
    """The server wants a verification code before login can finish."""


def encrypt_password(password: str) -> str:
    """Encrypt a password the way the app does: AES-GCM, IV prepended, Base64."""
    aes = AESGCM(PASSWORD_KEY)
    iv = os.urandom(12)
    ciphertext = aes.encrypt(iv, password.encode("utf-8"), None)
    # Android Base64.DEFAULT appends a newline.
    return base64.b64encode(iv + ciphertext).decode("ascii") + "\n"


def mobile_type() -> str:
    """Same shape as Build.BRAND;Build.MODEL;Android;Build.VERSION.RELEASE."""
    return "HomeAssistant;ZTEKids;Android;14"


def captcha_destination_type(account: str) -> str:
    """EMAIL when the account contains @, otherwise MOBILE_PHONE. Same split as the app."""
    return "EMAIL" if "@" in account else "MOBILE_PHONE"


def sign_body(body: dict[str, Any], timestamp: str, nonce: str) -> str:
    """SHA-256 of the sorted key=value pairs, including a trailing ampersand.

    The app's signer always leaves the last "&" in place and appends APP_SECRET
    after it. Dropping that ampersand produces a signature the server rejects.
    """
    pairs = {_stringify(key): _stringify(value) for key, value in body.items() if value is not None}
    pairs["timestamp"] = timestamp
    pairs["nonce"] = nonce
    pairs["appKey"] = APP_KEY
    ordered = "".join(f"{key}={pairs[key]}&" for key in sorted(pairs)) + APP_SECRET
    return hashlib.sha256(ordered.encode("utf-8")).hexdigest()


def path_for_log(url: str) -> str:
    """Path only, so query tokens are not written to the log."""
    return url.split("?", 1)[0]


def _signature_query(body: dict[str, Any]) -> dict[str, str]:
    """Query string the server requires on both signed JSON posts and gateway calls."""
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    return {
        "sign": sign_body(body, timestamp, nonce),
        "timestamp": timestamp,
        "nonce": nonce,
        "appKey": APP_KEY,
    }


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class ZteKidsClient:
    """Signed HTTP client for care-api.nubia.com."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def login(self, account: str, password: str, code: str | None = None) -> dict[str, Any]:
        """Log in the same way as the app: loginName, encrypted password, dypwdFlag N.

        The international app puts the email address in loginName.
        """
        body: dict[str, Any] = {
            "dypwdFlag": "N",
            "jigsawCode": "",
            "kid": "",
            "loginName": account,
            "mobileType": mobile_type(),
            "password": encrypt_password(password),
        }
        if code:
            body["code"] = code
        payload = await self._signed_post("api/account/login", body)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        token = data.get("accesstoken") or data.get("accessToken")
        openid = data.get("openid")
        if not token or not openid:
            _LOGGER.debug("Login response keys: %s", sorted(data) if isinstance(data, dict) else type(data).__name__)
            raise ZteKidsAuthError("Login response did not include a session.")
        _LOGGER.debug("Login succeeded for openid %s", openid)
        return {
            "accesstoken": token,
            "openid": openid,
            "user_name": data.get("userName") or account,
            "token_expire_time": data.get("token_expire_time"),
        }

    async def send_captcha(self, account: str) -> None:
        """Ask the server to send a verification code to this email or phone."""
        await self._signed_post(
            "api/account/sendcaptcha",
            {
                "destination": account,
                "destinationType": captcha_destination_type(account),
                "jigsawCode": "",
                "kid": "",
                "language": "en",
                "verificationCodeType": "login",
            },
        )

    async def list_devices(self, openid: str, access_token: str) -> list[dict[str, str]]:
        """Return watches linked to the parent account.

        The gateway rejects this GET unless openid and accesstoken are both
        query parameters and covered by the same signature as a signed POST.
        """
        fields = {"openid": openid, "accesstoken": access_token}
        url = urljoin(BASE_URL, f"getway/accounts/{openid}/related-device")
        payload = await self._request(
            "GET",
            url,
            params={**fields, **_signature_query(fields)},
        )
        devices: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in _device_lists(payload):
            imei = str(item.get("imei") or "")
            if not imei or imei in seen:
                continue
            seen.add(imei)
            name = item.get("name") or item.get("phone") or imei
            devices.append({"imei": imei, "name": str(name)})
        _LOGGER.debug("Related devices: %s", [(device["imei"], device["name"]) for device in devices])
        return devices

    async def query_location_history(
        self,
        imei: str,
        access_token: str,
        *,
        day: str,
        time_zone: int,
        timezone_str: str,
    ) -> dict[str, Any] | None:
        """Read stored points for one day. This does not wake the watch.

        The history service expects the session in a body field named token.
        Without it the call is signed correctly and still rejected as unauthorized.
        """
        payload = await self._signed_post(
            "api/device/querylocation",
            {
                "day": day,
                "imei": imei,
                "timeZone": time_zone,
                "timezoneStr": timezone_str,
                "token": access_token,
            },
        )
        point = _latest_point(payload)
        _LOGGER.debug("History for %s on %s (%s): %s", imei, day, timezone_str, _point_for_log(point))
        return point

    async def request_location(self, imei: str, openid: str, access_token: str) -> dict[str, Any] | None:
        """Ask the server for the watch's latest fix.

        The app posts openid and accesstoken as form fields and signs that pair.
        A fresh GPS fix is requested from the watch when the server does not
        already have a recent point, so callers must rate limit it.
        """
        fields = {"openid": openid, "accesstoken": access_token}
        url = urljoin(BASE_URL, f"getway/devices/{imei}/location/last")
        payload = await self._request(
            "POST",
            url,
            params=_signature_query(fields),
            data=fields,
        )
        point = _latest_point(payload)
        _LOGGER.debug("Live fix for %s: %s", imei, _point_for_log(point))
        return point

    async def query_device(self, imei: str, openid: str, access_token: str) -> dict[str, Any]:
        """Read device details, including whether the watch is online.

        Same signed query as the related-device list. This does not ask the watch for a new fix.
        """
        fields = {"openid": openid, "accesstoken": access_token}
        url = urljoin(BASE_URL, f"getway/devices/{imei}")
        payload = await self._request("GET", url, params={**fields, **_signature_query(fields)})
        return parse_device(payload)

    async def query_system_config(self, imei: str, access_token: str) -> dict[str, Any]:
        """Read stored watch settings, including battery percent and SOS numbers."""
        payload = await self._signed_post(
            "api/device/query/systemconfig",
            {"deviceId": imei, "token": access_token},
        )
        return parse_system_config(payload)

    async def query_sport(
        self,
        imei: str,
        access_token: str,
        *,
        day: str,
        time_zone: int,
        timezone_str: str,
        period: str,
    ) -> dict[str, Any]:
        """Read stored steps, distance, and calories. period is daily or week."""
        path = "api/sport/query/daily" if period == "daily" else "api/sport/query/week"
        # The sport request has no day field. The server uses timeZone for "today".
        _LOGGER.debug("Sport %s for %s on %s zone %s", period, imei, day, timezone_str)
        payload = await self._signed_post(
            path,
            {
                "deviceId": imei,
                "timeZone": time_zone,
                "timezoneStr": timezone_str,
                "token": access_token,
            },
        )
        return parse_sport(payload)

    async def query_wifi(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read Wi-Fi networks the server has stored for this watch."""
        payload = await self._signed_post("api/device/wifilist", {"imei": imei, "token": access_token})
        return parse_wifi(payload)

    async def query_places(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read places saved on the parent account for this watch."""
        payload = await self._signed_post("api/addr/query", {"imei": imei, "token": access_token})
        return parse_places(payload)

    async def query_safe_zones(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read safe-zone rules stored for this watch."""
        payload = await self._signed_post("api/guardrule/query", {"imei": imei, "token": access_token})
        return parse_safe_zones(payload)

    async def query_reminders(self, imei: str, access_token: str, *, day: str) -> list[dict[str, Any]]:
        """Read schedule reminders for one day."""
        payload = await self._signed_post(
            "api/scheduleReminder/queryByWeek",
            {"dateStr": day, "deviceId": imei, "token": access_token},
        )
        return parse_reminders(payload)

    async def query_contacts(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read contacts stored for this watch."""
        payload = await self._signed_post(
            "api/device/query/contact",
            {"deviceId": imei, "token": access_token},
        )
        return parse_contacts(payload)

    async def query_call_log(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read the first page of call history stored for this watch."""
        payload = await self._signed_post(
            "api/message/calllog/query",
            {"deviceId": imei, "page": 1, "size": 20, "token": access_token},
        )
        return parse_calls(payload)

    async def query_messages(self, imei: str, access_token: str) -> list[dict[str, Any]]:
        """Read the first page of SMS history stored for this watch."""
        payload = await self._signed_post(
            "api/message/sms/query",
            {"deviceId": imei, "page": 1, "size": 20, "token": access_token},
        )
        return parse_messages(payload)

    async def save_system_config(
        self,
        imei: str,
        access_token: str,
        *,
        config_type: int,
        status: int | None = None,
        mode: int | None = None,
    ) -> None:
        """Change one stored watch setting. config_type selects which setting."""
        body: dict[str, Any] = {"deviceId": imei, "token": access_token, "type": config_type}
        if status is not None:
            body["status"] = status
        if mode is not None:
            body["mode"] = mode
        await self._signed_post("api/device/save/systemconfig", body)

    async def _signed_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(BASE_URL, path)
        return await self._request(
            "POST",
            url,
            params=_signature_query(body),
            json_body=body,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        path = path_for_log(url)
        _LOGGER.debug(
            "Request %s %s query=%s body=%s",
            method,
            path,
            sorted(params or {}),
            sorted(json_body or data or {}),
        )
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                text = await response.text()
                if response.status >= 500:
                    _LOGGER.debug("Response %s %s HTTP %s body=%s", method, path, response.status, " ".join(text.split())[:200])
                    raise ZteKidsError(f"ZTE Kids returned HTTP {response.status} for {method} {path}.")
                payload: dict[str, Any]
                try:
                    parsed = await response.json(content_type=None)
                except Exception:
                    parsed = None
                if not isinstance(parsed, dict):
                    snippet = " ".join(text.split())[:200]
                    _LOGGER.debug("Response %s %s HTTP %s non-JSON body=%s", method, path, response.status, snippet)
                    raise ZteKidsError(
                        f"ZTE Kids returned HTTP {response.status} for {method} {path} "
                        f"with a non-JSON body: {snippet or '(empty)'}"
                    )
                payload = parsed
        except aiohttp.ClientError as err:
            _LOGGER.debug("Request %s %s failed: %s", method, path, err)
            raise ZteKidsError(f"Could not reach ZTE Kids at {path}: {err}") from err
        _LOGGER.debug("Response %s %s HTTP %s %s", method, path, response.status, _payload_summary(payload))
        _raise_for_api_error(payload, method=method, path=path)
        return payload


def _payload_summary(payload: dict[str, Any]) -> str:
    """Code, message, and data shape. Values that can hold a session are left out."""
    code = payload.get("code", payload.get("ret"))
    message = payload.get("msg") or payload.get("message") or payload.get("error") or ""
    data = payload.get("data")
    if isinstance(data, dict):
        shape = ",".join(sorted(str(key) for key in data))
    elif isinstance(data, list):
        shape = f"list[{len(data)}]"
    elif data is None:
        shape = "null"
    else:
        shape = type(data).__name__
    return f"code={code} msg={message} data={shape}"


def _point_for_log(point: dict[str, Any] | None) -> str:
    if point is None:
        return "none"
    return f"type={point.get('loc_type')} time={point.get('timestamp')} accuracy={point.get('accuracy')}"


def _raise_for_api_error(payload: dict[str, Any], *, method: str = "", path: str = "") -> None:
    # Success is code/ret 0 or 200. Captcha text means the login needs a second
    # step. 1132/1022 and token wording mean the saved session is dead.
    code = payload.get("code", payload.get("ret"))
    if code is None or code in _SUCCESS_CODES:
        return
    message = str(payload.get("msg") or payload.get("message") or payload.get("error") or code)
    where = f"{method} {path}".strip()
    detail = f"{where}: {message}" if where else message
    lowered = message.lower()
    if any(word in lowered for word in ("captcha", "jigsaw", "验证码")):
        _LOGGER.debug("Verification required code=%s %s", code, detail)
        raise ZteKidsCodeRequired(detail)
    if code in {401, 403, 1132, 1022, "401", "403", "1132", "1022"} or "token" in lowered or "登录" in message:
        _LOGGER.warning("ZTE Kids auth error code=%s %s", code, detail)
        raise ZteKidsAuthError(detail)
    _LOGGER.warning("ZTE Kids API error code=%s %s", code, detail)
    raise ZteKidsError(f"ZTE Kids API error {code} for {detail}")


def _device_lists(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    found: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return found
    for key in ("ownedDevices", "chatGroupDevices", "devices"):
        items = data.get(key)
        if isinstance(items, list):
            found.extend(item for item in items if isinstance(item, dict))
    return found


def _latest_point(payload: Any) -> dict[str, Any] | None:
    points = list(_walk_points(payload))
    if not points:
        return None
    points.sort(key=lambda item: item.get("timestamp") or 0)
    return points[-1]


def _walk_points(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        lat = node.get("lat", node.get("latitude"))
        # Some payloads spell longitude "lot".
        lon = node.get("lon", node.get("lot", node.get("longitude")))
        # 0,0 is an empty fix from the server, not a real position.
        if _is_number(lat) and _is_number(lon) and not (float(lat) == 0 and float(lon) == 0):
            stamp = node.get("timestamp") or node.get("location_time") or node.get("gps_time") or node.get("stamp")
            found.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "accuracy": _optional_float(node.get("radius")),
                    "timestamp": _optional_float(stamp),
                    "address": node.get("address") or node.get("address_poi"),
                    "loc_type": node.get("loc_type") or node.get("locationType") or node.get("type"),
                }
            )
        for value in node.values():
            found.extend(_walk_points(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_points(value))
    return found


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _optional_float(value: Any) -> float | None:
    if not _is_number(value):
        return None
    return float(value)


def _payload_data(payload: dict[str, Any]) -> Any:
    return payload.get("data") if "data" in payload else payload


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("list", "records", "rows", "items", "content"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _first_number(*values: Any) -> float | None:
    for value in values:
        if _is_number(value):
            return float(value)
    return None


def _text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_device(payload: dict[str, Any]) -> dict[str, Any]:
    """Online flag, model, and any heart-rate or temperature the device payload carries."""
    data = _as_dict(_payload_data(payload))
    if not data and isinstance(payload.get("data"), dict):
        data = payload["data"]
    online = data.get("onlineStatus", data.get("online"))
    parsed: dict[str, Any] = {
        "model": _text(data.get("model")),
        "phone": _text(data.get("phone")),
    }
    if online is not None and _is_number(online):
        parsed["online"] = int(float(online)) == 1
    heart = _first_number(data.get("lastHeartRate"), data.get("heartRate"), data.get("heart"))
    if heart is not None:
        parsed["heart_rate"] = heart
        parsed["heart_rate_at"] = _first_number(data.get("lastHeartRateTime"), data.get("heartRateTime"))
    temperature = _first_number(data.get("lastTemperature"), data.get("temperature"))
    if temperature is not None:
        parsed["temperature"] = temperature
        parsed["temperature_at"] = _first_number(data.get("lastTemperatureTime"), data.get("temperatureTime"))
    battery = _first_number(data.get("battery"))
    if battery is not None:
        parsed["battery"] = battery
    return {key: value for key, value in parsed.items() if value is not None}


def parse_system_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Battery, SOS numbers, and location mode from the stored system config."""
    data = _as_dict(_payload_data(payload))
    parsed: dict[str, Any] = {}
    battery = data.get("battery")
    percent = None
    updated = None
    if isinstance(battery, dict):
        percent = _first_number(battery.get("percent"), battery.get("battery"))
        updated = _first_number(battery.get("updateTime"), battery.get("update_time"))
    else:
        percent = _first_number(battery)
    if percent is not None:
        parsed["battery"] = percent
    if updated is not None:
        parsed["battery_updated"] = updated
    flags = {
        "batterySwitch": "battery_switch",
        "longLifeMode": "long_life_mode",
        "sportsSwitch": "sports",
        "callWhitelist": "call_whitelist",
        "positionSwitch": "position_reports",
        "smsSwitch": "sms_filter",
        "autoAnswer": "auto_answer",
        "bootOffSwitch": "scheduled_power_off",
        "appSwitch": "app_install",
    }
    for source, key in flags.items():
        if _is_number(data.get(source)):
            parsed[key] = int(float(data[source])) == 1
    if _is_number(data.get("locMode")):
        parsed["location_mode"] = int(float(data["locMode"]))
    sos = data.get("sos")
    numbers: list[str] = []
    if isinstance(sos, dict):
        for key in ("sos1", "sos2", "sos3"):
            number = _text(sos.get(key))
            if number:
                numbers.append(number)
    elif isinstance(sos, list):
        numbers = [item for item in (_text(value) for value in sos) if item]
    parsed["sos"] = numbers
    return parsed


def _sport_total(rows: list[dict[str, Any]], total_key: str, part_key: str, extra_part: str | None = None) -> float | None:
    totals = [_first_number(row.get(total_key)) for row in rows]
    totals = [value for value in totals if value is not None]
    if totals:
        return max(totals)
    parts: list[float] = []
    for row in rows:
        value = _first_number(row.get(part_key), row.get(extra_part) if extra_part else None)
        if value is not None:
            parts.append(value)
    if not parts:
        return None
    return sum(parts)


def parse_sport(payload: dict[str, Any]) -> dict[str, Any]:
    """Collapse hourly rows into one steps, distance, and calorie total."""
    data = _payload_data(payload)
    rows = [row for row in _as_list(data) if isinstance(row, dict)]
    if isinstance(data, dict) and not rows:
        rows = [data]
    parsed: dict[str, Any] = {}
    steps = _sport_total(rows, "totalStep", "step", "num")
    distance = _sport_total(rows, "totalDistance", "distance")
    calories = _sport_total(rows, "totalCalorie", "calorie")
    goal = None
    for row in rows:
        goal = _first_number(row.get("target"), row.get("aim")) or goal
    if steps is not None:
        parsed["steps"] = steps
    if distance is not None:
        parsed["distance"] = distance
    if calories is not None:
        parsed["calories"] = calories
    if goal is not None:
        parsed["step_goal"] = goal
    return parsed


def parse_wifi(payload: dict[str, Any]) -> list[dict[str, Any]]:
    networks: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        name = _text(item.get("ssid"), item.get("name"), item.get("wifiSsid"))
        if not name:
            continue
        networks.append({"ssid": name, "signal": _first_number(item.get("signal"))})
    return networks


def parse_places(payload: dict[str, Any]) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        name = _text(item.get("addrName"), item.get("name"), item.get("address"))
        if not name:
            continue
        places.append(
            {
                "name": name,
                "detail": _text(item.get("addrDetail")),
                "range": _first_number(item.get("addrRange"), item.get("radius")),
            }
        )
    return places


def parse_safe_zones(payload: dict[str, Any]) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        name = _text(item.get("ruleName"), item.get("name"), item.get("address"))
        if not name:
            continue
        status = item.get("status")
        zones.append(
            {
                "name": name,
                "enabled": int(float(status)) == 1 if _is_number(status) else None,
            }
        )
    return zones


def parse_reminders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reminders: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        content = _text(item.get("reminderContent"), item.get("content"), item.get("name"))
        if not content:
            continue
        reminders.append(
            {
                "content": content,
                "label": _text(item.get("reminderLabel")),
                "time": _text(item.get("firstReminderTime"), item.get("time")),
                "date": _text(item.get("dateStr")),
            }
        )
    return reminders


def parse_contacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        name = _text(item.get("name"), item.get("realName"))
        phone = _text(item.get("phone"), item.get("number"))
        if not name and not phone:
            continue
        contacts.append({"name": name, "phone": phone})
    return contacts


def parse_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        phone = _text(item.get("phone"), item.get("number"), item.get("callNumber"))
        if not phone and not _text(item.get("name")):
            continue
        calls.append(
            {
                "name": _text(item.get("name")),
                "phone": phone,
                "time": _first_number(item.get("timestamp"), item.get("time"), item.get("callTime")),
                "direction": _text(item.get("type"), item.get("callType")),
            }
        )
    return calls


def parse_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in _iter_dicts(payload):
        content = _text(item.get("content"), item.get("sms"), item.get("message"), item.get("text"))
        if not content:
            continue
        messages.append(
            {
                "content": content,
                "phone": _text(item.get("phone"), item.get("number"), item.get("sender")),
                "time": _first_number(item.get("timestamp"), item.get("time")),
            }
        )
    return messages


def _iter_dicts(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    data = _payload_data(payload) if isinstance(payload, dict) else payload
    walk(data)
    return found
