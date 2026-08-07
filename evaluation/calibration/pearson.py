"""Pure Pearson correlation coefficient — no numpy/scipy dependency,
kept separate from run_calibration.py so it's trivially unit-testable
with synthetic data."""


def pearson_correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n != len(y):
        raise ValueError(f"x and y must be the same length, got {n} and {len(y)}")
    if n < 2:
        raise ValueError("need at least 2 points to compute a correlation")

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    denom = (var_x * var_y) ** 0.5
    if denom == 0:
        return 0.0  # no variance in one series — correlation undefined, treat as 0
    return cov / denom
