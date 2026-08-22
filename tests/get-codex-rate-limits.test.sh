#!/usr/bin/env bash
set -euo pipefail

# get-codex-rate-limits used to be a standalone bash+jq JSON-RPC client; that
# logic now lives in aiusage.providers.codex_rate_limits, called in-process by
# get-ai-usage. This test drives that function directly via python3 instead of
# a CLI, still faking the `codex` binary on PATH.

repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export PYTHONPATH="$repo/package/contents/tools"

run() {
    PATH="$tmp:$PATH" python3 -B -c "from aiusage.providers.codex_rate_limits import get_codex_rate_limits; import json; print(json.dumps(get_codex_rate_limits()))"
}

cat >"$tmp/codex" <<'EOF'
#!/usr/bin/env bash
IFS= read -r initialize
if IFS= read -r -t 0.05 premature; then
    printf '%s\n' '{"id":1,"result":{"userAgent":"test"}}'
    exit 0
fi
printf '%s\n' '{"id":1,"result":{"userAgent":"test"}}'
IFS= read -r read_limits
printf '%s\n' '{"id":2,"result":{"rateLimits":{"primary":{"usedPercent":42,"windowDurationMins":10080,"resetsAt":200}}}}'
EOF
chmod +x "$tmp/codex"

actual="$(run)"
jq -e '.rateLimits.primary.windowDurationMins == 10080 and .rateLimits.primary.usedPercent == 42' <<<"$actual" >/dev/null

cat >"$tmp/codex" <<'EOF'
#!/usr/bin/env bash
IFS= read -r initialize
printf '%s\n' '{"id":1,"result":{}}'
IFS= read -r read_limits
EOF
chmod +x "$tmp/codex"

test "$(run)" = '{}'

echo "get-codex-rate-limits: all assertions passed"

# The CLI also has to be found when it is NOT on $PATH: Plasma widgets never
# run the user's shell rc, so mise/cargo installs are invisible to the backend
# even though `codex` works in a terminal. Plant the fake in a fallback spot
# under a fake HOME and resolve without PATH help.
home_fallback="$tmp/home-fallback"
mkdir -p "$home_fallback/.local/bin"
cat >"$home_fallback/.local/bin/codex" <<'EOF'
#!/usr/bin/env bash
IFS= read -r initialize
printf '%s\n' '{"id":1,"result":{"userAgent":"test"}}'
IFS= read -r read_limits
printf '%s\n' '{"id":2,"result":{"rateLimits":{"primary":{"usedPercent":7,"windowDurationMins":300,"resetsAt":900}}}}'
EOF
chmod +x "$home_fallback/.local/bin/codex"
fallback="$(HOME="$home_fallback" PATH="/usr/bin:/bin" CODEX_BIN= python3 -B -c "
from aiusage.providers.codex_rate_limits import get_codex_rate_limits
import json
print(json.dumps(get_codex_rate_limits()))")"
jq -e '.rateLimits.primary.usedPercent == 7' <<<"$fallback" >/dev/null

echo "get-codex-rate-limits: fallback resolution passed"
