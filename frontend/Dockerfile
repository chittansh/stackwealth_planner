# Frontend image — Next.js 15 production server.
# Build context = REPO ROOT (so we can pull in the workspace siblings).

FROM node:20-alpine AS base
RUN npm i -g pnpm@9.12.0 && apk add --no-cache tini
WORKDIR /app

# ── deps ─────────────────────────────────────────────────────────────────
FROM base AS deps
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* ./
COPY frontend/package.json frontend/
COPY shared/package.json shared/
RUN pnpm install --filter frontend... --frozen-lockfile || pnpm install --filter frontend...

# ── build ────────────────────────────────────────────────────────────────
FROM deps AS build
# NEXT_PUBLIC_* values are baked into the client bundle at build time —
# pass via `--build-arg NEXT_PUBLIC_BACKEND_URL=https://your-backend.fly.dev`.
ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:4000
ARG BACKEND_URL=http://localhost:4000
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
ENV BACKEND_URL=$BACKEND_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY shared/ shared/
COPY frontend/ frontend/
RUN pnpm --filter frontend build

# ── runtime ──────────────────────────────────────────────────────────────
FROM base AS runtime
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/frontend/node_modules /app/frontend/node_modules
COPY --from=build /app/frontend/.next /app/frontend/.next
COPY --from=build /app/frontend/public /app/frontend/public
COPY --from=build /app/frontend/package.json /app/frontend/package.json
COPY --from=build /app/frontend/next.config.ts /app/frontend/next.config.ts
COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/pnpm-workspace.yaml /app/pnpm-workspace.yaml

WORKDIR /app/frontend
EXPOSE 3000
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["pnpm", "exec", "next", "start", "-p", "3000", "-H", "0.0.0.0"]
