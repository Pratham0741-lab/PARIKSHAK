# ==============================================================================
# Frontend image: Vite production build served by nginx.
# VITE_API_URL is baked in at build time (the browser calls the API directly).
# ==============================================================================

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=http://localhost:8000/api/v1
ARG VITE_API_MODE=http
ENV VITE_API_URL=${VITE_API_URL} VITE_API_MODE=${VITE_API_MODE}
RUN npm run build

FROM nginx:1.27-alpine AS runner
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD wget -q --spider http://localhost/ || exit 1
