#!/usr/bin/env bash
# Collect everything the reviewer reads into .review/ in the current folder.
#
# Usage: prepare_review.sh <pr-number> <base-ref>
# Needs: git, gh (with GH_TOKEN set), and a checkout of the repository.
#
# It prints skip=true or skip=false (to $GITHUB_OUTPUT when set, else to the screen).
# skip=true means the change is too big or has binary files, so the model is not run;
# findings.json already says so.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <pr-number> <base-ref>" >&2
  exit 2
fi
PR="$1"
BASE_REF="$2"

MAX_BYTES=300000
OUT="${GITHUB_OUTPUT:-/dev/stdout}"

mkdir -p .review

# The change itself, the names of the changed files, and the pull request text.
gh pr diff "$PR" > .review/diff.patch
gh pr diff "$PR" --name-only > .review/files.txt
gh pr view "$PR" --json title,body --jq '"# " + .title + "\n\n" + (.body // "")' > .review/pr.md

# The working rules come from the base branch, not from the pull request,
# so a pull request cannot change the rules it is reviewed by.
git fetch --no-tags --depth=1 origin "$BASE_REF"
for file in PRINCIPLES.md AGENTS.md; do
  if ! git show "origin/$BASE_REF:$file" > ".review/$file" 2>/dev/null; then
    : > ".review/$file"   # the file does not exist there: leave it empty
  fi
done

# Too big or binary: say so in findings.json and skip the model.
bytes="$(wc -c < .review/diff.patch | tr -d '[:space:]')"
binary="$(grep -c '^Binary files' .review/diff.patch || true)"
if [ "$bytes" -gt "$MAX_BYTES" ] || [ "$binary" -gt 0 ]; then
  printf '{"summary":"Diff too large to review (%s bytes)","new_surface":[],"findings":[]}\n' \
    "$bytes" > .review/findings.json
  echo "skip=true" >> "$OUT"
else
  echo "skip=false" >> "$OUT"
fi
