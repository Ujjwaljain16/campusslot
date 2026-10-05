#!/usr/bin/env bash
# Wait until other jobs of this workflow run have finished, and fail fast if one of them failed.
#
#   wait-for-jobs.sh <timeout-seconds> "Job name" ["Job name" ...]
#
# Jobs of one workflow run start in parallel. The image build and the cluster setup are slow, so
# they start at once, and this script holds back the steps that must not happen before the quality
# gates (pushing an image) or before the images exist (installing them). It needs GH_TOKEN and the
# "actions: read" permission. A skipped job counts as finished, which is what a documentation-only
# change produces.
set -euo pipefail

timeout="$1"
shift
deadline=$((SECONDS + timeout))

while true; do
  jobs_json="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/jobs?per_page=100")"
  waiting=()
  for name in "$@"; do
    conclusion="$(jq -r --arg n "$name" '[.jobs[] | select(.name == $n)][0].conclusion // "pending"' <<< "$jobs_json")"
    case "$conclusion" in
      success|skipped) ;;
      pending) waiting+=("$name") ;;
      *)
        echo "::error::The job '$name' ended with '$conclusion', so this job stops."
        exit 1
        ;;
    esac
  done
  if [ "${#waiting[@]}" -eq 0 ]; then
    echo "All required jobs have succeeded."
    exit 0
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::Timed out after ${timeout}s while waiting for: ${waiting[*]}"
    exit 1
  fi
  echo "Waiting for: ${waiting[*]}"
  sleep 5
done
