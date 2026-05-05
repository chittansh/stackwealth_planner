---
name: fly-deploy
description: Deploy to Fly.io. Argument can be "backend", "frontend", or "both" (default = both). Runs typecheck on touched packages first, deploys, then health-checks the live URL. Use after committing changes.
---

# fly-deploy — Stackwealth Planner

Deploys backend and/or frontend to Fly.io. **You MUST run from the repo root** (`stackwealth_planner/`).

## Argument

The skill arg controls scope:
- `backend` — backend only
- `frontend` — frontend only
- `both` (default) — backend first, then frontend
- `<commit-sha>` — deploy whatever is at that sha (informational only — Fly deploys the working tree state)

## Live targets

- **Backend**: `https://stackwealth-backend.fly.dev` (Fly app `stackwealth-backend`, region `bom`)
- **Frontend**: `https://stackwealth-frontend.fly.dev` (Fly app `stackwealth-frontend`)

## Procedure

### Pre-flight

1. Confirm `fly` CLI is installed and logged in:
   ```bash
   fly auth whoami
   ```
   If not authenticated, ask the user to run `fly auth login` and stop.

2. Check the apps exist (`fly apps list | grep stackwealth-`). If a target app is missing, ask before proceeding.

3. **Typecheck only the package(s) being deployed**. Don't block on pre-existing errors that aren't in the changed files — but warn loudly if the diff introduces NEW errors:
   ```bash
   # Backend
   cd backend && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -E '<changed-files-pattern>' | head -20
   # Frontend
   cd frontend && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -E '<changed-files-pattern>' | head -20
   ```

4. Sanity check `git status` — note any unstaged changes (these WILL be deployed since Fly uses the working tree, not HEAD).

### Backend deploy

```bash
cd <repo-root>
fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile --remote-only
```

Use `--remote-only` always — Fly's depot builder is faster than the local Docker daemon and doesn't require Docker installed locally.

After it completes, health-check:

```bash
curl -sS -m 10 https://stackwealth-backend.fly.dev/health
# → {"ok":true,"ts":"..."}
```

### Frontend deploy

`NEXT_PUBLIC_BACKEND_URL` is **baked at build time** into the client bundle. ALWAYS pass both build args:

```bash
cd <repo-root>
fly deploy --config frontend/fly.toml --dockerfile frontend/Dockerfile --remote-only \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://stackwealth-backend.fly.dev \
  --build-arg BACKEND_URL=https://stackwealth-backend.fly.dev
```

Health-check:

```bash
curl -sS -m 30 -L -o /dev/null -w 'http=%{http_code}\n' https://stackwealth-frontend.fly.dev/
# → http=200
```

### Both

Backend first (in case the frontend depends on a new endpoint), then frontend.

If backend deploy fails, **stop** and report the error before touching the frontend.

### Tail logs (optional)

If the user wants to watch logs after deploy:

```bash
fly logs --app stackwealth-backend
fly logs --app stackwealth-frontend
```

## What can go wrong (and the fix)

| Symptom | Cause | Fix |
|---|---|---|
| Backend deploy succeeds, but `/health` times out | Machine still booting (cold-start ~10s) | Wait 15s and re-curl. If still failing, `fly logs --app stackwealth-backend` to see the boot error. |
| Frontend deploy fails on health check, but logs show "Ready in Ns" | `next start` takes longer than the 30s grace period | Already fixed — health check points at `/advisor/clients` not `/`. If still failing, bump `grace_period` in `frontend/fly.toml` |
| API calls work in dev but fail in prod with CORS error | `FRONTEND_ORIGIN` secret on backend doesn't match the deployed frontend URL | `fly secrets set --app stackwealth-backend FRONTEND_ORIGIN=https://<frontend>.fly.dev` |
| Frontend deployed but it's still hitting localhost | Missed one or both build args | Re-deploy with both `NEXT_PUBLIC_BACKEND_URL` and `BACKEND_URL` |
| Anthropic 401 / OpenAI 401 in chat | Stale or rotated key | `fly secrets set --app stackwealth-backend ANTHROPIC_API_KEY=...` |
| Data resets after a few minutes | `auto_stop_machines = "stop"` + no `DATABASE_URL` → in-memory store wiped on cold start | Either set DATABASE_URL or set `auto_stop_machines = false` in fly.toml |
| `pnpm-lock.yaml` mismatch in build | Lockfile drifted | Either run `pnpm install` to regenerate, OR the Dockerfile's fallback `|| pnpm install --filter ...` will recover |

## Output

After a successful deploy, summarize for the user:

```
✓ Backend deployed (image: stackwealth-backend:deployment-XYZ)
  https://stackwealth-backend.fly.dev/health → {"ok":true}

✓ Frontend deployed (image: stackwealth-frontend:deployment-ABC)
  https://stackwealth-frontend.fly.dev → http=200 (1.2s)

What changed (from git log -1):
  <commit subject>
```

If only one was deployed, only show that section.

If anything failed, **don't claim success** — show the error output and a one-line diagnosis from the table above.
