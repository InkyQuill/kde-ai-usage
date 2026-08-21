#!/usr/bin/env bash
set -euo pipefail

# Credential discovery decides whether a provider renders a number or the
# "no token configured" row, and it is the one part of a provider that never
# shows up in the envelope (docs/provider-contract.md: credentials are never
# part of a result). That makes a wrong precedence invisible to the contract
# tests — a key can sit on disk, valid, while the widget claims there is none.
#
# Each case builds a pristine HOME, plants exactly one credential, and asserts
# which one the resolver settles on.

repo="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$repo/package/contents/tools/sh/get-ai-usage"

tmp="$(mktemp -d)"
trap 'case "$tmp" in /tmp/*) rm -rf -- "$tmp" ;; esac' EXIT

failures=0
checks=0

# resolve <provider-function> — runs the real resolver against a clean HOME and
# whatever variables the caller exported, and prints what it found. Resolvers
# that also report where the key came from return (key, source, jwt); only the
# key takes part in the precedence assertion, the tuple cases below check the
# rest explicitly.
resolve() {
    local fn="$1"
    HOME="$tmp/home" PYTHONPATH="$repo/package/contents/tools" python3 -c "
from aiusage.providers.${fn%%:*} import ${fn##*:}
r = ${fn##*:}()
print(r[0] if isinstance(r, tuple) else r)"
}

# expect <description> <expected> <provider-function>
expect() {
    local description="$1" expected="$2" fn="$3" got
    checks=$((checks + 1))
    got="$(resolve "$fn")"
    if [ "$got" != "$expected" ]; then
        printf 'FAIL %s\n  want: %s\n  got:  %s\n' "$description" "$expected" "$got" >&2
        failures=$((failures + 1))
    fi
}

fresh_home() {
    rm -rf "$tmp/home"
    mkdir -p "$tmp/home/.config"
}

# ── Z.AI ────────────────────────────────────────────────────────────────────

fresh_home
expect "no credential anywhere yields an empty key" "" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.config/zai"
printf 'from-config-file\n' >"$tmp/home/.config/zai/token"
expect "reads the conventional ~/.config/zai/token" "from-config-file" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.zai"
printf 'from-dot-zai\n' >"$tmp/home/.zai/token"
expect "falls back to ~/.zai/token" "from-dot-zai" "zai:_zai_key"

# The vendor documents Z_AI_API_KEY; this tool has always read ZAI_TOKEN. A
# user who followed z.ai's own docs used to get "no token configured".
fresh_home
Z_AI_API_KEY=from-vendor-env expect "accepts the vendor's Z_AI_API_KEY spelling" \
    "from-vendor-env" "zai:_zai_key"

fresh_home
ZAI_TOKEN=from-native-env Z_AI_API_KEY=from-vendor-env \
    expect "prefers this tool's own ZAI_TOKEN over the vendor spelling" \
    "from-native-env" "zai:_zai_key"

# glm-acp-agent --setup is where a lot of people paste the coding-plan key.
fresh_home
mkdir -p "$tmp/home/.config/glm-acp-agent"
printf '{"z_ai_api_key": "from-acp-agent"}\n' >"$tmp/home/.config/glm-acp-agent/credentials.json"
expect "reads the glm-acp-agent credentials file" "from-acp-agent" "zai:_zai_key"

mkdir -p "$tmp/home/.config/zai"
printf 'from-config-file\n' >"$tmp/home/.config/zai/token"
expect "an explicit token still beats the borrowed one" "from-config-file" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.config/glm-acp-agent"
printf 'not json at all\n' >"$tmp/home/.config/glm-acp-agent/credentials.json"
expect "a corrupt credentials file is empty, not an exception" "" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.config/glm-acp-agent"
printf '{"z_ai_api_key": null}\n' >"$tmp/home/.config/glm-acp-agent/credentials.json"
expect "a null key is treated as absent" "" "zai:_zai_key"

# The ZCode desktop app keeps its whole session in plain JSON under ~/.zcode;
# a logged-in machine must work with nothing pasted anywhere, and the provider
# must remember where the key came from — the Start Plan balance endpoint is
# only reachable with the app's own JWT.
fresh_home
mkdir -p "$tmp/home/.zcode/v2"
printf '{"oauth:zai:access_token": "from-zcode-app", "zcodejwttoken": "app-jwt"}\n' \
    >"$tmp/home/.zcode/v2/credentials.json"
expect "falls back to the ZCode app session" "from-zcode-app" "zai:_zai_key"

checks=$((checks + 1))
zcode_tuple="$(HOME="$tmp/home" PYTHONPATH="$repo/package/contents/tools" python3 -c '
from aiusage.providers.zai import _zai_key
print(_zai_key())')"
if [ "$zcode_tuple" != "('from-zcode-app', 'zcode', 'app-jwt')" ]; then
    printf 'FAIL the app session carries its source and JWT\n  want: %s\n  got:  %s\n' \
        "('from-zcode-app', 'zcode', 'app-jwt')" "$zcode_tuple" >&2
    failures=$((failures + 1))
fi

fresh_home
mkdir -p "$tmp/home/.zcode/v2" "$tmp/home/.config/zai"
printf '{"oauth:zai:access_token": "from-zcode-app"}\n' >"$tmp/home/.zcode/v2/credentials.json"
printf 'from-config-file\n' >"$tmp/home/.config/zai/token"
expect "an explicit token still beats the app session" "from-config-file" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.zcode/v2"
printf '{"zcodejwttoken": "app-jwt-only"}\n' >"$tmp/home/.zcode/v2/credentials.json"
expect "a ZCode session without an access token is absent" "" "zai:_zai_key"

# ── Moonshot / Kimi ─────────────────────────────────────────────────────────

fresh_home
expect "no Moonshot credential yields an empty key" "" "moonshot:_moonshot_key"

fresh_home
KIMI_API_KEY=from-kimi-env expect "still accepts the KIMI_API_KEY spelling" \
    "from-kimi-env" "moonshot:_moonshot_key"

fresh_home
MOONSHOT_API_KEY=from-moonshot-env KIMI_API_KEY=from-kimi-env \
    expect "prefers MOONSHOT_API_KEY over KIMI_API_KEY" \
    "from-moonshot-env" "moonshot:_moonshot_key"

fresh_home
mkdir -p "$tmp/home/.config/moonshot"
printf 'from-moonshot-file\n' >"$tmp/home/.config/moonshot/api-key"
KIMI_API_KEY=from-kimi-env expect "an environment key outranks the file" \
    "from-kimi-env" "moonshot:_moonshot_key"

fresh_home
mkdir -p "$tmp/home/.config/kimi"
printf 'from-kimi-file\n' >"$tmp/home/.config/kimi/api-key"
expect "reads ~/.config/kimi/api-key" "from-kimi-file" "moonshot:_moonshot_key"

if [ "$failures" -eq 0 ]; then
    printf 'ok — %d credential checks passed\n' "$checks"
else
    printf '%d of %d credential checks failed\n' "$failures" "$checks" >&2
    exit 1
fi
