import random
from collections.abc import Callable


def backoff_delay(
    attempt: int,
    base_seconds: float,
    max_seconds: float,
    rand: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait after failed attempt number `attempt` (1-based).

    Exponential backoff with "full jitter": the ceiling doubles each attempt (base, 2*base, 4*base, ...)
    up to max_seconds, and the actual wait is a random value between 0 and that ceiling. The jitter
    spreads retries out, so many workers failing at the same moment don't all hit the database
    again at the same moment.
    """
    ceiling = min(max_seconds, base_seconds * 2 ** (attempt - 1))
    return ceiling * rand()
