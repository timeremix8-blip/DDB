import base64, hashlib, hmac

from okx_bot.client import OKXClient, sign


def test_sign_matches_okx_spec():
    ts, secret = "2020-12-08T09:08:57.715Z", "secret"
    path = "/api/v5/account/balance?ccy=BTC"
    expected = base64.b64encode(
        hmac.new(secret.encode(), f"{ts}GET{path}".encode(), hashlib.sha256).digest()
    ).decode()
    assert sign(ts, "get", path, "", secret) == expected


class FakeResp:
    status_code = 200
    def __init__(self, payload): self.payload = payload
    def json(self): return self.payload


def test_demo_header_and_auth_headers(monkeypatch):
    c = OKXClient("k", "s", "p", demo=True)
    captured = {}
    def fake_request(method, url, headers, data, timeout):
        captured.update(headers=headers, url=url)
        return FakeResp({"code": "0", "data": [{"details": [{"ccy": "USDT", "availBal": "50.5"}]}]})
    monkeypatch.setattr(c.session, "request", fake_request)
    assert c.get_balance("USDT") == 50.5
    h = captured["headers"]
    assert h["x-simulated-trading"] == "1"
    assert h["OK-ACCESS-KEY"] == "k" and h["OK-ACCESS-PASSPHRASE"] == "p"
    assert captured["url"].endswith("/api/v5/account/balance?ccy=USDT")


def test_candles_oldest_first_and_confirmed_only(monkeypatch):
    c = OKXClient()
    rows = [["3", "1", "1", "1", "3", "1", "1", "1", "0"],   # 진행 중 캔들
            ["2", "1", "1", "1", "2", "1", "1", "1", "1"],
            ["1", "1", "1", "1", "1", "1", "1", "1", "1"]]
    monkeypatch.setattr(c.session, "request",
                        lambda *a, **k: FakeResp({"code": "0", "data": rows}))
    assert [x["close"] for x in c.get_candles("BTC-USDT")] == [1.0, 2.0]
