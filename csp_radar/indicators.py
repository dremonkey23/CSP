from __future__ import annotations


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    """Return Wilder RSI for the latest close, or None if unavailable."""
    values = [float(x) for x in closes if x is not None and float(x) > 0]
    if len(values) <= period:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(values, values[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    if len(gains) < period:
        return None

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
