# syntax=docker/dockerfile:1

# ---- Stage 1: build the static site with Node ---------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Stage 2: serve the static files with unprivileged nginx -----------------------------
# Only the compiled dist/ folder reaches this stage, so Node and node_modules are not in the
# final image. The "unprivileged" nginx variant runs as a non-root user and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.30-alpine AS runtime
ARG GIT_SHA=dev
LABEL org.opencontainers.image.title="campusslot-frontend" \
      org.opencontainers.image.description="CampusSlot React frontend served by nginx" \
      org.opencontainers.image.source="https://github.com/Ujjwaljain16/campusslot" \
      org.opencontainers.image.revision="${GIT_SHA}"

USER root
RUN apk upgrade --no-cache
USER 101

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Defaults suit Docker Compose; Kubernetes overrides BACKEND_HOST with the backend Service name.
ENV BACKEND_HOST=backend \
    BACKEND_PORT=8000

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
