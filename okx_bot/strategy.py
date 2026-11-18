"""EMA 골든/데드 크로스 전략 + 손절/익절."""
from enum import Enum


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]  # 첫 값은 SMA
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def crossover_signal(closes: list[float], fast: int, slow: int) -> Signal:
    """직전 캔들 대비 마지막 캔들에서 교차가 일어났는지 판단."""
    f, s = ema(closes, fast), ema(closes, slow)
    if len(s) < 2:
        return Signal.HOLD
    f = f[-len(s):]  # 길이 맞추기
    prev_diff, cur_diff = f[-2] - s[-2], f[-1] - s[-1]
    if prev_diff <= 0 < cur_diff:
        return Signal.BUY
    if prev_diff >= 0 > cur_diff:
        return Signal.SELL
    return Signal.HOLD


def risk_exit(entry_price: float, last_price: float, sl_pct: float, tp_pct: float) -> str | None:
    change = (last_price - entry_price) / entry_price * 100
    if change <= -sl_pct:
        return f"손절 ({change:.2f}%)"
    if change >= tp_pct:
        return f"익절 ({change:.2f}%)"
    return None
