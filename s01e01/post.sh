#!/usr/bin/env bash
# Usage: post.sh <body.json>  — POSTs to the course API and appends request + reply to log.md verbatim.
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
url="https://hq.mega.dev/challenges/where-the-story-begins/api"
body="$1"
reply="$(curl -sS -i -X POST -H 'Content-Type: application/json' --data-binary @"$body" "$url")"
{
  printf '\n## POST %s (%s)\n\n### body\n\n```json\n' "$url" "$(date -u +%FT%TZ)"
  cat "$body"
  # shellcheck disable=SC2016 # backticks are literal markdown fences
  printf '\n```\n\n### reply\n\n```\n%s\n```\n' "$reply"
} >> "$dir/log.md"
printf '%s\n' "$reply"
