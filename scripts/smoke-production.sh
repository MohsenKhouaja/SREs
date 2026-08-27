#!/usr/bin/env bash
set -euo pipefail

base_url="${SMOKE_BASE_URL:-https://trysres.xyz}"
www_url="${SMOKE_WWW_URL:-https://www.trysres.xyz}"
attempts="${SMOKE_ATTEMPTS:-60}"
delay_seconds="${SMOKE_DELAY_SECONDS:-20}"

check_production() {
  curl --fail --silent --show-error --max-time 15 "${base_url}/" >/dev/null || return 1

  curl --fail --silent --show-error --max-time 15 "${base_url}/api/health" \
    | python3 -c 'import json, sys; assert json.load(sys.stdin).get("status") == "healthy"' \
    || return 1

  curl --fail --silent --show-error --max-time 15 "${base_url}/api/system/status" \
    | python3 -c 'import json, sys; data=json.load(sys.stdin); required=("mongodb", "postgres", "redis", "prometheus", "loki", "sample_api", "sample_payment"); assert all(data.get(name) == "healthy" for name in required), data' \
    || return 1

  curl --fail --silent --show-error --max-time 15 "${base_url}/api/settings/llm" \
    | python3 -c 'import json, sys; data=json.load(sys.stdin); assert data.get("llm_provider") == "groq", data; assert data.get("api_key_configured") is True, data; assert data.get("groq_model") == "openai/gpt-oss-120b", data; assert data.get("groq_reasoning_effort") == "low", data' \
    || return 1

  local redirect_headers
  redirect_headers="$(curl --silent --show-error --max-time 15 --dump-header - --output /dev/null "${www_url}/")" || return 1
  printf '%s\n' "$redirect_headers" | awk '
    BEGIN { status_ok=0; location_ok=0 }
    /^HTTP\/[0-9.]+ 30[18]/ { status_ok=1 }
    tolower($0) ~ /^location: https:\/\/trysres\.xyz\/?\r?$/ { location_ok=1 }
    END { exit !(status_ok && location_ok) }
  '
}

for attempt in $(seq 1 "$attempts"); do
  if check_production; then
    echo "Production smoke checks passed on attempt ${attempt}."
    exit 0
  fi
  echo "Production is not ready yet (attempt ${attempt}/${attempts})."
  sleep "$delay_seconds"
done

echo "Production smoke checks did not pass before the timeout." >&2
exit 1
