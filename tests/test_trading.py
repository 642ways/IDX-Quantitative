import pytest

from idxquant.trading import net_return, round_tick, tick_size


def test_tick_bands():
    prices = (199, 200, 499, 500, 1999, 2000, 4990, 5000)
    assert [tick_size(p) for p in prices] == [1, 2, 2, 5, 5, 10, 10, 25]


def test_round_tick_directions():
    assert round_tick(2483, "up") == 2490
    assert round_tick(2483, "down") == 2480
    assert round_tick(201, "up") == 202


def test_round_tick_nearest():
    assert round_tick(2486) == 2490
    assert round_tick(2484) == 2480


def test_round_tick_crossing_band_stays_valid():
    rounded = round_tick(499.5, "up")
    assert rounded == 500
    assert rounded % tick_size(rounded) == 0


def test_round_tick_up_across_band_lands_on_new_band_tick():
    # 4,995 is on the old band's grid only if ticks of 10 were used; 5,000 is valid in both
    assert round_tick(4995, "up") == 5000
    assert round_tick(5003, "down") == 5000


def test_net_return_includes_both_fees():
    assert net_return(1000, 1100) == pytest.approx((1100 * 0.9975) / (1000 * 1.0015) - 1)
