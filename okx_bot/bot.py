"""메인 트레이딩 루프."""
import json
import logging
import os
import time
from decimal import Decimal, ROUND_DOWN

from .bybit_client import BybitClient
from .client import ExchangeError, OKXClient
from .config import Config
from .strategy import Signal, crossover_signal, risk_exit

log = logging.getLogger(__name__)


def make_client(cfg: Config):
    if cfg.exchange == "bybit":
        return BybitClient(cfg.api_key, cfg.api_secret, demo=cfg.demo)
    return OKXClient(cfg.api_key, cfg.api_secret, cfg.passphrase, demo=cfg.demo)


def round_down(value: float, step: str) -> str:
    d = Decimal(str(value)).quantize(Decimal(step), rounding=ROUND_DOWN)
    return format(d, "f")


class TradingBot:
    def __init__(self, cfg: Config, client: OKXClient | None = None):
        self.cfg = cfg
        self.client = client or make_client(cfg)
        self.base_ccy, self.quote_ccy = cfg.inst_id.split("-")
        self.state = self._load_state()
        self.last_candle_ts = None
        inst = self.client.get_instrument(cfg.inst_id)
        self.lot_sz, self.min_sz = inst["lotSz"], float(inst["minSz"])

    # ---------- 상태 저장 (재시작해도 포지션 기억) ----------
    def _load_state(self) -> dict:
        if os.path.exists(self.cfg.state_file):
            with open(self.cfg.state_file) as f:
                return json.load(f)
        return {"position": 0.0, "entry_price": None}

    def _save_state(self):
        with open(self.cfg.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    @property
    def in_position(self) -> bool:
        return self.state["position"] >= self.min_sz

    # ---------- 주문 ----------
    def buy(self, price: float, reason: str):
        usdt = self.cfg.order_usdt
        log.info("🟢 매수 시그널 [%s] %.2f %s @ ~%.2f", reason, usdt, self.quote_ccy, price)
        if self.cfg.dry_run:
            self.state.update(position=usdt / price, entry_price=price)
            self._save_state()
            return
        avail = self.client.get_balance(self.quote_ccy)
        if avail < usdt:
            log.warning("잔고 부족: %s %.2f < %.2f", self.quote_ccy, avail, usdt)
            return
        ord_id = self.client.place_market_order(self.cfg.inst_id, "buy", f"{usdt:.2f}", tgt_ccy="quote_ccy")
        order = self.client.wait_filled(self.cfg.inst_id, ord_id)
        filled = float(order.get("accFillSz") or 0)
        fee = float(order.get("fee") or 0)  # 수수료는 음수, 매수 시 BTC로 차감
        if order.get("feeCcy") == self.base_ccy:
            filled += fee
        if filled <= 0:
            log.error("매수 체결 실패: %s", order)
            return
        self.state.update(position=filled, entry_price=float(order["avgPx"]))
        self._save_state()
        log.info("체결: %.8f %s @ %s (ordId=%s)", filled, self.base_ccy, order["avgPx"], ord_id)

    def sell(self, price: float, reason: str):
        pos = self.state["position"]
        log.info("🔴 매도 시그널 [%s] %.8f %s @ ~%.2f", reason, pos, self.base_ccy, price)
        if not self.cfg.dry_run:
            pos = min(pos, self.client.get_balance(self.base_ccy))
            sz = round_down(pos, self.lot_sz)
            if float(sz) < self.min_sz:
                log.warning("매도 가능 수량(%s)이 최소 주문 수량(%s) 미만", sz, self.min_sz)
                self.state.update(position=0.0, entry_price=None)
                self._save_state()
                return
            ord_id = self.client.place_market_order(self.cfg.inst_id, "sell", sz)
            order = self.client.wait_filled(self.cfg.inst_id, ord_id)
            price = float(order.get("avgPx") or price)
            log.info("체결: %s %s @ %.2f (ordId=%s)", sz, self.base_ccy, price, ord_id)
        entry = self.state["entry_price"]
        if entry:
            log.info("이번 거래 손익: %.2f%%", (price - entry) / entry * 100)
        self.state.update(position=0.0, entry_price=None)
        self._save_state()

    # ---------- 한 번의 루프 ----------
    def step(self):
        last = float(self.client.get_ticker(self.cfg.inst_id)["last"])

        # 1) 손절/익절은 매 루프마다 체크
        if self.in_position and self.state["entry_price"]:
            reason = risk_exit(self.state["entry_price"], last,
                               self.cfg.stop_loss_pct, self.cfg.take_profit_pct)
            if reason:
                self.sell(last, reason)
                return

        # 2) 전략 시그널은 새 캔들이 마감됐을 때만 판단
        candles = self.client.get_candles(self.cfg.inst_id, self.cfg.bar, limit=self.cfg.ema_slow * 5)
        if not candles or candles[-1]["ts"] == self.last_candle_ts:
            return
        self.last_candle_ts = candles[-1]["ts"]
        signal = crossover_signal([c["close"] for c in candles], self.cfg.ema_fast, self.cfg.ema_slow)
        log.info("가격 %.2f | 시그널 %s | 포지션 %.8f", last, signal.value, self.state["position"])

        if signal is Signal.BUY and not self.in_position:
            self.buy(last, "EMA 골든크로스")
        elif signal is Signal.SELL and self.in_position:
            self.sell(last, "EMA 데드크로스")

    def run(self):
        mode = "DRY-RUN(주문 안 함)" if self.cfg.dry_run else ("데모" if self.cfg.demo else "⚠️ 실거래")
        log.info("봇 시작: [%s] %s %s, EMA %d/%d, 모드=%s", self.cfg.exchange.upper(), self.cfg.inst_id, self.cfg.bar,
                 self.cfg.ema_fast, self.cfg.ema_slow, mode)
        while True:
            try:
                self.step()
            except ExchangeError as e:
                log.error("거래소 API 오류: %s", e)
            except Exception:
                log.exception("예상치 못한 오류")
            time.sleep(self.cfg.poll_seconds)
