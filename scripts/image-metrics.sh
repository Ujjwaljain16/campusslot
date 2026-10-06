#!/usr/bin/env bash
# Measure the container images: size, build time (cold and after a one-line code change) and startup
# time, for the real Dockerfiles and for naive single-stage versions of them.
#
#   scripts/image-metrics.sh
#
# Everything is built from a temporary copy, so the repository is not touched, and every image and
# container that it creates is removed at the end. The base images are pulled first, so the build
# times do not include the download of a base image (they do include the package downloads).
# Results and reading: docs/engineering/performance.md
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
RUNS="${RUNS:-5}"
PULLED=""
trap 'docker rm -f cs-measure-run >/dev/null 2>&1; for b in $PULLED; do docker rmi -f "$b" >/dev/null 2>&1; done; docker rmi -f cs-measure-backend cs-measure-backend-naive cs-measure-backend-builder cs-measure-frontend cs-measure-frontend-naive cs-measure-frontend-build >/dev/null 2>&1; rm -rf "$WORK"' EXIT

now() { python -c "import time; print(f'{time.time():.3f}')"; }
elapsed() { python -c "print(f'{$(now) - $1:.1f}')"; }
size_mb() { local bytes; bytes=$(docker image inspect --format '{{.Size}}' "$1"); python -c "print(round($bytes / 1048576))"; }

cp -r "$ROOT/backend" "$WORK/backend"
cp -r "$ROOT/frontend" "$WORK/frontend"
rm -rf "$WORK/frontend/node_modules" "$WORK/frontend/dist" "$WORK/backend/.venv"
find "$WORK/backend" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null

# the naive versions: one stage, the full base image, everything copied before the dependencies are installed
cat > "$WORK/backend/Dockerfile.naive" <<'EOF'
FROM python:3.12
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
EOF
cat > "$WORK/frontend/Dockerfile.naive" <<'EOF'
FROM node:26
WORKDIR /app
COPY . .
RUN npm ci && npm run build
EXPOSE 8080
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "8080"]
EOF
printf '**/node_modules\n**/dist\n**/__pycache__\n**/.venv\n' > "$WORK/.dockerignore"
cp "$WORK/.dockerignore" "$WORK/backend/.dockerignore"; cp "$WORK/.dockerignore" "$WORK/frontend/.dockerignore"

echo "### Image metrics, $(date '+%Y-%m-%d %H:%M:%S'), docker $(docker version --format '{{.Server.Version}}')"
echo "pulling the base images first, so that the build times do not include their download"
for image in python:3.12-slim python:3.12 node:26-alpine node:26 nginxinc/nginx-unprivileged:1.30-alpine; do
  docker image inspect "$image" > /dev/null 2>&1 || PULLED="$PULLED $image"
  docker pull -q "$image" > /dev/null 2>&1 || echo "  could not pull $image now, the local copy is used if there is one"
done

build() { # name context dockerfile [extra args]
  # Both Dockerfiles start with "# syntax=docker/dockerfile:1", so every build contacts Docker Hub, even
  # when all layers are cached. A failed lookup is retried, and only the attempt that works is timed.
  local name=$1 ctx=$2 file=$3 attempt t0; shift 3
  for attempt in 1 2 3; do
    t0=$(now)
    if docker build -q -t "$name" -f "$file" "$@" "$ctx" > /dev/null 2>&1; then elapsed "$t0"; return 0; fi
    sleep 5
  done
  echo "failed"
}

echo; echo "### 1. Build from nothing (--no-cache), seconds"
backend_cold=$(build cs-measure-backend "$WORK/backend" "$WORK/backend/Dockerfile" --no-cache)
backend_naive_cold=$(build cs-measure-backend-naive "$WORK/backend" "$WORK/backend/Dockerfile.naive" --no-cache)
frontend_cold=$(build cs-measure-frontend "$WORK/frontend" "$WORK/frontend/Dockerfile" --no-cache)
frontend_naive_cold=$(build cs-measure-frontend-naive "$WORK/frontend" "$WORK/frontend/Dockerfile.naive" --no-cache)
printf '  %-22s %8s s   (single stage: %s s)\n' "backend" "$backend_cold" "$backend_naive_cold"
printf '  %-22s %8s s   (single stage: %s s)\n' "frontend" "$frontend_cold" "$frontend_naive_cold"

echo; echo "### 2. Rebuild after a one-line change in the application code, with the layer cache, seconds"
echo "# a comment is added to a source file, which is what most commits look like"
# the comment is different on every run, otherwise the layer cache of an earlier run would answer the build
stamp="$(date +%s%N)"
echo "# change $stamp" >> "$WORK/backend/app/main.py"
echo "// change $stamp" >> "$WORK/frontend/src/main.jsx"
backend_warm=$(build cs-measure-backend "$WORK/backend" "$WORK/backend/Dockerfile")
backend_naive_warm=$(build cs-measure-backend-naive "$WORK/backend" "$WORK/backend/Dockerfile.naive")
frontend_warm=$(build cs-measure-frontend "$WORK/frontend" "$WORK/frontend/Dockerfile")
frontend_naive_warm=$(build cs-measure-frontend-naive "$WORK/frontend" "$WORK/frontend/Dockerfile.naive")
printf '  %-22s %8s s   (single stage, files copied first: %s s)\n' "backend" "$backend_warm" "$backend_naive_warm"
printf '  %-22s %8s s   (single stage, files copied first: %s s)\n' "frontend" "$frontend_warm" "$frontend_naive_warm"

# the stage that a multi-stage build leaves behind: what would be shipped without the second stage
docker build -q -t cs-measure-backend-builder --target builder -f "$WORK/backend/Dockerfile" "$WORK/backend" > /dev/null 2>&1
docker build -q -t cs-measure-frontend-build --target build -f "$WORK/frontend/Dockerfile" "$WORK/frontend" > /dev/null 2>&1

echo; echo "### 3. Image size (uncompressed, as Docker reports it), MB"
printf '  %-34s %6s\n' "backend, the real image" "$(size_mb cs-measure-backend)"
printf '  %-34s %6s\n' "backend, the build stage alone" "$(size_mb cs-measure-backend-builder)"
printf '  %-34s %6s\n' "backend, single stage, full python" "$(size_mb cs-measure-backend-naive)"
printf '  %-34s %6s\n' "frontend, the real image" "$(size_mb cs-measure-frontend)"
printf '  %-34s %6s\n' "frontend, the build stage alone" "$(size_mb cs-measure-frontend-build)"
printf '  %-34s %6s\n' "frontend, single stage, full node" "$(size_mb cs-measure-frontend-naive)"

startup() { # image port path
  python - "$1" "$2" "$3" "$RUNS" <<'PY'
import statistics, subprocess, sys, time, urllib.request
image, port, path, runs = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
inner = "8000" if port == "18000" else "8080"
times = []
for _ in range(runs):
    subprocess.run(["docker", "rm", "-f", "cs-measure-run"], capture_output=True)
    start = time.perf_counter()
    # nginx refuses to start when the host named "backend" (the proxy target) does not resolve. In
    # Compose and Kubernetes it exists, so here it is pointed at the container itself.
    extra = ["--add-host", "backend:127.0.0.1"] if image == "cs-measure-frontend" else []
    subprocess.run(["docker", "run", "-d", "--name", "cs-measure-run", *extra, "-p", f"{port}:{inner}", image],
                   capture_output=True, check=True)
    ok = False
    while time.perf_counter() - start < 60:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/{path}", timeout=1) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(0.02)
    if ok:
        times.append(time.perf_counter() - start)
    subprocess.run(["docker", "rm", "-f", "cs-measure-run"], capture_output=True)
if times:
    print(f"median {statistics.median(times):.2f} s, fastest {min(times):.2f} s, slowest {max(times):.2f} s ({len(times)} of {runs} runs)")
else:
    print("never became ready")
PY
}

echo; echo "### 4. Startup: from \"docker run\" to the first 200 answer, $RUNS runs each (this includes creating the container)"
printf '  %-34s %s\n' "backend, the real image" "$(startup cs-measure-backend 18000 health)"
printf '  %-34s %s\n' "backend, single stage" "$(startup cs-measure-backend-naive 18000 health)"
printf '  %-34s %s\n' "frontend, the real image" "$(startup cs-measure-frontend 18080 healthz)"
printf '  %-34s %s\n' "frontend, single stage (vite preview)" "$(startup cs-measure-frontend-naive 18080 "")"

echo; echo "### 5. What the real images are made of"
for image in cs-measure-backend cs-measure-frontend; do
  echo "  $image: $(docker image inspect --format '{{len .RootFS.Layers}} layers, runs as user "{{.Config.User}}"' "$image")"
done
echo "done"
