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
            raise ZteKidsAuthError("Login response did not include a session.")
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
        """Return watches linked to the parent account."""
        url = urljoin(BASE_URL, f"getway/accounts/{openid}/related-device")
        payload = await self._request(
            "GET",
            url,
            params={"accesstoken": access_token},
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
        return devices

    async def query_location_history(
        self,
        imei: str,
        *,
        day: str,
        time_zone: int,
        timezone_str: str,
    ) -> dict[str, Any] | None:
        """Read stored points for one day. This does not wake the watch."""
        payload = await self._signed_post(
            "api/device/querylocation",
            {
                "day": day,
                "imei": imei,
                "timeZone": time_zone,
                "timezoneStr": timezone_str,
            },
        )
        return _latest_point(payload)

    async def request_location(self, imei: str, openid: str, access_token: str) -> dict[str, Any] | None:
        """Ask the server for the watch's latest fix.

        The app posts this as form fields. A fresh GPS fix is requested from the
        watch when the server does not already have a recent point, so callers
        must rate limit it.
        """
        url = urljoin(BASE_URL, f"getway/devices/{imei}/location/last")
        payload = await self._request(
            "POST",
            url,
            data={"openid": openid, "accesstoken": access_token},
        )
        return _latest_point(payload)

    async def _signed_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        signature = sign_body(body, timestamp, nonce)
        url = urljoin(BASE_URL, path)
        return await self._request(
            "POST",
            url,
            params={
                "sign": signature,
                "timestamp": timestamp,
                "nonce": nonce,
                "appKey": APP_KEY,
            },
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
                    raise ZteKidsError(f"ZTE Kids returned HTTP {response.status} for {method} {path_for_log(url)}.")
                payload: dict[str, Any]
                try:
                    parsed = await response.json(content_type=None)
                except Exception:
                    parsed = None
                if not isinstance(parsed, dict):
                    snippet = " ".join(text.split())[:200]
                    raise ZteKidsError(
                        f"ZTE Kids returned HTTP {response.status} for {method} {path_for_log(url)} "
                        f"with a non-JSON body: {snippet or '(empty)'}"
                    )
                payload = parsed
        except aiohttp.ClientError as err:
            raise ZteKidsError(f"Could not reach ZTE Kids at {path_for_log(url)}: {err}") from err
        _raise_for_api_error(payload)
        return payload


def _raise_for_api_error(payload: dict[str, Any]) -> None:
    # Success is code/ret 0 or 200. Captcha text means the login needs a second
    # step. 1132/1022 and token wording mean the saved session is dead.
    code = payload.get("code", payload.get("ret"))
    if code is None or code in _SUCCESS_CODES:
        return
    message = str(payload.get("msg") or payload.get("message") or payload.get("error") or code)
    lowered = message.lower()
    if any(word in lowered for word in ("captcha", "jigsaw", "验证码")):
        raise ZteKidsCodeRequired(message)
    if code in {401, 403, 1132, 1022, "401", "403", "1132", "1022"} or "token" in lowered or "登录" in message:
        raise ZteKidsAuthError(message)
    _LOGGER.warning("ZTE Kids API error code=%s message=%s", code, message)
    raise ZteKidsError(f"ZTE Kids API error {code}: {message}")


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
