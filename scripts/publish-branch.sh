#!/usr/bin/env bash
# Replaces a branch with the contents of a folder as one fresh commit, so it never builds up history.
# Usage: scripts/publish-branch.sh BRANCH FOLDER   (needs GITHUB_TOKEN and GITHUB_REPOSITORY)
set -euo pipefail

branch="$1"
source_dir="$2"
work="$(mktemp -d)"

cp -r "$source_dir"/. "$work"/
cd "$work"
git init -q -b "$branch"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git commit -q -m "Update $branch for $(date -u +%F)"
git push -q --force "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "HEAD:$branch"
