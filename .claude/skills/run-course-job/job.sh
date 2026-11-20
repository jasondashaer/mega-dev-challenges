#!/usr/bin/env bash
# Runs a MEGA.dev course job over MCP JSON-RPC with curl, for a worker that can't add an MCP
# server mid-session (jasondashaer/fleet#173). Everything it prints is masked: the link, its token, and the
# receipt, escaped JSON included. The link stays in a curl config file, never in argv.
#   job.sh init                       initialize, then notifications/initialized
#   job.sh tools | resources          list the job's tools or resources
#   job.sh skill <uri> [sha256]       read the served skill into $JOB_DIR/SKILL.md and check it
#   job.sh call <tool> [json-args]    call a tool, passing and saving its step token
#   job.sh report <done|failed> <result>   print the final message, receipt unmasked
# Every call needs the same JOB_DIR, a mktemp -d directory holding the job link in "link".
set -euo pipefail
umask 077

dir="${JOB_DIR:?set JOB_DIR to the mktemp -d directory that holds the job link in link}"
[ -s "$dir/link" ] || { echo "no job link in $dir/link" >&2; exit 1; }
chmod 600 "$dir/link"
link="$(tr -d '[:space:]' <"$dir/link")"
# A quote or backslash would break out of the curl config string below.
[[ "$link" =~ ^https?://[^\"\\]+$ ]] || { echo "the job link is not a plain http(s) URL" >&2; exit 1; }

# mask [extra-secret...]: filters stdin. Each secret is also masked in its once- and
# twice-JSON-escaped forms, since tool text carries values inside escaped JSON.
mask() {
  local raw=("$link" "$@") secrets=() piece s e1 e2
  local -a pieces
  # The link layout is unknown, so mask each path or query piece shaped like a token: one that
  # mixes letters and digits at any length, or runs 16 characters. Words like "mcp" stay readable.
  IFS='/?&=#' read -ra pieces <<<"${link#*://*/}"
  for piece in ${pieces[@]+"${pieces[@]}"}; do
    if [[ ("$piece" =~ [0-9] && "$piece" =~ [A-Za-z]) || "${#piece}" -ge 16 ]]; then raw+=("$piece"); fi
  done
  if [ -s "$dir/receipt" ]; then raw+=("$(cat "$dir/receipt")"); fi
  for s in "${raw[@]}"; do
    [ -n "$s" ] || continue
    e1="$(jq -Rr 'tojson | .[1:-1]' <<<"$s")"
    e2="$(jq -Rr 'tojson | .[1:-1]' <<<"$e1")"
    secrets+=("$e2" "$e1" "$s")
  done
  # The regex catches a receipt this script failed to extract, behind any depth of \" escaping.
  MASK_LIST="$(printf '%s\n' "${secrets[@]}")" awk '
    BEGIN { n = split(ENVIRON["MASK_LIST"], s, "\n"); re = "[Rr]eceipt(\\\\)*\"[ ]*:[ ]*(\\\\)*\"[^\"\\\\]+" }
    {
      # Replaced text goes to out and is never searched again, so a secret like "*" cannot loop.
      for (i = 1; i <= n; i++) if (s[i] != "") {
        out = ""; rest = $0
        while ((j = index(rest, s[i])) > 0) { out = out substr(rest, 1, j - 1) "***"; rest = substr(rest, j + length(s[i])) }
        $0 = out rest
      }
      out = ""; rest = $0
      while (match(rest, re)) {
        seg = substr(rest, RSTART, RLENGTH); q = 0
        for (k = 1; k <= length(seg); k++) if (substr(seg, k, 1) == "\"") q = k
        out = out substr(rest, 1, RSTART - 1) substr(seg, 1, q) "***"
        rest = substr(rest, RSTART + RLENGTH)
      }
      print out rest
    }'
}

# Replaces every "receipt" field in a reply, inside JSON strings too, before anything prints it.
# Matching the value instead misses a receipt echoed with other spacing or short values.
# shellcheck disable=SC2016  # $v is a jq variable, not shell
redact='def red: if type == "object" then with_entries(if (.key | ascii_downcase) == "receipt" then .value = "***" else .value |= red end)
  elif type == "array" then map(red)
  elif type == "string" then ((try fromjson catch null) as $v
    | if ($v | type) == "object" or ($v | type) == "array" then $v | red | tojson else . end)
  else . end;'

die_masked() { local f="$1"; shift; mask "$@" <"$f" >&2; exit 1; }

next_id() {
  local id=1
  [ -s "$dir/id" ] && id=$(($(cat "$dir/id") + 1))
  echo "$id" >"$dir/id"
  echo "$id"
}

# rpc <method> <params-json> [id]: posts one JSON-RPC message, leaves the reply in $dir/reply.
# Without an id it is a notification, which expects 202 and no body.
rpc() {
  local method="$1" params="$2" id="${3-}" status ctype rc=0
  printf 'url = "%s"\n' "$link" >"$dir/curlrc"
  # A header file, unlike curl config strings, passes a session id's quotes and backslashes as is.
  {
    echo 'Content-Type: application/json'
    echo 'Accept: application/json, text/event-stream'
    if [ -s "$dir/session" ]; then echo "Mcp-Session-Id: $(cat "$dir/session")"; fi
    if [ -s "$dir/protocol" ]; then echo "MCP-Protocol-Version: $(cat "$dir/protocol")"; fi
  } >"$dir/request.headers"
  jq -nc --arg m "$method" --argjson p "$params" --arg id "$id" \
    '{jsonrpc: "2.0", method: $m, params: $p} + (if $id == "" then {} else {id: ($id | tonumber)} end)' \
    >"$dir/request"
  # -q comes first so a user ~/.curlrc can't add tracing that logs the link unmasked.
  status="$(curl -q -sS -K "$dir/curlrc" -H @"$dir/request.headers" -X POST --data-binary @"$dir/request" \
    --connect-timeout 15 --max-time 300 -D "$dir/headers" -o "$dir/raw" -w '%{http_code}' 2>"$dir/curl.err")" || rc=$?
  # An SSE stream can stay open after its reply, so a timeout (28) still parses what arrived.
  if [ "$rc" -ne 0 ] && ! { [ "$rc" -eq 28 ] && [ -n "$id" ] && [ -s "$dir/raw" ]; }; then die_masked "$dir/curl.err"; fi
  [ "${status:0:1}" = 2 ] || { echo "HTTP $status from $method" >&2; die_masked "$dir/raw"; }

  # Echo a session id if the server hands one out; the S02E04 job server sent none.
  tr -d '\r' <"$dir/headers" | awk 'tolower($1) == "mcp-session-id:" { print $2 }' >"$dir/session.new"
  if [ -s "$dir/session.new" ]; then mv "$dir/session.new" "$dir/session"; else rm -f "$dir/session.new"; fi

  [ -n "$id" ] || return 0
  ctype="$(tr -d '\r' <"$dir/headers" | awk 'tolower($1) == "content-type:" { print tolower($2) }' | tail -n 1)"
  if [[ "$ctype" == text/event-stream* ]]; then
    # One line at a time, so a partial event cut off by the timeout can't hide a complete reply.
    sed -n 's/^data: \{0,1\}//p' "$dir/raw" \
      | jq -cR --argjson id "$id" 'fromjson? | select(type == "object" and .id == $id)' | tail -n 1 >"$dir/reply"
  else
    # Slurped, so trailing junk fails the whole body instead of passing a valid prefix.
    { jq -cs --argjson id "$id" '[.[] | select(type == "object" and .id == $id)] | if length == 1 then .[0] else empty end' \
      "$dir/raw" 2>/dev/null || true; } >"$dir/reply"
  fi
  [ -s "$dir/reply" ] || { echo "no reply to $method" >&2; die_masked "$dir/raw"; }
  if jq -e 'has("error")' "$dir/reply" >/dev/null; then
    echo "$method failed:" >&2
    jq "$redact"' .error | red' "$dir/reply" >"$dir/out"
    die_masked "$dir/out"
  fi
}

# Tool replies nest JSON inside JSON strings, so parse every string that holds JSON while
# looking for a key. A plain "receipt":"..." regex misses the escaped copy (jasondashaer/fleet#173).
# The key's value is read before any further parsing, so a JSON receipt comes back whole.
deep_find() {
  jq -r --arg k "$1" '
    def f($k): if type == "object" then ((.[$k] // empty | if type == "string" then . else tojson end), (.[] | f($k)))
      elif type == "array" then (.[] | f($k))
      elif type == "string" then ((try fromjson catch null) | select(type == "object" or type == "array") | f($k))
      else empty end;
    [.result | f($k)] | last // empty' "$dir/reply"
}

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

case "${1-}" in
  init)
    rm -f "$dir/session" "$dir/protocol" "$dir/step" "$dir/receipt" "$dir/id" "$dir/verified" \
      "$dir/tools.json" "$dir/resources.json" "$dir/SKILL.md"
    rpc initialize '{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"run-course-job","version":"1"}}' "$(next_id)"
    jq -r '.result.protocolVersion // empty' "$dir/reply" >"$dir/protocol"
    rpc notifications/initialized '{}'
    jq '.result.serverInfo' "$dir/reply" | mask
    ;;
  tools)
    rpc tools/list '{}' "$(next_id)"
    cp "$dir/reply" "$dir/tools.json"
    jq '.result.tools' "$dir/reply" | mask
    ;;
  resources)
    rpc resources/list '{}' "$(next_id)"
    cp "$dir/reply" "$dir/resources.json"
    jq '.result.resources' "$dir/reply" | mask
    ;;
  skill)
    uri="${2:?usage: job.sh skill <uri> [sha256]}"
    want="${3-}"
    rm -f "$dir/verified"
    if [ -z "$want" ] && [ -s "$dir/resources.json" ]; then
      want="$(jq -r --arg u "$uri" '[.result.resources[] | select(.uri == $u) | .. | strings
        | capture("(?<h>[0-9a-fA-F]{64})").h] | first // empty' "$dir/resources.json")"
    fi
    [ -n "$want" ] || { echo "no sha256 for $uri; run job.sh resources first, or pass it" >&2; exit 1; }
    rpc resources/read "$(jq -nc --arg u "$uri" '{uri: $u}')" "$(next_id)"
    if jq -e '.result.contents[0] | has("text")' "$dir/reply" >/dev/null; then
      jq -j '.result.contents[0].text' "$dir/reply" >"$dir/SKILL.md"
    else
      jq -j '.result.contents[0].blob' "$dir/reply" | base64 -d >"$dir/SKILL.md"
    fi
    got="$(sha256 "$dir/SKILL.md")"
    want="$(echo "$want" | tr 'A-F' 'a-f')"
    [ "$got" = "$want" ] || { echo "sha256 mismatch for $uri: got $got, listed $want" >&2; exit 1; }
    touch "$dir/verified"
    echo "sha256 ok: $dir/SKILL.md" >&2
    mask <"$dir/SKILL.md"
    ;;
  call)
    tool="${2:?usage: job.sh call <tool> [json-args]}"
    args="${3:-"{}"}"
    jq -e 'type == "object"' <<<"$args" >/dev/null || { echo "arguments must be a JSON object" >&2; exit 1; }
    [ -s "$dir/tools.json" ] || { echo "run job.sh tools first: it says which tools take a step" >&2; exit 1; }
    [ -f "$dir/verified" ] || { echo "run job.sh skill first: follow the checked skill before any tool call" >&2; exit 1; }
    takes_step=false
    if jq -e --arg t "$tool" \
      '.result.tools[] | select(.name == $t) | .inputSchema.properties | has("step")' "$dir/tools.json" >/dev/null; then
      takes_step=true
    fi
    if $takes_step && [ -s "$dir/step" ] && ! jq -e 'has("step")' <<<"$args" >/dev/null; then
      args="$(jq -c --arg s "$(cat "$dir/step")" '. + {step: $s}' <<<"$args")"
    fi
    rpc tools/call "$(jq -nc --arg t "$tool" --argjson a "$args" '{name: $t, arguments: $a}')" "$(next_id)"
    jq -r "$redact"' .result | red | if (.content // []) != [] then .content[] | (.text // tojson) else .structuredContent | tojson end' \
      "$dir/reply" >"$dir/out"
    receipt="$(deep_find receipt)"
    # An error reply can still hand out the step for a retry, but never a receipt to keep.
    step="$(deep_find step)"
    if [ -n "$step" ]; then printf '%s\n' "$step" >"$dir/step"; echo "step saved" >&2; fi
    if jq -e '.result.isError == true' "$dir/reply" >/dev/null; then
      echo "$tool returned an error:" >&2
      die_masked "$dir/out" "$receipt"
    fi
    if [ -n "$receipt" ]; then printf '%s\n' "$receipt" >"$dir/receipt"; echo "receipt saved" >&2; fi
    mask <"$dir/out"
    ;;
  report)
    status="${2-}"
    result="${3:?usage: job.sh report <done|failed> <result>}"
    case "$status" in done | failed) ;; *) echo "status must be done or failed" >&2; exit 1 ;; esac
    if [ "$status" = "done" ] && [ ! -s "$dir/receipt" ]; then
      echo "no receipt saved, so the job is not done; report failed" >&2
      exit 1
    fi
    receipt="none"
    if [ -s "$dir/receipt" ]; then receipt="$(cat "$dir/receipt")"; fi
    printf 'STATUS: %s\nRECEIPT: %s\nRESULT: %s\n' "$status" "$receipt" "$(tr '\n' ' ' <<<"$result" | mask)"
    ;;
  *)
    sed -n '5,10s/^# \{0,1\}//p' "$0" >&2
    exit 1
    ;;
esac
