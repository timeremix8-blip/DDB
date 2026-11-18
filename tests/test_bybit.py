import hashlib, hmac, json

import pytest

from okx_bot.bybit_client import BybitClient, BybitError, sign


class FakeResp:
    status_code = 200
    def __init__(self, payload): self.payload = payload
    def json(self): return self.payload


def ok(result): return FakeResp({"retCode": 0, "retMsg": "OK", "result": result})


def test_sign_is_hex_hmac():
    exp = hmac.new(b"sec", b"1700000000000key5000category=spot", hashlib.sha256).hexdigest()
    assert sign("1700000000000", "key", "5000", "category=spot", "sec") == exp


def test_private_get_uses_demo_domain_and_signs_query(monkeypatch):
    c = BybitClient("key", "sec", demo=True)
    cap = {}
    def fake(method, url, headers, data, timeout):
        cap.update(url=url, headers=headers)
        return ok({"list": [{"coin": [{"coin": "USDT", "walletBalance": "100", "locked": "30"}]}]})
    monkeypatch.setattr(c.session, "request", fake)
    assert c.get_balance("USDT") == 70.0
    assert cap["url"].startswith("https://api-demo.bybit.com/v5/account/wallet-balance?")
    h = cap["headers"]
    query = cap["url"].split("?", 1)[1]
    assert h["X-BAPI-SIGN"] == sign(h["X-BAPI-TIMESTAMP"], "key", "5000", query, "sec")


def test_market_buy_body_and_post_signature(monkeypatch):
    c = BybitClient("key", "sec", demo=False)
    cap = {}
    def fake(method, url, headers, data, timeout):
        cap.update(url=url, headers=headers, data=data)
        return ok({"orderId": "123"})
    monkeypatch.setattr(c.session, "request", fake)
    assert c.place_market_order("BTC-USDT", "buy", "20.00", tgt_ccy="quote_ccy") == "123"
    body = json.loads(cap["data"])
    assert body == {"category": "spot", "symbol": "BTCUSDT", "side": "Buy",
                    "orderType": "Market", "qty": "20.00", "marketUnit": "quoteCoin"}
    assert cap["url"] == "https://api.bybit.com/v5/order/create"
    h = cap["headers"]
    assert h["X-BAPI-SIGN"] == sign(h["X-BAPI-TIMESTAMP"], "key", "5000", cap["data"], "sec")


def test_market_sell_uses_base_coin(monkeypatch):
    c = BybitClient("key", "sec")
    cap = {}
    monkeypatch.setattr(c.session, "request",
                        lambda m, u, headers, data, timeout: cap.update(data=data) or ok({"orderId": "9"}))
    c.place_market_order("BTC-USDT", "sell", "0.001")
    assert json.loads(cap["data"])["marketUnit"] == "baseCoin"


def test_candles_drop_live_candle_and_oldest_first(monkeypatch):
    c = BybitClient()
    rows = [["3", "1", "1", "1", "3", "1", "1"],  # 진행 중
            ["2", "1", "1", "1", "2", "1", "1"],
            ["1", "1", "1", "1", "1", "1", "1"]]
    monkeypatch.setattr(c.session, "request", lambda *a, **k: ok({"list": rows}))
    assert [x["close"] for x in c.get_candles("BTC-USDT", "15m")] == [1.0, 2.0]


def test_order_normalized_to_bot_format(monkeypatch):
    c = BybitClient("key", "sec")
    order = {"orderStatus": "Filled", "cumExecQty": "0.0002", "avgPrice": "100000",
             "cumExecFee": "0.0000002", "side": "Buy"}
    monkeypatch.setattr(c.session, "request", lambda *a, **k: ok({"list": [order]}))
    o = c.get_order("BTC-USDT", "1")
    assert o["state"] == "filled" and o["feeCcy"] == "BTC"
    assert float(o["accFillSz"]) + float(o["fee"]) == pytest.approx(0.0001998)


def test_error_raises(monkeypatch):
    c = BybitClient()
    monkeypatch.setattr(c.session, "request",
                        lambda *a, **k: FakeResp({"retCode": 10001, "retMsg": "bad", "result": {}}))
    with pytest.raises(BybitError):
        c.get_ticker("BTC-USDT")
