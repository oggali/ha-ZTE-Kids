"""Tests for request signing and location parsing. No live account."""

import hashlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "zte_kids"
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
_pkg = types.ModuleType("custom_components.zte_kids")
_pkg.__path__ = [str(_ROOT)]
_pkg.__package__ = "custom_components.zte_kids"
sys.modules["custom_components.zte_kids"] = _pkg


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "custom_components.zte_kids"
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


_const = _load("custom_components.zte_kids.const", "const.py")
_api = _load("custom_components.zte_kids.api", "api.py")
ZteKidsAuthError = _api.ZteKidsAuthError
captcha_destination_type = _api.captcha_destination_type
_latest_point = _api._latest_point
_raise_for_api_error = _api._raise_for_api_error
parse_calls = _api.parse_calls
parse_device = _api.parse_device
parse_messages = _api.parse_messages
parse_sport = _api.parse_sport
parse_system_config = _api.parse_system_config
sign_body = _api.sign_body
APP_KEY = _const.APP_KEY
APP_SECRET = _const.APP_SECRET


class SignTests(unittest.TestCase):
    def test_sign_includes_secret_and_app_key(self) -> None:
        signature = sign_body({"b": "2", "a": "1"}, "1000", "abc")
        pairs = {
            "a": "1",
            "b": "2",
            "appKey": APP_KEY,
            "nonce": "abc",
            "timestamp": "1000",
        }
        raw = "".join(f"{key}={pairs[key]}&" for key in sorted(pairs)) + APP_SECRET
        self.assertEqual(signature, hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(len(signature), 64)

    def test_gateway_query_signs_openid_and_token(self) -> None:
        fields = {"openid": "parent", "accesstoken": "token"}
        query = _api._signature_query(fields)
        self.assertEqual(set(query), {"sign", "timestamp", "nonce", "appKey"})
        self.assertEqual(query["appKey"], APP_KEY)
        self.assertEqual(query["sign"], sign_body(fields, query["timestamp"], query["nonce"]))


class ParseTests(unittest.TestCase):
    def test_last_location_uses_lot_as_longitude(self) -> None:
        point = _latest_point({"data": {"lat": 60.1, "lot": 24.9, "timestamp": 10, "address": "School"}})
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["lat"], 60.1)
        self.assertEqual(point["lon"], 24.9)
        self.assertEqual(point["address"], "School")

    def test_captcha_destination_follows_account(self) -> None:
        self.assertEqual(captcha_destination_type("parent@example.com"), "EMAIL")
        self.assertEqual(captcha_destination_type("+358401234567"), "MOBILE_PHONE")

    def test_login_failed_is_auth(self) -> None:
        with self.assertRaises(ZteKidsAuthError):
            _raise_for_api_error({"code": 1132, "msg": "用户登录失败", "data": None})

    def test_system_config_reads_battery_and_sos(self) -> None:
        parsed = parse_system_config(
            {
                "data": {
                    "battery": {"percent": 0, "updateTime": 1700000000000},
                    "batterySwitch": 1,
                    "locMode": 2,
                    "sos": {"sos1": "112", "sos2": "", "sos3": "0500"},
                }
            }
        )
        self.assertEqual(parsed["battery"], 0)
        self.assertEqual(parsed["battery_updated"], 1700000000000)
        self.assertEqual(parsed["sos"], ["112", "0500"])
        self.assertTrue(parsed["battery_switch"])
        self.assertEqual(parsed["location_mode"], 2)

    def test_system_config_reads_setting_flags(self) -> None:
        parsed = parse_system_config({"data": {"sportsSwitch": 0, "callWhitelist": 1, "locMode": 3}})
        self.assertFalse(parsed["sports"])
        self.assertTrue(parsed["call_whitelist"])
        self.assertEqual(parsed["location_mode"], 3)

    def test_device_online_and_heart_rate(self) -> None:
        parsed = parse_device(
            {"data": {"onlineStatus": 1, "model": "Kids", "lastHeartRate": "88", "lastHeartRateTime": 10}}
        )
        self.assertTrue(parsed["online"])
        self.assertEqual(parsed["heart_rate"], 88)
        self.assertEqual(parsed["model"], "Kids")

    def test_sport_prefers_daily_total_over_hourly_parts(self) -> None:
        parsed = parse_sport(
            {
                "data": [
                    {"step": 100, "totalStep": 4000, "distance": 0.2, "totalDistance": 1.5, "calorie": 10, "totalCalorie": 80},
                    {"step": 200, "totalStep": 4000, "distance": 0.3, "totalDistance": 1.5, "calorie": 20, "totalCalorie": 80, "target": 8000},
                ]
            }
        )
        self.assertEqual(parsed["steps"], 4000)
        self.assertEqual(parsed["distance"], 1.5)
        self.assertEqual(parsed["calories"], 80)
        self.assertEqual(parsed["step_goal"], 8000)

    def test_sport_sums_hourly_rows_without_a_total(self) -> None:
        parsed = parse_sport({"data": [{"step": 10, "distance": 0.1, "calorie": 2}, {"num": 15}]})
        self.assertEqual(parsed["steps"], 25)
        self.assertEqual(parsed["distance"], 0.1)

    def test_call_and_message_pages(self) -> None:
        calls = parse_calls({"data": {"records": [{"phone": "0500", "name": "Home", "timestamp": 5, "type": "in"}]}})
        messages = parse_messages({"data": [{"content": "ok", "phone": "0500", "timestamp": 6}]})
        self.assertEqual(calls[0]["phone"], "0500")
        self.assertEqual(messages[0]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
