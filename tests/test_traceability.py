"""tests/TRACEABILITY.md stays honest: every port test it names exists, and no row is lost."""
import ast
import re
from pathlib import Path

TESTS = Path(__file__).parent
DOC = (TESTS / "TRACEABILITY.md").read_text(encoding="utf-8")
LUBA_TESTS_FUNCTIONS = 290            # luba-tests at the P0 fix commit
ROW = re.compile(r"^\| `(test_[a-z0-9_]+)` \| (.+) \|$", re.M)
REF = re.compile(r"`((?:engine/)?test_[a-z0-9_]+\.py)::(test_[a-z0-9_]+)`")


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}


def test_every_row_is_present_and_answered():
    rows = ROW.findall(DOC)
    assert len(rows) == LUBA_TESTS_FUNCTIONS
    for name, port in rows:
        assert REF.search(port) or port.startswith(("retired", "covered")), name


def test_every_referenced_port_test_exists():
    refs = REF.findall(DOC)
    assert refs
    missing = [f"{file}::{name}" for file, name in refs if name not in _functions(TESTS / file)]
    assert missing == []
