#!/bin/sh
# Container entrypoint for the CampusSlot API.
#
# Docker Compose sets RUN_MIGRATIONS=true so one container applies the schema before serving.
# Kubernetes leaves it unset and runs migrations once, in a Helm hook Job, so that two replicas
# never try to migrate at the same time.
set -eu

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "Applying database migrations"
    attempt=0
    until alembic upgrade head; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 15 ]; then
            echo "Migrations still failing after $attempt attempts, giving up" >&2
            exit 1
        fi
        echo "Database not ready yet, retrying in 2 seconds ($attempt/15)"
        sleep 2
    done
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
