# Fitness Tracker

Self-hosted workout and weight tracker. Designed for use on phone and PC over Tailscale.

## Features

- **Strength workouts** — 3-day rotation (Day A/B/C) with per-set rep, weight, and duration tracking
- **Warmup timer** — 5-minute countdown with exercise checklist
- **Workout timer** — elapsed time for the full session
- **Exercise timer** — full-screen countdown for timed exercises (planks, holds)
- **Custom activities** — log pickleball, bike rides, walks, etc.
- **Weight tracking** — log body weight with trend chart
- **Trends** — exercise progression charts over time
- **Calendar** — month view showing workout and activity history
- **Backup/restore** — full JSON export and import

## Setup

```bash
docker compose up -d
```

The app runs on port **8322**. Access it at `http://<hostname>:8322`.

## Data

All data is stored in a single SQLite file at `data/fitness.db`. This directory is volume-mounted, so data persists across container rebuilds.

To back up, either:
- Copy `data/fitness.db` directly
- Use the **Backup** button in the app to download a JSON export

## Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** Single HTML file, vanilla JavaScript, no external dependencies
- **Deployment:** Docker Compose
