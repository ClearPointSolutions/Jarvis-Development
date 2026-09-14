#!/usr/bin/env bash
# Strict HTTP probes shared by installation and preflight. This file is sourced.

jarvis_http_probe() {
  probe_url=$1
  public_authority=$2
  expected_codes=$3
  contract=${4:-none}
  probe_tmp=$(mktemp -d)
  probe_body="$probe_tmp/body"
  probe_headers="$probe_tmp/headers"
  probe_curl=${JARVIS_CURL_BIN:-curl}
  probe_python=${JARVIS_PYTHON_BIN:-python3}
  probe_cleanup() {
    rm -f -- "$probe_body" "$probe_headers"
    rmdir -- "$probe_tmp" 2>/dev/null || true
  }

  if probe_code=$("$probe_curl" --silent --show-error \
      --connect-timeout "${JARVIS_PROBE_CONNECT_TIMEOUT:-3}" \
      --max-time "${JARVIS_PROBE_MAX_TIME:-8}" \
      --max-redirs 0 \
      --header "Host: $public_authority" \
      --output "$probe_body" \
      --dump-header "$probe_headers" \
      --write-out '%{http_code}' \
      "$probe_url"); then
    :
  else
    probe_status=$?
    printf 'HTTP probe transport failed (curl exit %s, HTTP %s): %s\n' \
      "$probe_status" "${probe_code:-000}" "$probe_url" >&2
    probe_cleanup
    return 1
  fi

  case ",$expected_codes," in
    *,"$probe_code",*) ;;
    *)
      printf 'HTTP probe returned unexpected status %s (expected %s): %s\n' \
        "${probe_code:-000}" "$expected_codes" "$probe_url" >&2
      probe_cleanup
      return 1
      ;;
  esac

  case "$contract" in
    none) ;;
    auth_required)
      if ! "$probe_python" - "$probe_body" "$probe_headers" <<'PY'
import json
import sys
from pathlib import Path

body = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
headers = Path(sys.argv[2]).read_text(encoding="iso-8859-1").lower()
error = body.get("error") if isinstance(body, dict) else None
ok = (
    "content-type: application/json" in headers
    and isinstance(error, dict)
    and error.get("code") == "auth.required"
    and error.get("message") == "Authentication is required"
    and isinstance(error.get("request_id"), str)
    and len(error["request_id"]) >= 8
    and isinstance(error.get("details"), dict)
)
raise SystemExit(0 if ok else 1)
PY
      then
        printf 'HTTP 401 did not match the Jarvis auth.required response contract: %s\n' \
          "$probe_url" >&2
        probe_cleanup
        return 1
      fi
      ;;
    same_origin_login_redirect)
      if [ "$probe_code" = 200 ]; then
        :
      else
      location=$(sed -n 's/^[Ll]ocation:[[:space:]]*//p' "$probe_headers" | tr -d '\r' | tail -n1)
      case "$location" in
        /login|/login\?*|"${JARVIS_PUBLIC_ORIGIN%/}"/login|"${JARVIS_PUBLIC_ORIGIN%/}"/login\?*) ;;
        *)
          printf 'HTTP redirect is not the documented same-origin login route: %s\n' \
            "${location:-missing Location}" >&2
          probe_cleanup
          return 1
          ;;
      esac
      fi
      ;;
    *)
      printf 'Unknown HTTP probe contract: %s\n' "$contract" >&2
      probe_cleanup
      return 2
      ;;
  esac

  probe_cleanup
  printf '%s\n' "$probe_code"
}
