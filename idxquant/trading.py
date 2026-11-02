"""IDX market mechanics: tick sizes and trading costs."""
import math

from idxquant.config import CONFIG


def tick_size(price: float) -> int:
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def round_tick(price: float, direction: str = "nearest") -> int:
    tick = tick_size(price)
    steps = round(price / tick, 6)  # Absorbs float noise so 2480.0000001 doesn't round up a tick
    if direction == "up":
        return math.ceil(steps) * tick
    if direction == "down":
        return math.floor(steps) * tick
    if direction == "nearest":
        return round(steps) * tick
    raise ValueError(f"unknown direction: {direction}")


def net_return(entry: float, exit: float, cfg=CONFIG) -> float:
    return (exit * (1 - cfg.sell_fee)) / (entry * (1 + cfg.buy_fee)) - 1
