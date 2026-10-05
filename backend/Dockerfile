# syntax=docker/dockerfile:1

# ---- Stage 1: build the virtual environment with all dependencies --------------------------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt \
    && /opt/venv/bin/python -m pip uninstall -y pip

# ---- Stage 2: small runtime image, no build tooling, non-root ------------------------------
FROM python:3.12-slim AS runtime
ARG APP_VERSION=1.0.0
ARG GIT_SHA=dev
LABEL org.opencontainers.image.title="campusslot-backend" \
      org.opencontainers.image.description="CampusSlot FastAPI backend" \
      org.opencontainers.image.source="https://github.com/Ujjwaljain16/campusslot" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

# Pull in the latest security fixes for the base image, then create the unprivileged user.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh ./
RUN chmod 0555 docker-entrypoint.sh

# A numeric UID lets Kubernetes verify "runAsNonRoot" without having to resolve a name.
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

ENTRYPOINT ["./docker-entrypoint.sh"]
