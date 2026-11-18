from okx_bot.strategy import Signal, crossover_signal, ema, risk_exit
from okx_bot.bot import round_down


def test_ema_first_value_is_sma():
    assert ema([1, 2, 3], 3) == [2]


def test_golden_cross():
    closes = [100 - i for i in range(30)] + [120]  # 하락 후 급등
    assert crossover_signal(closes, 3, 8) == Signal.BUY


def test_dead_cross():
    closes = [100 + i for i in range(30)] + [80]  # 상승 후 급락
    assert crossover_signal(closes, 3, 8) == Signal.SELL


def test_not_enough_data():
    assert crossover_signal([1, 2, 3], 3, 8) == Signal.HOLD


def test_risk_exit():
    assert risk_exit(100, 97.9, 2, 4).startswith("손절")
    assert risk_exit(100, 104.1, 2, 4).startswith("익절")
    assert risk_exit(100, 101, 2, 4) is None


def test_round_down_lot_size():
    assert round_down(0.123456789, "0.00000001") == "0.12345678"
