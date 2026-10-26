"""Tests for the check command's own wiring. No network, no key.

The check script is shell, so these tests do two things: they pin the exact
invocation the check must use, and they prove the mechanism end to end in a
throwaway git repo.
"""

import subprocess
from pathlib import Path

CHECK = Path(__file__).resolve().parent.parent / "scripts" / "check"


def _run(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _scaffold_repo(root: Path) -> Path:
    """A repo where inputs/ is ignored and a file under it is force-added."""
    root.mkdir(parents=True, exist_ok=True)
    _run("init", "-q", cwd=root)
    _run("config", "user.email", "test@example.com", cwd=root)
    _run("config", "user.name", "Test", cwd=root)
    (root / ".gitignore").write_text("inputs/\n")
    sneak = root / "inputs" / "sneak.txt"
    sneak.parent.mkdir(parents=True, exist_ok=True)
    sneak.write_text("must never be tracked\n")
    _run("add", ".gitignore", cwd=root)
    _run("add", "-f", "inputs/sneak.txt", cwd=root)
    tracked = _run("ls-files", cwd=root).stdout.split()
    assert "inputs/sneak.txt" in tracked, "the file must be tracked for the test"
    return root


def test_check_scans_tracked_files_without_the_index(tmp_path):
    text = CHECK.read_text()
    assert "check-ignore --no-index" in text, (
        "plain check-ignore skips tracked files, so the scan can never fail"
    )


def test_check_scans_file_names_for_emails():
    text = CHECK.read_text()
    assert "possible email address in tracked file names" in text, (
        "the check must grep tracked file names for emails, not just file contents"
    )


def test_check_scans_file_names_for_phones():
    text = CHECK.read_text()
    assert "possible phone number in tracked file names" in text, (
        "the check must grep tracked file names for phones, not just file contents"
    )


def test_force_added_file_under_inputs_is_caught(tmp_path):
    root = _scaffold_repo(tmp_path / "repo")
    # The check's algorithm with the flag: every tracked file, patterns only.
    flagged = [
        f
        for f in _run("ls-files", cwd=root).stdout.split()
        if _run("check-ignore", "--no-index", "-q", f, cwd=root).returncode == 0
    ]
    assert flagged == ["inputs/sneak.txt"], "the force-added file must be flagged"
    # And why the flag matters: without it git trusts the index, so the old
    # form reports the same file as not ignored and the check passes silently.
    missed = [
        f
        for f in _run("ls-files", cwd=root).stdout.split()
        if _run("check-ignore", "-q", f, cwd=root).returncode == 0
    ]
    assert missed == [], "without --no-index the scan can never fail"
