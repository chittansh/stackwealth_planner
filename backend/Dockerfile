# Backend image — Hono server on Node 20.
# Build context = REPO ROOT (so we can pull in workspace siblings).

FROM node:20-alpine AS base
RUN npm i -g pnpm@9.12.0 && apk add --no-cache tini
WORKDIR /app

# ── deps ─────────────────────────────────────────────────────────────────
FROM base AS deps
ENV PUPPETEER_SKIP_DOWNLOAD=true
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY backend/package.json backend/
COPY frontend/package.json frontend/
COPY shared/package.json shared/
RUN pnpm install --filter backend... --frozen-lockfile || pnpm install --filter backend...

# ── runtime ──────────────────────────────────────────────────────────────
FROM deps AS runtime
ENV NODE_ENV=production
ENV PORT=4000
COPY shared/ shared/
COPY backend/ backend/

WORKDIR /app/backend
EXPOSE 4000

# Run TypeScript directly via tsx — keeps the workspace path-aliased import
# of `../../shared/types/plan-state.js` resolving without a separate build
# step for the shared package.
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["pnpm", "exec", "tsx", "src/index.ts"]
