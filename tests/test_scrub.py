"""Self-test for tools/scrub_check.py: prove the gate fires on each class of leak.

Synthetic values are built at runtime so this file never trips the gate itself.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import scrub_check  # noqa: E402

TERM = "zz" + "synthetic-secret" + "zz"
ZONE = "Zz" + "Meadow"
HASH = str(7 * 10**18 + 123)             # 19 digits
HEX_ID = "ab" * 16                        # 32 hex
COORD = "42." + "1" * 6


def _tree(tmp_path: Path, files: dict[str, str], denylist: str) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / scrub_check.LOCAL_FILE).write_text(denylist, encoding="utf-8")
    return tmp_path


def _run(root: Path, monkeypatch, *args: str) -> int:
    monkeypatch.delenv(scrub_check.ENV_VAR, raising=False)
    return scrub_check.main([*args, str(root)])


def test_clean_tree_passes(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"a.py": "x = 1\n"}, f"{TERM}\n")
    assert _run(root, monkeypatch) == 0
    assert "clean" in capsys.readouterr().out


def test_denylist_term_fails_case_insensitively_without_echoing_it(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"docs/x.md": f"see {TERM.upper()}\n"}, f"# comment\n{TERM}\n")
    assert _run(root, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "docs/x.md:1: denylist term #2" in out
    assert TERM not in out.lower()


@pytest.mark.parametrize("value, label", [(HASH, "long integer"), (HEX_ID, "32-hex id"),
                                          (COORD, "high-precision coordinate")])
def test_generic_patterns_fail(tmp_path, monkeypatch, capsys, value, label):
    root = _tree(tmp_path, {"c.py": f"v = {value!r}\n"}, f"{TERM}\n")
    assert _run(root, monkeypatch) == 1
    assert label in capsys.readouterr().out


def test_fixtures_waive_patterns_and_tilde_terms_but_not_plain_terms(tmp_path, monkeypatch, capsys):
    files = {"tests/fixtures/f.json": f'{{"hash": {HASH}, "zone": "{ZONE}"}}\n'}
    root = _tree(tmp_path, files, f"{TERM}\n~{ZONE}\n")
    assert _run(root, monkeypatch) == 0
    (root / "tests/fixtures/f.json").write_text(TERM, encoding="utf-8")
    assert _run(root, monkeypatch) == 1


def test_tilde_term_fails_outside_fixtures(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"README.md": f"Mows the {ZONE}\n"}, f"~{ZONE}\n")
    assert _run(root, monkeypatch) == 1


def test_allow_marker_waives_patterns_only(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"c.py": f"v = {HASH}  # scrub: allow\n"}, f"{TERM}\n")
    assert _run(root, monkeypatch) == 0
    (root / "c.py").write_text(f"v = '{TERM}'  # scrub: allow\n", encoding="utf-8")
    assert _run(root, monkeypatch) == 1


def test_empty_denylist_fails_closed(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"a.py": "x = 1\n"}, "# nothing\n\n")
    assert _run(root, monkeypatch) == 2
    assert scrub_check.ENV_VAR in capsys.readouterr().err


def test_env_var_wins_over_local_file(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"a.py": f"{TERM}\n"}, "unrelated\n")
    monkeypatch.setenv(scrub_check.ENV_VAR, f"{TERM}\n")
    assert scrub_check.main([str(root)]) == 1


def test_history_scan_catches_author_and_message(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path, {"a.py": "x = 1\n"}, f"{TERM}\n")
    git = ["git", "-c", "user.name=someone", "-c", f"user.email={TERM}@example.invalid"]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(git + ["add", "a.py"], cwd=root, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], cwd=root, check=True)
    assert _run(root, monkeypatch) == 0              # tree only: clean
    assert _run(root, monkeypatch, "--history") == 1
    assert "commit " in capsys.readouterr().out


def test_repository_tree_has_no_generic_pattern_hits():
    """The real denylist is CI-only; the generic patterns can be checked anywhere."""
    hits = scrub_check.scan_tree(ROOT, [], [])
    assert hits == []
