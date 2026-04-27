#!/usr/bin/env python3
"""
check_project.py — Validates that all commits in a Git project fall within
the current weekend window (Friday 18:00 → Sunday 23:59:59 local time).

Usage:
    python check_project.py <path/to/repo|github_url> [--weekend YYYY-MM-DD] [--tz TIMEZONE]

    repo           Local path OR a GitHub URL
                   (e.g. https://github.com/user/repo or github.com/user/repo)
    --weekend      Anchor date (any day) to pick the surrounding weekend.
                   Defaults to today.
    --tz           Timezone for the window (e.g. Europe/Madrid). Defaults to
                   system local time.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ── helpers ──────────────────────────────────────────────────────────────────

_GITHUB_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/[\w.\-]+/[\w.\-]+"
)

def is_github_url(value: str) -> bool:
    return bool(_GITHUB_PATTERN.match(value))


def normalise_github_url(value: str) -> str:
    """Ensure the URL starts with https:// and ends without .git."""
    if not value.startswith("http"):
        value = "https://" + value
    # strip trailing slashes / .git
    value = value.rstrip("/")
    if not value.endswith(".git"):
        value += ".git"
    return value


def clone_repo(url: str) -> str:
    """Clone *url* into a temporary directory and return its path."""
    tmp = tempfile.mkdtemp(prefix="judgingtool_")
    print(f"  Cloning {url} …")
    try:
        subprocess.run(
            ["git", "clone", "--quiet", url, tmp],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"[ERROR] git clone failed:\n{exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return tmp


def get_weekend_window(anchor: datetime) -> tuple[datetime, datetime]:
    """
    Return (friday_6pm, sunday_midnight) for the weekend that contains
    or most recently preceded *anchor*.

    Weekend = Friday 18:00:00 (local) → Sunday 23:59:59 (local).
    """
    tz = anchor.tzinfo

    # weekday(): Monday=0 … Sunday=6  →  Friday=4
    days_since_friday = (anchor.weekday() - 4) % 7
    friday = anchor.date() - timedelta(days=days_since_friday)
    sunday = friday + timedelta(days=2)

    start = datetime.combine(friday, time(18, 0, 0), tzinfo=tz)
    end   = datetime.combine(sunday, time(23, 59, 59), tzinfo=tz)
    return start, end


def git_commits(repo_path: str) -> list[dict]:
    """Return a list of {hash, author, timestamp, subject} for every commit."""
    fmt = "%H\x1f%ae\x1f%aI\x1f%s"          # \x1f = ASCII unit-separator
    try:
        result = subprocess.run(
            ["git", "log", "--all", f"--pretty=format:{fmt}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] git log failed: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("[ERROR] 'git' executable not found.", file=sys.stderr)
        sys.exit(1)

    commits = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        sha, author, iso_ts, subject = parts
        try:
            ts = datetime.fromisoformat(iso_ts)   # already tz-aware (git ISO 8601)
        except ValueError:
            ts = None
        commits.append({"hash": sha[:10], "full_hash": sha,
                         "author": author,
                         "timestamp": ts, "subject": subject})
    return commits


def local_now(tz_name: str | None) -> datetime:
    try:
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("localtime")
    except (ZoneInfoNotFoundError, KeyError):
        tz = timezone.utc
    return datetime.now(tz=tz)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check that all project commits fall within the weekend window."
    )
    parser.add_argument("repo", nargs="?", default=".",
                        help="Local path OR GitHub URL to the repository (default: .)")
    parser.add_argument("--weekend", metavar="YYYY-MM-DD", default=None,
                        help="Anchor date to select the weekend (default: today)")
    parser.add_argument("--tz", metavar="TIMEZONE", default=None,
                        help="Timezone name for the window, e.g. Europe/Madrid "
                             "(default: system local time)")
    args = parser.parse_args()

    # ── resolve repo path (clone if GitHub URL) ───────────────────────────────
    tmp_dir = None
    repo_label = args.repo

    github_base_url = None
    if is_github_url(args.repo):
        url = normalise_github_url(args.repo)
        tmp_dir = clone_repo(url)
        repo_path = tmp_dir
        # base URL for commit links: https://github.com/user/repo
        github_base_url = url.removesuffix(".git")
    else:
        repo_path = args.repo

    try:
        _run_check(repo_path, repo_label, args, github_base_url)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_check(repo_path: str, repo_label: str, args: argparse.Namespace,
               github_base_url: str | None = None) -> None:
    # ── determine the weekend window ─────────────────────────────────────────
    now = local_now(args.tz)

    if args.weekend:
        try:
            anchor_date = datetime.strptime(args.weekend, "%Y-%m-%d").date()
            anchor = datetime.combine(anchor_date, time(12, 0), tzinfo=now.tzinfo)
        except ValueError:
            print("[ERROR] --weekend must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        anchor = now

    window_start, window_end = get_weekend_window(anchor)

    print("=" * 60)
    print(f"  Repo   : {repo_label}")
    print(f"  Weekend window")
    print(f"  From : {window_start.strftime('%A %Y-%m-%d %H:%M:%S %Z')}")
    print(f"  To   : {window_end.strftime('%A %Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 60)

    # ── fetch commits ─────────────────────────────────────────────────────────
    commits = git_commits(repo_path)

    if not commits:
        print("\n[INFO] No commits found in this repository.")
        return

    # ── classify ──────────────────────────────────────────────────────────────
    inside:  list[dict] = []
    outside: list[dict] = []
    unknown: list[dict] = []

    for c in commits:
        if c["timestamp"] is None:
            unknown.append(c)
        elif window_start <= c["timestamp"] <= window_end:
            inside.append(c)
        else:
            outside.append(c)

    total   = len(commits)
    verdict = "VALID" if not outside and not unknown else "SUSPICIOUS / INVALID"
    colour  = "\033[32m" if verdict == "VALID" else "\033[31m"
    reset   = "\033[0m"

    # git log returns newest-first
    ts_fmt = "%A %Y-%m-%d %H:%M:%S %Z"
    first_ts = commits[-1]["timestamp"]   # oldest
    last_ts  = commits[0]["timestamp"]    # newest
    first_str = first_ts.strftime(ts_fmt) if first_ts else "unknown"
    last_str  = last_ts.strftime(ts_fmt)  if last_ts  else "unknown"

    # unique committers (preserve insertion order → chronological first appearance)
    seen: dict[str, None] = {}
    for c in reversed(commits):   # oldest first for a natural listing order
        seen[c["author"]] = None
    committers = list(seen.keys())
    n_committers = len(committers)
    comm_colour = "\033[33m" if n_committers > 4 else ""   # yellow warning

    print(f"\n  Total commits : {total}")
    print(f"  First commit  : {first_str}")
    print(f"  Last commit   : {last_str}")
    print(f"  Inside window : {len(inside)}")
    print(f"  Outside window: {len(outside)}")
    if unknown:
        print(f"  Unknown ts    : {len(unknown)}")
    print(f"  Committers    : {comm_colour}{n_committers}{reset}"
          + (" ⚠  (>4)" if n_committers > 4 else ""))
    for email in committers:
        print(f"                  • {email}")

    print(f"\n  Verdict: {colour}{verdict}{reset}\n")

    # ── report outside commits ────────────────────────────────────────────────
    if outside:
        print("─" * 60)
        print("  COMMITS OUTSIDE THE WEEKEND WINDOW:")
        print("─" * 60)
        for c in outside:
            ts_str = c["timestamp"].strftime("%A %Y-%m-%d %H:%M:%S %Z")
            if c["timestamp"] < window_start:
                reason = "before Friday 18:00 (pre-weekend)"
            elif c["timestamp"] > window_end:
                reason = "after Sunday 23:59 (post-weekend)"
            else:
                reason = "outside window"
            full_hash = c["full_hash"]
            link = (f"{github_base_url}/commit/{full_hash}"
                    if github_base_url else full_hash)
            print(f"  [{c['hash']}] {ts_str}")
            print(f"           by   : {c['author']}")
            print(f"           msg  : {c['subject'][:72]}")
            print(f"           flag : {reason}")
            print(f"           link : {link}")
            print()

    if unknown:
        print("─" * 60)
        print("  COMMITS WITH UNPARSEABLE TIMESTAMPS:")
        print("─" * 60)
        for c in unknown:
            print(f"  [{c['hash']}] {c['author']} — {c['subject'][:72]}")
        print()

    if verdict != "VALID":
        sys.exit(2)     # non-zero exit so CI/scripts can detect failure


if __name__ == "__main__":
    main()
