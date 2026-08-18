"""Tests for hsv.py Fibonacci functions"""

import pytest

from hsv import fib, fib_series


@pytest.mark.parametrize("n,expected", [
    (0, 0),
    (1, 1),
    (2, 1),
    (3, 2),
    (5, 5),
    (10, 55),
])
def test_fib(n, expected):
    assert fib(n) == expected

def test_fib_negative():
    with pytest.raises(ValueError):
        fib(-1)

@pytest.mark.parametrize("count,expected", [
    (0, []),
    (1, [0]),
    (2, [0, 1]),
    (5, [0, 1, 1, 2, 3]),
    (10, [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]),
])
def test_fib_series(count, expected):
    assert fib_series(count) == expected

def test_fib_series_negative():
    with pytest.raises(ValueError):
        fib_series(-5)
