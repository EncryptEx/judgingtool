#!/usr/bin/env python3
"""
app.py — Streamlit UI for check_project.py
Run with:  streamlit run app.py
"""

import shutil
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

# Re-use all core logic from the CLI module
from check_project import (
    is_github_url,
    normalise_github_url,
    clone_repo,
    get_weekend_window,
    git_commits,
    local_now,
)

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="HackUPC Judging Tool",
    page_icon="🔍",
    layout="centered",
)

st.title("🔍 Project Validity Checker")
st.caption("Flags commits made outside the hackathon weekend window (Fri 18:00 → Sun 23:59).")

# ── sidebar: settings ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    tz_name = st.text_input("Timezone", value="Europe/Madrid",
                             help="IANA timezone name, e.g. Europe/Madrid, UTC")
    override_date = st.date_input(
        "Weekend anchor date",
        value=date.today(),
        help="Any date — the script picks the surrounding Fri-Sun window.",
    )

# ── main input ────────────────────────────────────────────────────────────────
repo_input = st.text_input(
    "GitHub URL or local repo path",
    placeholder="https://github.com/user/repo",
)

check_btn = st.button("Check project", type="primary", disabled=not repo_input.strip())

if not check_btn:
    st.stop()

# ── resolve timezone ──────────────────────────────────────────────────────────
try:
    tz = ZoneInfo(tz_name) if tz_name.strip() else ZoneInfo("localtime")
except (ZoneInfoNotFoundError, KeyError):
    st.error(f"Unknown timezone '{tz_name}'. Falling back to UTC.")
    tz = timezone.utc

anchor = datetime.combine(override_date, time(12, 0), tzinfo=tz)
window_start, window_end = get_weekend_window(anchor)

ts_fmt = "%A %Y-%m-%d %H:%M:%S %Z"
st.info(
    f"**Weekend window**  \n"
    f"🟢 From: `{window_start.strftime(ts_fmt)}`  \n"
    f"🔴 To:   `{window_end.strftime(ts_fmt)}`"
)

# ── clone / locate repo ───────────────────────────────────────────────────────
tmp_dir = None
github_base_url = None

repo_input = repo_input.strip()

try:
    if is_github_url(repo_input):
        url = normalise_github_url(repo_input)
        github_base_url = url.removesuffix(".git")
        with st.spinner(f"Cloning `{url}` …"):
            tmp_dir = clone_repo(url)
        repo_path = tmp_dir
    else:
        repo_path = repo_input

    # ── fetch & classify commits ──────────────────────────────────────────────
    with st.spinner("Analysing commits …"):
        commits = git_commits(repo_path)

finally:
    # cleanup happens after we've used repo_path below
    pass

if not commits:
    st.warning("No commits found in this repository.")
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    st.stop()

inside, outside, unknown = [], [], []
for c in commits:
    if c["timestamp"] is None:
        unknown.append(c)
    elif window_start <= c["timestamp"] <= window_end:
        inside.append(c)
    else:
        outside.append(c)

if tmp_dir:
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ── summary metrics ───────────────────────────────────────────────────────────
total = len(commits)
first_ts = commits[-1]["timestamp"]   # git log is newest-first
last_ts  = commits[0]["timestamp"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total commits", total)
col2.metric("✅ Inside window", len(inside))
col3.metric("🚩 Outside window", len(outside))
col4.metric("❓ Unknown ts", len(unknown))

st.markdown("---")
fc1, fc2 = st.columns(2)
fc1.markdown(f"**First commit**  \n`{first_ts.strftime(ts_fmt) if first_ts else 'unknown'}`")
fc2.markdown(f"**Last commit**  \n`{last_ts.strftime(ts_fmt) if last_ts else 'unknown'}`")

# ── committers ────────────────────────────────────────────────────────────────
seen: dict[str, None] = {}
for c in reversed(commits):
    seen[c["author"]] = None
committers = list(seen.keys())
n = len(committers)

st.markdown("---")
warn = " ⚠️  more than 4!" if n > 4 else ""
st.markdown(f"**Committers ({n}){warn}**")
for email in committers:
    st.markdown(f"- `{email}`")

# ── verdict ───────────────────────────────────────────────────────────────────
st.markdown("---")
if not outside and not unknown:
    st.success("## ✅ VALID — all commits are within the weekend window.")
else:
    st.error("## 🚨 SUSPICIOUS / INVALID — commits found outside the weekend window.")

# ── flagged commits table ─────────────────────────────────────────────────────
if outside:
    st.markdown("### 🚩 Commits outside the window")
    for c in outside:
        ts_str = c["timestamp"].strftime(ts_fmt)
        if c["timestamp"] < window_start:
            reason = "⏮ before Friday 18:00 (pre-weekend)"
        else:
            reason = "⏭ after Sunday 23:59 (post-weekend)"

        full_hash = c["full_hash"]
        if github_base_url:
            link = f"{github_base_url}/commit/{full_hash}"
            link_md = f"[{c['hash']}]({link})"
        else:
            link_md = f"`{c['hash']}`"

        with st.container(border=True):
            st.markdown(f"**{link_md}** — {ts_str}")
            st.markdown(f"👤 `{c['author']}`  \n💬 {c['subject'][:120]}  \n🏷 {reason}")

if unknown:
    st.markdown("### ❓ Commits with unparseable timestamps")
    for c in unknown:
        st.markdown(f"- `{c['hash']}` — `{c['author']}` — {c['subject'][:120]}")
