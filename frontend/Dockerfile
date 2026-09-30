# syntax=docker/dockerfile:1.7
# ==============================================================================
# Frontend image: Vite production build served by nginx.
# VITE_API_URL is baked in at build time (the browser calls the API directly).
# ==============================================================================

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
ENV npm_config_fetch_retries=5 npm_config_fetch_retry_maxtimeout=120000
# Retry the whole install (ECONNRESET under parallel builds was observed); the cache mount keeps
# downloaded packages across builds, including after `docker compose down -v`.
RUN --mount=type=cache,target=/root/.npm \
    n=0; until npm ci --no-audit --no-fund; do n=$((n+1)); [ "$n" -ge 4 ] && exit 1; echo "npm ci retry $n"; sleep 15; done
COPY . .
ARG VITE_API_URL=http://localhost:8000/api/v1
ARG VITE_API_MODE=http
ENV VITE_API_URL=${VITE_API_URL} VITE_API_MODE=${VITE_API_MODE}
RUN npm run build

FROM nginx:1.27-alpine AS runner
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD wget -q --spider http://127.0.0.1/ || exit 1
