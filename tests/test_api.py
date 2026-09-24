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
_latest_point = _api._latest_point
_raise_for_api_error = _api._raise_for_api_error
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


class ParseTests(unittest.TestCase):
    def test_last_location_uses_lot_as_longitude(self) -> None:
        point = _latest_point({"data": {"lat": 60.1, "lot": 24.9, "timestamp": 10, "address": "School"}})
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["lat"], 60.1)
        self.assertEqual(point["lon"], 24.9)
        self.assertEqual(point["address"], "School")

    def test_login_failed_is_auth(self) -> None:
        with self.assertRaises(ZteKidsAuthError):
            _raise_for_api_error({"code": 1132, "msg": "用户登录失败", "data": None})


if __name__ == "__main__":
    unittest.main()
