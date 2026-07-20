# Provider Usage Window Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the widget classify and display Claude and Codex session/weekly limits by semantic metadata or duration, hiding unavailable windows while preserving legacy five-hour state and history.

**Architecture:** Put provider-payload normalization in a small QML-compatible JavaScript module with Node tests. Obtain the preferred Codex snapshot through the local Codex app-server, retain the authenticated web request as fallback, and let `main.qml` map normalized windows into semantic availability/state properties. Presentation components render rows, panel slots, and chart selectors only for available windows.

**Tech Stack:** KDE Plasma 6 QML, QML JavaScript, Bash, Codex app-server JSON-RPC, Node.js built-in test runner, `qmllint`, `kpackagetool6` package validation.

## Global Constraints

- Never infer a window meaning from `primary` or `secondary` position alone.
- Recognize session windows only at 300 minutes or 18,000 seconds and weekly windows only at 10,080 minutes or 604,800 seconds.
- Retain legacy QML properties and history keys `s`, `w`, `cp`, and `cw`; do not rewrite or delete saved history.
- A window is available only when it has a finite numeric percentage and is not an explicitly inactive placeholder.
- Unknown window kinds or durations remain hidden.
- OpenAI API organization billing remains separate from Codex subscription limits.

---

### Task 1: Provider Window Normalizer

**Files:**
- Create: `package/contents/code/UsageWindows.js`
- Create: `tests/usage-windows.test.js`

**Interfaces:**
- Consumes: raw Claude OAuth usage objects, Codex app-server `GetAccountRateLimitsResponse` objects, or legacy Codex web usage objects.
- Produces: `normalizeClaude(payload)` and `normalizeCodex(payload)`, each returning `{ session, weekly, additional }`; each window is `{ available, pct, resetAt }` and each additional entry includes `name`, `session`, `weekly`, and `limitReached`.

- [ ] **Step 1: Write failing Claude normalization tests**

Create `tests/usage-windows.test.js` with Node's built-in runner. Include these assertions exactly:

```js
const test = require("node:test");
const assert = require("node:assert/strict");
const UsageWindows = require("../package/contents/code/UsageWindows.js");

test("normalizes Claude semantic session and weekly limits", () => {
    const result = UsageWindows.normalizeClaude({
        limits: [
            { group: "session", kind: "session", is_active: true, percent: 23, resets_at: "2026-07-19T15:00:00Z" },
            { group: "weekly", kind: "weekly_scoped", is_active: true, percent: 61, resets_at: "2026-07-25T15:00:00Z" }
        ]
    });
    assert.deepEqual(result.session, { available: true, pct: 23, resetAt: "2026-07-19T15:00:00Z" });
    assert.deepEqual(result.weekly, { available: true, pct: 61, resetAt: "2026-07-25T15:00:00Z" });
});

test("falls back to legacy Claude windows", () => {
    const result = UsageWindows.normalizeClaude({
        five_hour: { utilization: 12, resets_at: "session-reset" },
        seven_day: { utilization: 45, resets_at: "weekly-reset" }
    });
    assert.equal(result.session.available, true);
    assert.equal(result.session.pct, 12);
    assert.equal(result.weekly.available, true);
    assert.equal(result.weekly.pct, 45);
});

test("rejects inactive and nonnumeric Claude placeholders", () => {
    const result = UsageWindows.normalizeClaude({
        limits: [
            { group: "session", kind: "session", is_active: false, percent: 0 },
            { group: "weekly", kind: "weekly_scoped", is_active: true, percent: null }
        ]
    });
    assert.equal(result.session.available, false);
    assert.equal(result.weekly.available, false);
});
```

- [ ] **Step 2: Run the Claude tests and verify RED**

Run: `node --test tests/usage-windows.test.js`

Expected: FAIL with `MODULE_NOT_FOUND` for `UsageWindows.js`.

- [ ] **Step 3: Add failing Codex duration tests**

Append tests for the current app-server schema, the legacy web schema, reversed positions, additional limits, and unknown durations:

```js
test("normalizes a weekly-only Codex app-server snapshot", () => {
    const result = UsageWindows.normalizeCodex({
        rateLimits: {
            limitId: "codex",
            primary: { usedPercent: 58, windowDurationMins: 10080, resetsAt: 1784956965 },
            secondary: null
        }
    });
    assert.equal(result.session.available, false);
    assert.deepEqual(result.weekly, { available: true, pct: 58, resetAt: 1784956965000 });
});

test("classifies legacy Codex windows by duration even when reversed", () => {
    const result = UsageWindows.normalizeCodex({
        rate_limit: {
            primary_window: { used_percent: 70, limit_window_seconds: 604800, reset_at: 200 },
            secondary_window: { used_percent: 20, limit_window_seconds: 18000, reset_at: 100 }
        }
    });
    assert.equal(result.session.pct, 20);
    assert.equal(result.session.resetAt, 100000);
    assert.equal(result.weekly.pct, 70);
    assert.equal(result.weekly.resetAt, 200000);
});

test("normalizes app-server named limits and ignores unknown durations", () => {
    const result = UsageWindows.normalizeCodex({
        rateLimits: { primary: { usedPercent: 1, windowDurationMins: 60, resetsAt: 10 } },
        rateLimitsByLimitId: {
            codex: { limitId: "codex", primary: { usedPercent: 1, windowDurationMins: 60, resetsAt: 10 } },
            spark: { limitId: "spark", limitName: "Spark", primary: { usedPercent: 9, windowDurationMins: 10080, resetsAt: 20 } }
        }
    });
    assert.equal(result.session.available, false);
    assert.equal(result.weekly.available, false);
    assert.equal(result.additional.length, 1);
    assert.equal(result.additional[0].weekly.pct, 9);
});
```

- [ ] **Step 4: Implement the QML-compatible normalizer**

Create `package/contents/code/UsageWindows.js` with plain ES5-compatible functions. Use this public surface and export guard:

```js
function unavailableWindow() {
    return { available: false, pct: 0, resetAt: null };
}

function finiteNumber(value) {
    return typeof value === "number" && isFinite(value);
}

function windowValue(pct, resetAt, active) {
    if (active === false || !finiteNumber(pct))
        return unavailableWindow();
    return { available: true, pct: pct, resetAt: resetAt === undefined ? null : resetAt };
}

function classifyCodexWindow(raw) {
    if (!raw)
        return { kind: "", value: unavailableWindow() };
    var minutes = finiteNumber(raw.windowDurationMins) ? raw.windowDurationMins : null;
    var seconds = finiteNumber(raw.limit_window_seconds) ? raw.limit_window_seconds : null;
    var kind = minutes === 300 || seconds === 18000 ? "session" :
        (minutes === 10080 || seconds === 604800 ? "weekly" : "");
    var pct = raw.usedPercent !== undefined ? raw.usedPercent : raw.used_percent;
    var resetSeconds = raw.resetsAt !== undefined ? raw.resetsAt : raw.reset_at;
    var resetAt = finiteNumber(resetSeconds) ? resetSeconds * 1000 : null;
    return { kind: kind, value: kind ? windowValue(pct, resetAt, true) : unavailableWindow() };
}

function assignCodexWindow(result, raw) {
    var classified = classifyCodexWindow(raw);
    if (classified.kind)
        result[classified.kind] = classified.value;
}

function normalizeCodex(payload) {
    var result = { session: unavailableWindow(), weekly: unavailableWindow(), additional: [] };
    var main = payload && (payload.rateLimits || payload.rate_limit);
    if (main) {
        assignCodexWindow(result, main.primary || main.primary_window);
        assignCodexWindow(result, main.secondary || main.secondary_window);
    }
    var byId = payload && payload.rateLimitsByLimitId;
    if (byId) {
        for (var id in byId) {
            if (!Object.prototype.hasOwnProperty.call(byId, id) || id === "codex")
                continue;
            var snapshot = byId[id];
            var entry = { name: snapshot.limitName || snapshot.limitId || id, session: unavailableWindow(), weekly: unavailableWindow(), limitReached: snapshot.rateLimitReachedType !== null && snapshot.rateLimitReachedType !== undefined };
            assignCodexWindow(entry, snapshot.primary);
            assignCodexWindow(entry, snapshot.secondary);
            result.additional.push(entry);
        }
    } else {
        var legacy = payload && payload.additional_rate_limits || [];
        for (var i = 0; i < legacy.length; i++) {
            var legacyRate = legacy[i].rate_limit || {};
            var legacyEntry = { name: legacy[i].limit_name || "Model " + (i + 1), session: unavailableWindow(), weekly: unavailableWindow(), limitReached: legacyRate.limit_reached === true };
            assignCodexWindow(legacyEntry, legacyRate.primary_window);
            assignCodexWindow(legacyEntry, legacyRate.secondary_window);
            result.additional.push(legacyEntry);
        }
    }
    return result;
}

function normalizeClaude(payload) {
    var result = { session: unavailableWindow(), weekly: unavailableWindow(), additional: [] };
    var limits = payload && payload.limits || [];
    for (var i = 0; i < limits.length; i++) {
        var item = limits[i] || {};
        if (item.group === "session" || item.kind === "session")
            result.session = windowValue(item.percent, item.resets_at, item.is_active);
        if (item.group === "weekly" || item.kind === "weekly" || item.kind === "weekly_scoped")
            result.weekly = windowValue(item.percent, item.resets_at, item.is_active);
    }
    if (!result.session.available && payload && payload.five_hour)
        result.session = windowValue(payload.five_hour.utilization, payload.five_hour.resets_at, true);
    if (!result.weekly.available && payload && payload.seven_day)
        result.weekly = windowValue(payload.seven_day.utilization, payload.seven_day.resets_at, true);
    return result;
}

if (typeof module !== "undefined" && module.exports)
    module.exports = { normalizeClaude: normalizeClaude, normalizeCodex: normalizeCodex };
```

- [ ] **Step 5: Run the normalizer tests and verify GREEN**

Run: `node --test tests/usage-windows.test.js`

Expected: 6 tests pass, 0 fail.

- [ ] **Step 6: Commit the normalizer**

```bash
git add package/contents/code/UsageWindows.js tests/usage-windows.test.js
git commit -m "test: define provider usage window normalization"
```

---

### Task 2: Preferred Codex App-Server Source

**Files:**
- Create: `package/contents/tools/sh/get-codex-rate-limits`
- Create: `tests/get-codex-rate-limits.test.sh`
- Modify: `package/contents/ui/main.qml:1-9, 1276-1300, 1580-1658, 2210-2260`

**Interfaces:**
- Consumes: `codex app-server --stdio` and its existing authenticated account.
- Produces: one compact `GetAccountRateLimitsResponse` JSON object on stdout, or `{}` on missing Codex, timeout, protocol failure, or missing response.
- `main.qml` imports `../code/UsageWindows.js` as `UsageWindows`, calls `applyCodexUsage(payload)`, and falls back to `fetchCodexUsageFromWeb()` only when no recognized window is returned.

- [ ] **Step 1: Write the failing helper test**

Create a temporary fake `codex` executable that consumes stdin and returns initialize plus rate-limit responses. The test must assert that only the rate-limit result is emitted and that a missing response produces `{}`:

```bash
#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/codex" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' '{"id":1,"result":{"userAgent":"test"}}'
printf '%s\n' '{"id":2,"result":{"rateLimits":{"primary":{"usedPercent":42,"windowDurationMins":10080,"resetsAt":200}}}}'
EOF
chmod +x "$tmp/codex"

actual="$(PATH="$tmp:$PATH" "$repo/package/contents/tools/sh/get-codex-rate-limits")"
jq -e '.rateLimits.primary.windowDurationMins == 10080 and .rateLimits.primary.usedPercent == 42' <<<"$actual" >/dev/null

cat >"$tmp/codex" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' '{"id":1,"result":{}}'
EOF
chmod +x "$tmp/codex"
test "$(PATH="$tmp:$PATH" "$repo/package/contents/tools/sh/get-codex-rate-limits")" = '{}'
```

- [ ] **Step 2: Run the helper test and verify RED**

Run: `bash tests/get-codex-rate-limits.test.sh`

Expected: FAIL because `get-codex-rate-limits` does not exist.

- [ ] **Step 3: Implement the app-server helper**

Create the executable with fixed JSON-RPC request IDs and a bounded runtime:

```bash
#!/usr/bin/env bash
set -uo pipefail

if ! command -v codex >/dev/null 2>&1; then
    printf '%s\n' '{}'
    exit 0
fi

initialize='{"id":1,"method":"initialize","params":{"clientInfo":{"name":"kde-ai-usage","version":"1"},"capabilities":{"experimentalApi":true}}}'
read_limits='{"id":2,"method":"account/rateLimits/read","params":null}'
output="$(printf '%s\n%s\n' "$initialize" "$read_limits" | timeout 10 codex app-server --stdio 2>/dev/null || true)"
result="$(jq -c 'select(.id == 2 and .result != null) | .result' <<<"$output" 2>/dev/null | head -n 1)"
printf '%s\n' "${result:-{}}"
```

Run: `chmod +x package/contents/tools/sh/get-codex-rate-limits`.

- [ ] **Step 4: Run the helper test and verify GREEN**

Run: `bash tests/get-codex-rate-limits.test.sh`

Expected: exit 0 with no output.

- [ ] **Step 5: Wire semantic Codex state into `main.qml`**

Import `UsageWindows.js`. Add mutable semantic properties `codexSessionAvailable`, `codexSessionPct`, `codexSessionResetDate`, `codexSessionCountdown`, `codexWeeklyAvailable`, `codexWeeklyPct`, `codexWeeklyResetDate`, and `codexWeeklyCountdown`. Keep the old names as deprecated readonly aliases:

```qml
readonly property real codexPrimaryPct: root.codexSessionPct
readonly property var codexPrimaryResetDate: root.codexSessionResetDate
readonly property string codexPrimaryCountdown: root.codexSessionCountdown
readonly property real codexSecondaryPct: root.codexWeeklyPct
readonly property var codexSecondaryResetDate: root.codexWeeklyResetDate
readonly property string codexSecondaryCountdown: root.codexWeeklyCountdown
```

Add `applyCodexUsage(payload)` which calls `UsageWindows.normalizeCodex(payload)`, sets semantic state and additional entries, updates `codexUsageAvailable`, countdowns, and history, and returns whether at least one window was recognized. `recordCodexUsage` must accept availability booleans and write `cp` or `cw` only when its corresponding window is available, leaving any existing recent history member untouched otherwise.

Change `fetchCodexUsage()` to execute `get-codex-rate-limits` through a new `codexUsageSource`. Move the current XHR body to `fetchCodexUsageFromWeb()`. In `codexUsageSource.onNewData`, parse stdout and call the web fallback when parsing fails or `applyCodexUsage()` returns false. The web fallback passes its decoded response to the same `applyCodexUsage()` function.

- [ ] **Step 6: Verify parser and helper tests remain green**

Run: `node --test tests/usage-windows.test.js && bash tests/get-codex-rate-limits.test.sh`

Expected: all Node tests pass and the shell test exits 0.

- [ ] **Step 7: Commit the preferred source integration**

```bash
git add package/contents/tools/sh/get-codex-rate-limits tests/get-codex-rate-limits.test.sh package/contents/ui/main.qml
git commit -m "fix: normalize current Codex rate limits"
```

---

### Task 3: Claude Semantic Limits and Availability-Aware History

**Files:**
- Modify: `package/contents/ui/main.qml:109-121, 684-707, 1341-1420, 2075-2089`

**Interfaces:**
- Consumes: `UsageWindows.normalizeClaude(d)` from Task 1.
- Produces: `sessionAvailable` and `weeklyAvailable`; existing `sessionPct`, `weeklyPct`, reset, token, and countdown properties remain the presentation contract.

- [ ] **Step 1: Add a semantic-over-legacy precedence regression test**

Append this test to `tests/usage-windows.test.js`:

```js
test("prefers active Claude semantic entries over legacy values", () => {
    const result = UsageWindows.normalizeClaude({
        limits: [{ group: "session", kind: "session", is_active: true, percent: 31, resets_at: "new-reset" }],
        five_hour: { utilization: 99, resets_at: "old-reset" }
    });
    assert.deepEqual(result.session, { available: true, pct: 31, resetAt: "new-reset" });
});
```

- [ ] **Step 2: Run the targeted regression test**

Run: `node --test --test-name-pattern="prefers active Claude" tests/usage-windows.test.js`

Expected: PASS, proving the already test-driven Task 1 normalizer supplies the precedence required by this QML integration.

- [ ] **Step 3: Apply normalized Claude state**

Add `sessionAvailable` and `weeklyAvailable`, defaulting false. In the 200 response branch of `fetchClaudeUsage`, normalize the decoded object first, set availability, percentages, and reset dates from semantic output, but continue reading `tokens_used` and `token_limit` from legacy objects when present. Clear both availability flags when OAuth is missing or a successful payload contains neither window.

Change `recordUsage(sessionPct, weeklyPct)` to `recordUsage(sessionPct, weeklyPct, sessionAvailable, weeklyAvailable)`. Only assign `last.s`/`last.w` or new object fields when their availability flag is true. Do not remove old keys from a recent history record.

- [ ] **Step 4: Run the full normalizer suite**

Run: `node --test tests/usage-windows.test.js`

Expected: 7 tests pass, 0 fail.

- [ ] **Step 5: Commit Claude normalization**

```bash
git add package/contents/code/UsageWindows.js tests/usage-windows.test.js package/contents/ui/main.qml
git commit -m "fix: read semantic Claude usage limits"
```

---

### Task 4: Hide Unavailable Rows, Slots, and Chart Choices

**Files:**
- Modify: `package/contents/ui/ClaudeTab.qml:140-162`
- Modify: `package/contents/ui/OpenAiTab.qml:70-169`
- Modify: `package/contents/ui/UsageChart.qml:130-175, 508-516`
- Modify: `package/contents/ui/main.qml:532-576, 2701-2788`
- Modify: `tests/usage-windows.test.js`

**Interfaces:**
- Consumes: provider availability flags and semantic Codex properties from Tasks 2-3.
- Produces: no visible five-hour UI unless a session window is actually available; weekly-only Codex renders exactly one `7D` panel slot.

- [ ] **Step 1: Add failing chart-choice tests to the normalizer module**

Extend `UsageWindows.js` with a public `chartChoices(provider, sessionAvailable, weeklyAvailable)` function, writing these tests first:

```js
test("offers only weekly charts for weekly-only Codex", () => {
    assert.deepEqual(UsageWindows.chartChoices("openai", false, true), [
        { id: "codex_weekly", label: "7D" }
    ]);
});

test("offers session day and weekly charts when both windows exist", () => {
    assert.deepEqual(UsageWindows.chartChoices("claude", true, true), [
        { id: "session", label: "5H" },
        { id: "day", label: "24H" },
        { id: "weekly", label: "7D" }
    ]);
});
```

- [ ] **Step 2: Run chart-choice tests and verify RED**

Run: `node --test --test-name-pattern="offers" tests/usage-windows.test.js`

Expected: FAIL because `chartChoices` is not defined.

- [ ] **Step 3: Implement `chartChoices` and export it**

Use provider-specific IDs and include 5H/24H together only when session is available:

```js
function chartChoices(provider, sessionAvailable, weeklyAvailable) {
    var result = [];
    if (sessionAvailable) {
        result.push({ id: provider === "openai" ? "codex_primary" : "session", label: "5H" });
        result.push({ id: provider === "openai" ? "codex_day" : "day", label: "24H" });
    }
    if (weeklyAvailable)
        result.push({ id: provider === "openai" ? "codex_weekly" : "weekly", label: "7D" });
    return result;
}
```

Export `chartChoices` beside both normalizers.

- [ ] **Step 4: Apply visibility rules to popup rows**

Set the Claude five-hour and seven-day `PopupRow.visible` bindings to `sessionAvailable` and `weeklyAvailable`. Set Codex main rows to `codexSessionAvailable` and `codexWeeklyAvailable`, and bind them to semantic values/countdowns. For each additional limit, set row visibility to `modelData.session.available` or `modelData.weekly.available` and bind the corresponding semantic window. Keep legacy aliases available but do not use them for labels.

- [ ] **Step 5: Apply visibility rules to chart and panel**

Use `UsageWindows.chartChoices(...)` as the `UsageChart` selector model. If the selected chart becomes unavailable after a refresh, switch to weekly when available, otherwise session. Make reset labels recognize both `weekly` and `codex_weekly`.

In the panel, show Claude session and weekly slots only for their available windows and show their separator only when both are available. For OpenAI, show the session slot only when session is available; retain its API-cost fallback only when no Codex limit is available. Show the weekly slot only when weekly is available, and show the separator only when both Codex windows are available. Build tooltips from whichever semantic windows exist so a weekly-only account never mentions 5h.

- [ ] **Step 6: Run tests and QML lint**

Run:

```bash
node --test tests/usage-windows.test.js
qmllint package/contents/ui/main.qml package/contents/ui/ClaudeTab.qml package/contents/ui/OpenAiTab.qml package/contents/ui/UsageChart.qml
```

Expected: 9 tests pass. `qmllint` exits 0; environment-only warnings about unresolved Plasma import paths are acceptable only if there are no syntax, property, or binding errors.

- [ ] **Step 7: Commit presentation behavior**

```bash
git add package/contents/code/UsageWindows.js tests/usage-windows.test.js package/contents/ui/main.qml package/contents/ui/ClaudeTab.qml package/contents/ui/OpenAiTab.qml package/contents/ui/UsageChart.qml
git commit -m "fix: hide unavailable provider usage windows"
```

---

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md:46-92, 261-271, 290-293`
- Modify: `docs/superpowers/specs/2026-07-19-provider-usage-windows-design.md` only if implementation reveals a factual mismatch.

**Interfaces:**
- Consumes: completed behavior from Tasks 1-4.
- Produces: user-facing documentation that distinguishes current dynamic subscription windows from official API billing and explains retained compatibility.

- [ ] **Step 1: Update provider documentation**

State that Claude windows are discovered from semantic `limits[]` data with legacy field fallback, and that rows appear only when returned. State that Codex plan limits come from the local Codex app-server with authenticated web fallback, are classified by actual duration, and may currently be weekly-only. Remove claims that every refresh always appends both five-hour and weekly percentages; document that only available series are appended and historical fields are retained.

- [ ] **Step 2: Run the complete verification chain**

Run:

```bash
node --test tests/usage-windows.test.js
bash tests/get-codex-rate-limits.test.sh
bash -n package/contents/tools/sh/get-codex-rate-limits
qmllint package/contents/ui/*.qml package/contents/config/config.qml
kpackagetool6 --type Plasma/Applet --appstream-metainfo package >/tmp/kde-ai-usage.appdata.xml
archive="$(mktemp /tmp/kde-ai-usage.XXXXXX.plasmoid)"
(cd package && zip -qr "$archive" .)
unzip -t "$archive"
rm -f "$archive"
git diff --check
```

Expected: all 9 Node tests pass; shell tests and syntax checks exit 0; QML has no syntax/property/binding errors; metadata is accepted; every archive member tests `OK`; `git diff --check` emits nothing.

- [ ] **Step 3: Inspect the final diff against the approved spec**

Run: `git diff --stat && git diff -- package/contents/code/UsageWindows.js package/contents/tools/sh/get-codex-rate-limits package/contents/ui/main.qml package/contents/ui/ClaudeTab.qml package/contents/ui/OpenAiTab.qml package/contents/ui/UsageChart.qml README.md`

Confirm explicitly:

- weekly-only Codex has no five-hour row, tooltip, slot, or chart choice;
- Claude five-hour remains visible when its semantic or legacy session payload is available;
- inactive, null, and unknown windows remain hidden;
- legacy aliases and history keys remain present;
- unrelated provider code is unchanged.

- [ ] **Step 4: Commit documentation and verification-ready state**

```bash
git add README.md
git commit -m "docs: describe dynamic provider usage windows"
```
