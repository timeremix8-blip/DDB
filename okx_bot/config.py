import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class Config:
    api_key: str
    api_secret: str
    passphrase: str
    demo: bool
    dry_run: bool
    inst_id: str
    bar: str
    ema_fast: int
    ema_slow: int
    order_usdt: float
    stop_loss_pct: float
    take_profit_pct: float
    poll_seconds: int
    state_file: str = "state.json"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        cfg = cls(
            api_key=os.getenv("OKX_API_KEY", ""),
            api_secret=os.getenv("OKX_API_SECRET", ""),
            passphrase=os.getenv("OKX_PASSPHRASE", ""),
            demo=_bool(os.getenv("OKX_DEMO", "1")),
            dry_run=_bool(os.getenv("DRY_RUN", "true")),
            inst_id=os.getenv("INST_ID", "BTC-USDT"),
            bar=os.getenv("BAR", "15m"),
            ema_fast=int(os.getenv("EMA_FAST", "9")),
            ema_slow=int(os.getenv("EMA_SLOW", "21")),
            order_usdt=float(os.getenv("ORDER_USDT", "20")),
            stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "2.0")),
            take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "4.0")),
            poll_seconds=int(os.getenv("POLL_SECONDS", "30")),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("EMA_FAST 는 EMA_SLOW 보다 작아야 합니다.")
        if self.order_usdt <= 0:
            raise ValueError("ORDER_USDT 는 0보다 커야 합니다.")
        if not self.dry_run and not (self.api_key and self.api_secret and self.passphrase):
            raise ValueError("DRY_RUN=false 이면 OKX API 키 3종이 모두 필요합니다.")
