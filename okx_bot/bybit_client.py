"""Bybit REST API V5 클라이언트 (현물). OKXClient와 같은 메서드를 제공한다."""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import requests

from .client import ExchangeError

log = logging.getLogger(__name__)

MAINNET_URL = "https://api.bybit.com"
DEMO_URL = "https://api-demo.bybit.com"  # 데모 트레이딩 (데모 계정에서 발급한 키 필요)

# OKX 표기 → Bybit kline interval
INTERVALS = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
             "1H": "60", "2H": "120", "4H": "240", "6H": "360", "12H": "720",
             "1D": "D", "1W": "W", "1M": "M"}

_STATE = {"Filled": "filled", "Cancelled": "canceled", "Rejected": "canceled",
          "PartiallyFilledCanceled": "canceled", "Deactivated": "canceled"}


class BybitError(ExchangeError):
    def __init__(self, code, msg, data=None):
        super().__init__(f"Bybit error {code}: {msg}")
        self.code, self.msg, self.data = code, msg, data


def sign(timestamp: str, api_key: str, recv_window: str, payload: str, secret: str) -> str:
    """Bybit 서명: hex(HMAC-SHA256(secret, timestamp + apiKey + recvWindow + 쿼리문자열 또는 JSON body))."""
    prehash = f"{timestamp}{api_key}{recv_window}{payload}"
    return hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()


def to_symbol(inst_id: str) -> str:
    return inst_id.replace("-", "")  # BTC-USDT → BTCUSDT


class BybitClient:
    def __init__(self, api_key="", api_secret="", demo=True, timeout=10,
                 max_retries=3, recv_window="5000"):
        self.api_key, self.api_secret = api_key, api_secret
        self.demo = demo
        # 시세는 데모여도 실서버 데이터(동일 가격)를 쓰고, 개인 API만 데모 서버로 보낸다
        self.public_url = MAINNET_URL
        self.private_url = DEMO_URL if demo else MAINNET_URL
        self.timeout, self.max_retries, self.recv_window = timeout, max_retries, recv_window
        self.session = requests.Session()

    # ---------- 저수준 요청 ----------
    def _request(self, method: str, path: str, params=None, body=None, auth=False):
        query = urlencode(params) if params else ""
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        url = (self.private_url if auth else self.public_url) + path + (f"?{query}" if query else "")

        for attempt in range(1, self.max_retries + 1):
            headers = {"Content-Type": "application/json"}
            if auth:
                ts = str(int(time.time() * 1000))
                payload = body_str if method == "POST" else query
                headers.update({
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": ts,
                    "X-BAPI-RECV-WINDOW": self.recv_window,
                    "X-BAPI-SIGN": sign(ts, self.api_key, self.recv_window, payload, self.api_secret),
                })
            try:
                resp = self.session.request(method, url, headers=headers,
                                            data=body_str or None, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == self.max_retries:
                    raise
                wait = 2 ** attempt
                log.warning("요청 실패 (%s), %s초 후 재시도 %d/%d", e, wait, attempt, self.max_retries)
                time.sleep(wait)
                continue

            if data.get("retCode") != 0:
                raise BybitError(data.get("retCode"), data.get("retMsg"), data)
            return data.get("result", {})

    # ---------- 공개 API ----------
    def get_instrument(self, inst_id: str) -> dict:
        r = self._request("GET", "/v5/market/instruments-info",
                          {"category": "spot", "symbol": to_symbol(inst_id)})
        lot = r["list"][0]["lotSizeFilter"]
        return {"lotSz": lot["basePrecision"], "minSz": lot["minOrderQty"],
                "minOrderAmt": lot.get("minOrderAmt")}

    def get_ticker(self, inst_id: str) -> dict:
        r = self._request("GET", "/v5/market/tickers",
                          {"category": "spot", "symbol": to_symbol(inst_id)})
        return {"last": r["list"][0]["lastPrice"]}

    def get_candles(self, inst_id: str, bar="15m", limit=100) -> list[dict]:
        """마감된 캔들만 오래된 순서로 반환 (Bybit는 최신순, 첫 번째는 진행 중인 캔들)."""
        if bar not in INTERVALS:
            raise ValueError(f"지원하지 않는 BAR: {bar} (가능: {', '.join(INTERVALS)})")
        r = self._request("GET", "/v5/market/kline",
                          {"category": "spot", "symbol": to_symbol(inst_id),
                           "interval": INTERVALS[bar], "limit": str(limit + 1)})
        rows = r["list"][1:]  # 진행 중인 최신 캔들 제외
        candles = [{"ts": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                    "low": float(x[3]), "close": float(x[4]), "vol": float(x[5]),
                    "confirmed": True} for x in rows]
        candles.reverse()
        return candles

    # ---------- 개인 API ----------
    def get_balance(self, ccy: str) -> float:
        r = self._request("GET", "/v5/account/wallet-balance",
                          {"accountType": "UNIFIED", "coin": ccy}, auth=True)
        for acct in r.get("list", []):
            for c in acct.get("coin", []):
                if c["coin"] == ccy:
                    return float(c.get("walletBalance") or 0) - float(c.get("locked") or 0)
        return 0.0

    def place_market_order(self, inst_id: str, side: str, sz: str, tgt_ccy=None) -> str:
        """매수는 sz=USDT 금액(quoteCoin), 매도는 sz=BTC 수량(baseCoin)."""
        unit = "quoteCoin" if (tgt_ccy == "quote_ccy" or (tgt_ccy is None and side == "buy")) else "baseCoin"
        body = {"category": "spot", "symbol": to_symbol(inst_id),
                "side": side.capitalize(), "orderType": "Market",
                "qty": sz, "marketUnit": unit}
        return self._request("POST", "/v5/order/create", body=body, auth=True)["orderId"]

    def get_order(self, inst_id: str, ord_id: str) -> dict:
        params = {"category": "spot", "symbol": to_symbol(inst_id), "orderId": ord_id}
        lst = self._request("GET", "/v5/order/realtime", params, auth=True).get("list", [])
        if not lst:  # 이미 종료된 주문은 history에서 조회
            lst = self._request("GET", "/v5/order/history", params, auth=True).get("list", [])
        if not lst:
            return {"state": "live"}
        return self._normalize(lst[0], inst_id)

    @staticmethod
    def _normalize(o: dict, inst_id: str) -> dict:
        """봇이 쓰는 OKX 형식(state/accFillSz/avgPx/fee/feeCcy)으로 변환."""
        base = inst_id.split("-")[0]
        return {
            "state": _STATE.get(o.get("orderStatus"), "live"),
            "accFillSz": o.get("cumExecQty") or "0",
            "avgPx": o.get("avgPrice") or "0",
            # 현물 매수 수수료는 받는 코인(BTC)에서 차감됨. 매도 시 수량은 잔고로 한 번 더 보정한다.
            "fee": str(-float(o.get("cumExecFee") or 0)),
            "feeCcy": base if o.get("side") == "Buy" else inst_id.split("-")[1],
        }

    def wait_filled(self, inst_id: str, ord_id: str, timeout=15) -> dict:
        deadline = time.time() + timeout
        while True:
            order = self.get_order(inst_id, ord_id)
            if order["state"] in ("filled", "canceled") or time.time() > deadline:
                return order
            time.sleep(1)
