# hsv.py
"""
Simple Fibonacci series implementation.

Provides two utilities:
- `fib(n)`: Returns the nth Fibonacci number (0-indexed).
- `fib_series(count)`: Returns a list containing the first `count` Fibonacci numbers.

Both functions use an iterative approach for O(n) time and O(1) extra space.
"""

def fib(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed).

    Args:
        n: Index of the desired Fibonacci number (must be >= 0).

    Returns:
        The nth Fibonacci number.
    """
    if n < 0:
        raise ValueError("n must be a non‑negative integer")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def fib_series(count: int) -> list[int]:
    """Return a list containing the first `count` Fibonacci numbers.

    Args:
        count: Number of terms to generate (must be >= 0).

    Returns:
        List of Fibonacci numbers starting from 0.
    """
    if count < 0:
        raise ValueError("count must be a non‑negative integer")
    series = []
    a, b = 0, 1
    for _ in range(count):
        series.append(a)
        a, b = b, a + b
    return series


if __name__ == "__main__":
    # Simple demo when run directly.
    import sys
    try:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    except ValueError:
        print("Please provide an integer argument.")
        sys.exit(1)
    print(f"First {n} Fibonacci numbers: {fib_series(n)}")
