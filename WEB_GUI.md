# Web GUI

This project includes a LAN-oriented web interface for running Instaloader download jobs asynchronously.

## Stack

- Backend: FastAPI, SQLite, background worker pool
- Frontend: React, TypeScript, Vite
- Downloader: the local `instaloader` Python package

## Run

Install and start both services with:

```powershell
.\start_web.ps1
```

Or run them manually:

```powershell
py -m pip install -r web_backend\requirements.txt
py -m web_backend.run
```

```powershell
cd web_frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Other devices on the same LAN can use the host machine IP with port `5173`.

## Behavior

- Tasks are created through the web UI and run in the backend.
- Up to 2 tasks run at the same time; additional tasks remain queued.
- Task history and events are stored in `web_data/app.sqlite3`.
- Downloaded files are stored under `web_data/downloads`.
- Files can be downloaded from the web UI.
- Images and videos can be previewed from the selected task detail panel or the file center.
- The preview API returns the latest media recursively with `GET /api/media?task_id=1` or `GET /api/media?path=task-1`.
- Media files are rendered inline through `GET /api/media/view?path=...`; all paths are resolved under the configured download root.
- Shared Instagram session state is stored under `web_data/sessions`.
- Logged-in targets are rejected before enqueueing if no valid shared session is configured.
- Network, timeout, and rate-limit errors are classified and retried with delayed backoff.
- Rate-limit errors activate a cooldown window and temporarily reduce effective concurrency.
- `/api/health` reports database writability, download-directory writability, free disk space, task counts, session state, and cooldown state.

## Notes

- The web UI currently has no login system. Use it only on a trusted LAN and do not expose it to the public internet.
- Running task cancellation is cooperative. Queued tasks cancel immediately; running tasks are marked for cancellation and stop after the current Instaloader call returns.
- Browser cookie import requires `browser-cookie3`. If installation from the current Python package mirror fails, manual cookie text import remains available.
