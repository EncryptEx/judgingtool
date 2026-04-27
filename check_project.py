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


# weekday index: Monday=0 … Sunday=6
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]


def get_weekend_window(
    anchor: datetime,
    start_weekday: int = 4,       # Friday
    start_hour: int = 18,
    start_minute: int = 0,
    end_weekday: int = 6,         # Sunday
    end_hour: int = 23,
    end_minute: int = 59,
) -> tuple[datetime, datetime]:
    """
    Return (window_start, window_end) for the weekend that contains
    or most recently preceded *anchor*.

    Default: Friday 18:00 → Sunday 23:59:59 (local time).
    All weekday args use Python convention: Monday=0 … Sunday=6.
    """
    tz = anchor.tzinfo

    days_since_start = (anchor.weekday() - start_weekday) % 7
    start_date = anchor.date() - timedelta(days=days_since_start)
    # end_weekday must be >= start_weekday within the same week
    days_to_end = (end_weekday - start_weekday) % 7
    end_date = start_date + timedelta(days=days_to_end)

    start = datetime.combine(start_date, time(start_hour, start_minute, 0), tzinfo=tz)
    end   = datetime.combine(end_date,   time(end_hour,   end_minute,  59), tzinfo=tz)
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
    parser.add_argument("--start-day", metavar="DAY", default="Friday",
                        help="Weekday the window opens (default: Friday)")
    parser.add_argument("--start-time", metavar="HH:MM", default="18:00",
                        help="Time the window opens on start day (default: 18:00)")
    parser.add_argument("--end-day", metavar="DAY", default="Sunday",
                        help="Weekday the window closes (default: Sunday)")
    parser.add_argument("--end-time", metavar="HH:MM", default="23:59",
                        help="Time the window closes on end day (default: 23:59)")
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

    def _parse_day(name: str) -> int:
        name = name.strip().title()
        if name not in WEEKDAY_NAMES:
            print(f"[ERROR] Unknown day '{name}'. Use e.g. Friday, Saturday, Sunday.",
                  file=sys.stderr)
            sys.exit(1)
        return WEEKDAY_NAMES.index(name)

    def _parse_hhmm(s: str) -> tuple[int, int]:
        try:
            h, m = s.strip().split(":")
            return int(h), int(m)
        except ValueError:
            print(f"[ERROR] Time '{s}' must be HH:MM.", file=sys.stderr)
            sys.exit(1)

    start_wd = _parse_day(args.start_day)
    end_wd   = _parse_day(args.end_day)
    start_h, start_m = _parse_hhmm(args.start_time)
    end_h,   end_m   = _parse_hhmm(args.end_time)

    window_start, window_end = get_weekend_window(
        anchor,
        start_weekday=start_wd, start_hour=start_h, start_minute=start_m,
        end_weekday=end_wd,     end_hour=end_h,     end_minute=end_m,
    )

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
