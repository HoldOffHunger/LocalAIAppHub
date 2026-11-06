import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_topics import house  # noqa: E402


def test_only_house_tags_are_kept_with_plurals_matched():
    known = {"anarchism", "state", "unions", "imperialism", "workers", "worker"}
    assert house(["anarchism", "the state", "union", "imperialism", "anarchism", "made-up thing"], known) == \
        ["anarchism", "state", "unions", "imperialism"]


def test_never_more_than_five():
    known = {f"tag{n}" for n in range(9)}
    assert len(house([f"tag{n}" for n in range(9)], known)) == 5
