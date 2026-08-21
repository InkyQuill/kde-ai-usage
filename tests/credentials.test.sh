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

# The ZCode desktop app keeps its session under ~/.zcode with every secret
# wrapped as `enc:v1:<iv>.<tag>.<ciphertext>` (AES-256-GCM under sha256 of
# $ZCODE_CREDENTIAL_SECRET, or a machine-derived fallback string). The vectors
# below are deterministic (fixed IV, fixed secret) so the store is realistic:
# nothing in the file is readable without the key. A logged-in machine must
# work with nothing pasted anywhere, and the provider must remember where the
# key came from — the Start Plan balance endpoint needs the app's own JWT.
ZCODE_VEC_ACCESS='enc:v1:BwcHBwcHBwcHBwcH.LDmacVRZeBX6IOn2zpkjOA.QCggnWXAsihbhkxWbtG4zWg'
ZCODE_VEC_JWT='enc:v1:BwcHBwcHBwcHBwcH._ADpnKWlzGcSQC9tFztd-w.QCggnWXAuTxMzlxXJtY'

fresh_home
mkdir -p "$tmp/home/.zcode/v2"
printf '{"oauth:zai:access_token": "%s", "zcodejwttoken": "%s"}\n' \
    "$ZCODE_VEC_ACCESS" "$ZCODE_VEC_JWT" >"$tmp/home/.zcode/v2/credentials.json"
ZCODE_CREDENTIAL_SECRET=zcode-test-secret \
    expect "decrypts the ZCode app session" "zcode-access-cred" "zai:_zai_key"

checks=$((checks + 1))
zcode_tuple="$(HOME="$tmp/home" ZCODE_CREDENTIAL_SECRET=zcode-test-secret \
    PYTHONPATH="$repo/package/contents/tools" python3 -c '
from aiusage.providers.zai import _zai_key
print(_zai_key())')"
if [ "$zcode_tuple" != "('zcode-access-cred', 'zcode', 'zcode-jwt-cred')" ]; then
    printf 'FAIL the app session carries its source and decrypted JWT\n  want: %s\n  got:  %s\n' \
        "('zcode-access-cred', 'zcode', 'zcode-jwt-cred')" "$zcode_tuple" >&2
    failures=$((failures + 1))
fi

# A secret from another machine cannot read this store — and must not crash.
checks=$((checks + 1))
foreign="$(HOME="$tmp/home" ZCODE_CREDENTIAL_SECRET=someone-elses-machine \
    PYTHONPATH="$repo/package/contents/tools" python3 -c '
from aiusage.providers.zai import _zai_key
print(_zai_key()[0])')"
if [ "$foreign" != "" ]; then
    printf 'FAIL a foreign machine secret must yield no credential\n  got: %s\n' "$foreign" >&2
    failures=$((failures + 1))
fi

fresh_home
mkdir -p "$tmp/home/.zcode/v2" "$tmp/home/.config/zai"
printf '{"oauth:zai:access_token": "%s"}\n' "$ZCODE_VEC_ACCESS" \
    >"$tmp/home/.zcode/v2/credentials.json"
printf 'from-config-file\n' >"$tmp/home/.config/zai/token"
ZCODE_CREDENTIAL_SECRET=zcode-test-secret \
    expect "an explicit token still beats the app session" "from-config-file" "zai:_zai_key"

fresh_home
mkdir -p "$tmp/home/.zcode/v2"
printf '{"zcodejwttoken": "%s"}\n' "$ZCODE_VEC_JWT" >"$tmp/home/.zcode/v2/credentials.json"
ZCODE_CREDENTIAL_SECRET=zcode-test-secret \
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
