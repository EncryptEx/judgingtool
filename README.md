# Judging Tool (Project validator)

A hackathon project validator that checks whether all commits in a Git repository were made within the official weekend window (**Friday 18:00 → Sunday 23:59:59**). Designed for hackathon organizers to quickly flag suspicious submissions.

## Features

- Accepts a **GitHub URL** (auto-cloned) or a **local repo path**
- Detects commits outside the weekend window and explains why (pre/post)
- Shows **first & last commit** timestamps
- Lists all **unique committers**, with a warning if there are more than 4
- Provides a clear **VALID / SUSPICIOUS** verdict
- Clickable **GitHub commit links** for each flagged commit
- Available as both a **CLI tool** and a **Streamlit web app**

## Requirements

- Python 3.10+
- `git` installed and on your `PATH`
- `streamlit` (only for the web UI)

```bash
pip install streamlit
```

## Usage

### CLI

```bash
# Check a GitHub repo
python3 check_project.py https://github.com/user/repo

# Check a local repo
python3 check_project.py /path/to/repo

# Override timezone and weekend anchor date
python3 check_project.py https://github.com/user/repo --tz Europe/Madrid --weekend 2026-04-26

# Custom window: Saturday 09:00 → Sunday 20:00
python3 check_project.py https://github.com/user/repo \
  --start-day Saturday --start-time 09:00 \
  --end-day Sunday   --end-time 20:00
```

| Flag | Description | Default |
|------|-------------|---------|
| `--tz` | Timezone (e.g. `Europe/Madrid`) | system local |
| `--weekend` | Anchor date `YYYY-MM-DD` | today |
| `--start-day` | Weekday the window opens | `Friday` |
| `--start-time` | Time the window opens (`HH:MM`) | `18:00` |
| `--end-day` | Weekday the window closes | `Sunday` |
| `--end-time` | Time the window closes (`HH:MM`) | `23:59` |

Exit code `0` = valid, `2` = suspicious/invalid.

### Web UI

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser. Enter a GitHub URL or local path, pick the timezone and anchor date in the sidebar, and click **Check project**.

## Weekend Window

The window is always computed as:

| Start | End |
|-------|-----|
| Friday 18:00:00 (local time) | Sunday 23:59:59 (local time) |

The anchor date can be any day — the tool automatically finds the surrounding Friday-Sunday.
