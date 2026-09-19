"""Task-cluster bootstrap utilities with explicit reproducible seeds."""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable, Sequence


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    location = (len(ordered) - 1) * probability
    lower = int(location)
    upper = min(lower + 1, len(ordered) - 1)
    weight = location - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_interval(
    task_values: Sequence[float],
    *,
    seed: int,
    samples: int = 10_000,
    statistic: Callable[[Sequence[float]], float] = statistics.fmean,
) -> tuple[float | None, float | None]:
    if not task_values:
        return None, None
    randomizer = random.Random(seed)
    size = len(task_values)
    estimates = [
        statistic([task_values[randomizer.randrange(size)] for _ in range(size)])
        for _ in range(samples)
    ]
    return percentile(estimates, 0.025), percentile(estimates, 0.975)
