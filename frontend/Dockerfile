# syntax=docker/dockerfile:1.7
# Build stage: install deps + produce Next.js standalone output.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm install --legacy-peer-deps

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder
WORKDIR /app
# NEXT_PUBLIC_* vars MUST be present at build time for Next.js to inline them.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SESSION_COOKIE_PREFIX=nexus
ARG NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_GIT_SHA
ARG SENTRY_AUTH_TOKEN
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_SESSION_COOKIE_PREFIX=${NEXT_PUBLIC_SESSION_COOKIE_PREFIX}
ENV NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN}
ENV NEXT_PUBLIC_GIT_SHA=${NEXT_PUBLIC_GIT_SHA}
# SENTRY_AUTH_TOKEN is consumed by withSentryConfig at build time only.
# Not exported to runtime image (omitted from `runner` stage env block).
ENV SENTRY_AUTH_TOKEN=${SENTRY_AUTH_TOKEN}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN node -e "if (!/^[0-9a-f]{40}$/.test(process.env.NEXT_PUBLIC_GIT_SHA ?? '')) process.exit(1)"
RUN npm run build

# Runtime stage: minimal image with the standalone server.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
# Next.js standalone server jest gotowy w <1s. start-interval=2s sprawia, że
# kontener zostaje `healthy` ~2s po starcie (nie czeka pełnego start-period), więc
# Coolify przełącza Traefik na nowy kontener szybko i okno „no available server"
# przy deployu jest krótkie (~2s zamiast ~30s).
HEALTHCHECK --interval=15s --timeout=3s --retries=3 --start-period=20s --start-interval=2s \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null 2>&1 || exit 1
CMD ["node", "server.js"]
