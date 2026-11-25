import pytest

from app.services.ar import bucket_for, dunning_level


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (-3, "0-30"),
        (0, "0-30"),
        (30, "0-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "90+"),
        (400, "90+"),
    ],
)
def test_aging_bucket_boundaries(days: int, bucket: str) -> None:
    assert bucket_for(days) == bucket


@pytest.mark.parametrize(
    ("days", "level"), [(-1, 0), (0, 0), (1, 1), (30, 1), (31, 2), (60, 2), (61, 3), (365, 3)]
)
def test_dunning_level_boundaries(days: int, level: int) -> None:
    assert dunning_level(days) == level
