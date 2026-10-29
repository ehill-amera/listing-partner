"""Tests for the check command's own wiring. No network, no key.

The check script is shell, so these tests do two things: they pin the exact
invocation the check must use, and they prove the mechanism end to end in a
throwaway git repo.
"""

import subprocess
from pathlib import Path

CHECK = Path(__file__).resolve().parent.parent / "scripts" / "check"
SCAN = Path(__file__).resolve().parent.parent / "scripts" / "banned_scan.sh"


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


def test_check_reads_private_banned_list_not_local():
    text = CHECK.read_text()
    assert "../.listing-partner-private/banned-strings.txt" in SCAN.read_text()
    assert "banned_scan.sh" in text, "the check must run the banned-strings scan"
    assert "local/banned-strings.txt" not in text, (
        "the old in-repo list path must be gone from the check"
    )


def test_banned_scan_reports_entry_numbers_never_strings():
    text = SCAN.read_text()
    assert "entry #" in text, "hits report the list entry's number"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo ") or stripped.startswith("say "):
            assert "pat" not in line, f"a printed line must never carry the pattern: {line!r}"
    assert "[$pat]" not in text and '"$pat"' not in CHECK.read_text()


def _scaffold_scan_repo(root: Path, private_entries: str, files: dict) -> Path:
    """A throwaway repo plus a fake private list beside it.

    Layout: <root>/repo is the repo, <root>/.listing-partner-private/ holds
    the fake list, so the scan's fixed ../ path resolves inside tmp.
    """
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _run("init", "-q", cwd=repo)
    _run("config", "user.email", "test@example.com", cwd=repo)
    _run("config", "user.name", "Test", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.write_text(content)
        _run("add", name, cwd=repo)
    private = root / ".listing-partner-private"
    private.mkdir(parents=True, exist_ok=True)
    (private / "banned-strings.txt").write_text(private_entries)
    return repo


def test_banned_scan_reports_entry_number_and_hides_the_string(tmp_path):
    repo = _scaffold_scan_repo(
        tmp_path,
        "# comment line\n\nfakestreet-xyz-1\nfakestreet-xyz-2\n",
        {"notes.txt": "clean line\nmentions fakestreet-xyz-2 here\n"},
    )
    proc = subprocess.run(["sh", str(SCAN), str(repo)], capture_output=True, text=True, check=False)
    assert proc.returncode == 1, "a hit must fail"
    assert "entry #2" in proc.stdout, "the second active entry fired"
    assert "notes.txt" in proc.stdout, "the hit names the file"
    combined = proc.stdout + proc.stderr
    assert "fakestreet-xyz-1" not in combined, "a non-matching entry stays secret"
    assert "fakestreet-xyz-2" not in combined, "even the matching string stays secret"


def test_banned_scan_refuses_missing_or_empty_list(tmp_path):
    repo = _scaffold_scan_repo(tmp_path, "someentry\n", {"notes.txt": "clean\n"})
    (tmp_path / ".listing-partner-private" / "banned-strings.txt").unlink()
    proc = subprocess.run(["sh", str(SCAN), str(repo)], capture_output=True, text=True, check=False)
    assert proc.returncode == 1
    assert "MISSING OR EMPTY" in (proc.stdout + proc.stderr)
    (tmp_path / ".listing-partner-private" / "banned-strings.txt").write_text("")
    proc = subprocess.run(["sh", str(SCAN), str(repo)], capture_output=True, text=True, check=False)
    assert proc.returncode == 1


def test_banned_scan_passes_clean_tree(tmp_path):
    repo = _scaffold_scan_repo(tmp_path, "fakestreet-xyz-1\n", {"notes.txt": "nothing to see\n"})
    proc = subprocess.run(["sh", str(SCAN), str(repo)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


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
