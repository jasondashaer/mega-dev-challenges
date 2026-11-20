#!/usr/bin/env bash
# Deploys worker.js to Cloudflare Workers through the API, so no wrangler install is needed.
# Needs CLOUDFLARE_API_TOKEN (Workers Scripts edit) and CLOUDFLARE_ACCOUNT_ID, e.g. via `bws run -- ./deploy.sh`.
set -euo pipefail
cd "$(dirname "$0")"
name="status-for-the-night"
api="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID:?}/workers"
auth=(-H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN:?}")
# cache: "no-store" in fetch needs a compatibility date from 2024-11-11 on.
meta='{"main_module":"worker.js","compatibility_date":"2025-06-01"}'

curl -fsS "${auth[@]}" -X PUT "$api/scripts/$name" \
  -F "metadata=$meta;type=application/json" \
  -F "worker.js=@worker.js;type=application/javascript+module" | jq '{success, errors, id: .result.id}'
curl -fsS "${auth[@]}" -X POST "$api/scripts/$name/subdomain" \
  -H 'content-type: application/json' --data '{"enabled":true,"previews_enabled":false}' | jq '{success, errors}'
sub="$(curl -fsS "${auth[@]}" "$api/subdomain" | jq -r '.result.subdomain')"
echo "https://$name.$sub.workers.dev"
