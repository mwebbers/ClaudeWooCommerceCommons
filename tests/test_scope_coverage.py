"""Guarantee that SCOPE.md and the test suite stay in sync.

This reads every feature ID (F-001, F-002, ...) from SCOPE.md, then reads every
feature ID referenced by @pytest.mark.feature(...) across the test files. It fails
if either side has an ID the other does not:

  - a feature in SCOPE.md with no test  -> behaviour is not guaranteed
  - a test marker pointing at a feature not in SCOPE.md -> stale/typo'd reference

The test markers are parsed statically from the test source files, so the result
does not depend on which subset of tests you happen to run.

This is what makes "current functionality is locked in across future updates" real:
you cannot quietly add or drop a feature without the suite noticing.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SCOPE_FILE = REPO_ROOT / "SCOPE.md"
SELF = Path(__file__).name

FEATURE_ID = re.compile(r"\bF-\d{3}\b")
# Matches: @pytest.mark.feature("F-001")  /  @pytest.mark.feature('F-001')
MARKER = re.compile(r"""@pytest\.mark\.feature\(\s*["'](F-\d{3})["']\s*\)""")


def features_in_scope() -> set[str]:
    text = SCOPE_FILE.read_text(encoding="utf-8")
    # Only the "Features (acceptance criteria)" section defines real features.
    section = text.split("## Features")[1].split("## Out of scope")[0]
    return set(FEATURE_ID.findall(section))


def features_in_tests() -> set[str]:
    covered: set[str] = set()
    for path in TESTS_DIR.glob("test_*.py"):
        if path.name == SELF:
            continue  # don't count this file's own example IDs in docstrings
        covered.update(MARKER.findall(path.read_text(encoding="utf-8")))
    return covered


def test_every_scope_feature_has_a_test():
    scope = features_in_scope()
    tested = features_in_tests()

    missing = scope - tested
    assert not missing, (
        f"Features in SCOPE.md without a test: {sorted(missing)}. "
        "Add a test tagged @pytest.mark.feature(...) for each."
    )

    stale = tested - scope
    assert not stale, (
        f"Tests reference feature IDs not in SCOPE.md: {sorted(stale)}. "
        "Fix the marker or add the feature to SCOPE.md."
    )
