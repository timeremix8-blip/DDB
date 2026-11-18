"""OKX REST API v5 클라이언트 (서명, 시세, 잔고, 주문)."""
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.okx.com"


class OKXError(Exception):
    def __init__(self, code, msg, data=None):
        super().__init__(f"OKX error {code}: {msg}")
        self.code, self.msg, self.data = code, msg, data


def sign(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    """OKX 서명: base64(HMAC-SHA256(secret, timestamp + METHOD + path(+query) + body))."""
    prehash = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class OKXClient:
    def __init__(self, api_key="", api_secret="", passphrase="", demo=True,
                 base_url=BASE_URL, timeout=10, max_retries=3):
        self.api_key, self.api_secret, self.passphrase = api_key, api_secret, passphrase
        self.demo = demo
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    # ---------- 저수준 요청 ----------
    def _request(self, method: str, path: str, params=None, body=None, auth=False):
        query = f"?{urlencode(params)}" if params else ""
        request_path = path + query
        body_str = json.dumps(body, separators=(",", ":")) if body else ""

        for attempt in range(1, self.max_retries + 1):
            headers = {"Content-Type": "application/json"}
            if self.demo:
                headers["x-simulated-trading"] = "1"
            if auth:
                ts = iso_timestamp()
                headers.update({
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": sign(ts, method, request_path, body_str, self.api_secret),
                    "OK-ACCESS-TIMESTAMP": ts,
                    "OK-ACCESS-PASSPHRASE": self.passphrase,
                })
            try:
                resp = self.session.request(method, self.base_url + request_path,
                                            headers=headers, data=body_str or None,
                                            timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                payload = resp.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == self.max_retries:
                    raise
                wait = 2 ** attempt
                log.warning("요청 실패 (%s), %s초 후 재시도 %d/%d", e, wait, attempt, self.max_retries)
                time.sleep(wait)
                continue

            if payload.get("code") != "0":
                raise OKXError(payload.get("code"), payload.get("msg"), payload.get("data"))
            return payload.get("data", [])

    # ---------- 공개 API ----------
    def get_instrument(self, inst_id: str) -> dict:
        data = self._request("GET", "/api/v5/public/instruments",
                             {"instType": "SPOT", "instId": inst_id})
        return data[0]

    def get_ticker(self, inst_id: str) -> dict:
        return self._request("GET", "/api/v5/market/ticker", {"instId": inst_id})[0]

    def get_candles(self, inst_id: str, bar="15m", limit=100) -> list[dict]:
        """확정된(마감된) 캔들만 오래된 순서로 반환."""
        rows = self._request("GET", "/api/v5/market/candles",
                             {"instId": inst_id, "bar": bar, "limit": str(limit)})
        candles = [
            {"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4]), "vol": float(r[5]),
             "confirmed": r[8] == "1"}
            for r in rows
        ]
        candles.reverse()  # OKX는 최신순으로 줌 → 오래된 순으로
        return [c for c in candles if c["confirmed"]]

    # ---------- 개인 API ----------
    def get_balance(self, ccy: str) -> float:
        data = self._request("GET", "/api/v5/account/balance", {"ccy": ccy}, auth=True)
        for d in data[0].get("details", []) if data else []:
            if d["ccy"] == ccy:
                return float(d.get("availBal") or 0)
        return 0.0

    def place_market_order(self, inst_id: str, side: str, sz: str, tgt_ccy=None) -> str:
        """현물 시장가 주문. 매수는 기본적으로 sz=USDT 금액, 매도는 sz=BTC 수량."""
        body = {"instId": inst_id, "tdMode": "cash", "side": side,
                "ordType": "market", "sz": sz}
        if tgt_ccy:
            body["tgtCcy"] = tgt_ccy
        data = self._request("POST", "/api/v5/trade/order", body=body, auth=True)
        result = data[0]
        if result.get("sCode") != "0":
            raise OKXError(result.get("sCode"), result.get("sMsg"), result)
        return result["ordId"]

    def get_order(self, inst_id: str, ord_id: str) -> dict:
        return self._request("GET", "/api/v5/trade/order",
                             {"instId": inst_id, "ordId": ord_id}, auth=True)[0]

    def wait_filled(self, inst_id: str, ord_id: str, timeout=15) -> dict:
        deadline = time.time() + timeout
        while True:
            order = self.get_order(inst_id, ord_id)
            if order["state"] in ("filled", "canceled", "mmp_canceled"):
                return order
            if time.time() > deadline:
                return order
            time.sleep(1)
