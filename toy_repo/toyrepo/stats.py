"""Tiny statistics helpers used for demos and integration tests."""


def mean(values):
    if not values:
        raise ValueError("mean() of empty sequence")
    return sum(values) / len(values)


def median(values):
    if not values:
        raise ValueError("median() of empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def clamp(x, lo, hi):
    if lo > hi:
        raise ValueError("lo must be <= hi")
    return max(lo, min(x, hi))


def running_max(values):
    out = []
    best = None
    for v in values:
        if best is None or v > best:
            best = v
        out.append(best)
    return out
