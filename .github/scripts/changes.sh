#!/usr/bin/env bash
# Decide whether a change needs the whole pipeline or only touches documentation.
#
# A change that only touches docs/, Markdown files or the licence cannot break the build, so the
# heavy jobs are skipped. A skipped job still counts as passed for the required checks of the
# protected branch, and every other kind of file (including the workflow itself) runs everything.
# When no base commit can be found, the answer is always "run everything".
set -euo pipefail

event="${GITHUB_EVENT_NAME:-}"
zero="0000000000000000000000000000000000000000"
base=""

if [ "$event" = "pull_request" ]; then
  base="${PR_BASE_SHA:-}"
elif [ "$event" = "push" ] && [ "${PUSH_BEFORE:-$zero}" != "$zero" ]; then
  base="${PUSH_BEFORE}"
fi

if [ -z "$base" ] || ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "No base commit to compare with, so the full pipeline runs."
  echo "code=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

files="$(git diff --name-only "$base" HEAD)"
echo "Changed files compared with ${base:0:7}:"
echo "$files"

code=false
while IFS= read -r file; do
  [ -z "$file" ] && continue
  case "$file" in
    docs/*|*.md|LICENSE) ;;
    *) code=true ;;
  esac
done <<< "$files"

echo "code=$code" >> "$GITHUB_OUTPUT"
echo "Decision: code=$code"
