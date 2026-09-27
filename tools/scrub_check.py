"""Scrub gate: fail when the repository carries install-specific data.

Two kinds of check, applied to every tracked file and (with --history) to
every commit's author, committer and message:

1. **Denylist terms** — exact, case-insensitive substrings: device and
   registry IDs, serials, notify targets, hostnames, names. The list is
   deliberately NOT in the tree (a public repo would publish it). CI reads it
   from the ``SCRUB_DENYLIST`` secret; locally, from the gitignored file
   ``.scrub-denylist``. One term per line; ``#`` starts a comment; a leading
   ``~`` means "allowed under tests/fixtures/" (e.g. zone display names that
   fixtures may legitimately use). An empty or missing denylist is an error,
   so an unconfigured secret fails closed.
2. **Generic patterns** — shapes that are install-specific whatever their
   value: long integers (Mammotion area hashes are 18-19 digits), 32-hex
   registry IDs and high-precision coordinates. Waived under tests/fixtures/
   (which must use synthetic values) and on any line containing
   ``scrub: allow``.

Hits are reported as ``<where>:<line>: <what>``. A denylist hit names the
term's line number in the denylist, never the term, so the log itself
leaks nothing.

Usage: python tools/scrub_check.py [--history] [ROOT]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ENV_VAR = "SCRUB_DENYLIST"
LOCAL_FILE = ".scrub-denylist"
FIXTURE_PREFIX = "tests/fixtures/"
ALLOW_MARK = "scrub: allow"
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc"}

PATTERNS: dict[str, re.Pattern[str]] = {
    "long integer (area hash?)": re.compile(r"(?<![\w.])-?\d{15,20}(?![\w.])"),
    "32-hex id (device/registry id?)": re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{32}(?![0-9A-Za-z])"),
    "high-precision coordinate": re.compile(r"(?<![\w.])-?\d{1,3}\.\d{5,}(?![\w.])"),
}


class DenylistError(Exception):
    pass


def load_denylist(root: Path, env: dict[str, str] | None = None):
    """Return (terms, fixture_ok_terms) as lists of (denylist_line, lowercase_term)."""
    env = os.environ if env is None else env
    text = env.get(ENV_VAR, "")
    if not text.strip():
        local = root / LOCAL_FILE
        text = local.read_text(encoding="utf-8") if local.is_file() else ""
    terms, fixture_ok = [], []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("~"):
            fixture_ok.append((number, line[1:].strip().lower()))
        else:
            terms.append((number, line.lower()))
    if not terms and not fixture_ok:
        raise DenylistError(f"denylist is empty: set the {ENV_VAR} secret/env var or create {LOCAL_FILE}")
    return terms, fixture_ok


def scan_text(where: str, text: str, terms, fixture_ok, *, in_fixtures: bool) -> list[str]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        for number, term in terms:
            if term in lower:
                hits.append(f"{where}:{lineno}: denylist term #{number}")
        if not in_fixtures:
            for number, term in fixture_ok:
                if term in lower:
                    hits.append(f"{where}:{lineno}: denylist term #{number} (outside {FIXTURE_PREFIX})")
            if ALLOW_MARK not in line:
                for label, pattern in PATTERNS.items():
                    if pattern.search(line):
                        hits.append(f"{where}:{lineno}: {label}")
    return hits


def _tracked_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            files.append(Path(dirpath, name).relative_to(root).as_posix())
    return files


def scan_tree(root: Path, terms, fixture_ok) -> list[str]:
    files = _tracked_files(root)
    if files is None:
        files = _walk_files(root)
    hits = []
    for rel in sorted(files):
        if rel == LOCAL_FILE or Path(rel).suffix.lower() in BINARY_SUFFIXES:
            continue
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += scan_text(rel, text, terms, fixture_ok, in_fixtures=rel.startswith(FIXTURE_PREFIX))
    return hits


def scan_history(root: Path, terms, fixture_ok) -> list[str]:
    fmt = "%H%x00%an <%ae>%n%cn <%ce>%n%B%x01"
    out = subprocess.run(["git", "log", "--all", f"--format={fmt}"], cwd=root,
                         capture_output=True, check=True)
    hits = []
    for record in out.stdout.decode("utf-8", errors="replace").split("\x01"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x00")
        hits += scan_text(f"commit {sha[:10]}", body, terms, fixture_ok, in_fixtures=False)
    return hits


def main(argv: list[str]) -> int:
    history = "--history" in argv
    args = [a for a in argv if a != "--history"]
    root = Path(args[0] if args else ".").resolve()
    try:
        terms, fixture_ok = load_denylist(root)
    except DenylistError as err:
        print(f"scrub: {err}", file=sys.stderr)
        return 2
    hits = scan_tree(root, terms, fixture_ok)
    if history:
        hits += scan_history(root, terms, fixture_ok)
    for hit in hits:
        print(hit)
    if hits:
        print(f"scrub: {len(hits)} hit(s)", file=sys.stderr)
        return 1
    print(f"scrub: clean ({len(terms) + len(fixture_ok)} denylist terms, {len(PATTERNS)} patterns"
          f"{', history included' if history else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
