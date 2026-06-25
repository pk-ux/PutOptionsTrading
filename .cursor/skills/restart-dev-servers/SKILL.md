---
name: restart-dev-servers
description: Restart, start, or stop the local development servers for the Put Options Trading app (FastAPI backend + Vite frontend). Always kills any existing uvicorn/vite instances first, then starts both in the background and verifies backend health. Use when the user asks to start, run, restart, or stop the app, backend, or frontend, or after backend code changes that require a reload.
---

# Restart Dev Servers

Starts the Put Options Trading app locally: the FastAPI backend (uvicorn, port
8000) and the Vite frontend (port 5173). Existing instances are always killed
first so this is safe to run repeatedly.

## Usage

Run the script (it returns once both are started; servers keep running in the
background):

```bash
.cursor/skills/restart-dev-servers/scripts/restart-dev.sh
```

Stop everything without restarting:

```bash
.cursor/skills/restart-dev-servers/scripts/restart-dev.sh stop
```

Override ports if needed:

```bash
BACKEND_PORT=8001 FRONTEND_PORT=5174 .cursor/skills/restart-dev-servers/scripts/restart-dev.sh
```

## What the script does

1. Kills existing `uvicorn app.main:app` and `vite` processes, and frees the
   backend/frontend ports (backup `lsof` kill for orphans).
2. Activates a virtualenv (`.venv`, which has the full app deps; falls back to `backend/venv`).
3. Loads `backend/.env` so API keys and `DATABASE_URL` are set.
4. Starts the backend with `--reload`, then polls `/health` (up to ~20s).
5. Installs frontend deps if `node_modules` is missing, then starts Vite.
6. Logs to `.dev-logs/backend.log` and `.dev-logs/frontend.log`.

## Notes for the agent

- The script backgrounds both servers with `nohup`; do NOT block waiting on it.
  After running, confirm success by reading `.dev-logs/backend.log` and
  `.dev-logs/frontend.log` if needed.
- If the backend health check fails, read `.dev-logs/backend.log` for the error
  (commonly a missing dependency or a bad `.env` value).
- URLs: frontend http://localhost:5173, backend http://localhost:8000, API docs
  http://localhost:8000/docs.
