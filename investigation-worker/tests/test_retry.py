import pytest

from app.retry import backoff_delay


@pytest.mark.parametrize(
    ("attempt", "expected_ceiling"),
    [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0), (6, 10.0), (20, 10.0)],
)
def test_ceiling_doubles_per_attempt_up_to_the_cap(attempt, expected_ceiling):
    # rand() = 1.0 gives the ceiling itself
    assert backoff_delay(attempt, 0.5, 10.0, rand=lambda: 1.0) == expected_ceiling


def test_full_jitter_can_be_zero():
    assert backoff_delay(3, 0.5, 10.0, rand=lambda: 0.0) == 0.0


def test_real_random_delay_stays_within_bounds():
    for attempt in range(1, 10):
        delay = backoff_delay(attempt, 0.5, 10.0)
        assert 0.0 <= delay <= min(10.0, 0.5 * 2 ** (attempt - 1))
