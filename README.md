# Luba Scheduler

A Home Assistant integration that schedules and supervises a Mammotion Luba robot mower. It sits on top of the [Mammotion integration](https://github.com/mikey0000/Mammotion-HA):
- It decides when growing and weather conditions allow a mow.
- It asks before starting and verifies that the job really started.
- It stops the mower when the weather turns or the light fails.

**Status: development scaffold.** This build installs through HACS, but its setup flow aborts, so it cannot be configured and does nothing. Do not install it expecting a working integration.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

On Windows, run the tests in Docker, because the Home Assistant test plugin needs `fcntl`:

```bash
bash tools/test.sh -q
```

### Scrub gate

The repository is private for now but is kept publishable. CI's `scrub` job runs `tools/scrub_check.py --history` on every push and pull request, and fails when either of these is found:
- **Exact terms from the denylist.** The denylist lives in the `SCRUB_DENYLIST` repository secret, never in the tree. Locally the checker reads the gitignored file `.scrub-denylist`.
- **Generic install-specific patterns:** long integers (area hashes), 32-hex registry IDs and high-precision coordinates.

Both the tracked files and every commit's author and message are scanned. See `docs/RELEASING.md` → *Going public*.

Releases: `docs/RELEASING.md`.
