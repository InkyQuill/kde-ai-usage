# KDE AI Usage Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Z.AI and GitHub Copilot as first-class KDE Plasma AI Usage widget providers.

**Architecture:** Keep the current plasmoid architecture: provider-specific shell helpers fetch and normalize JSON, while QML owns state, panel slots, popup tabs, settings, chart history, and stale/error behavior. Add two focused helpers and two focused tab components without introducing Python, waybar config support, browser-cookie scraping, or a generic provider framework.

**Tech Stack:** KDE Plasma 6 QML, `org.kde.plasma.plasma5support` executable `DataSource`, Bash, `curl`, `jq`, existing widget config XML.

---

## File Structure

- Create `package/contents/tools/sh/get-zai-usage`: resolve Z.AI token, call Z.AI quota endpoint, normalize response to widget JSON.
- Create `package/contents/tools/sh/get-copilot-usage`: resolve GitHub token/quota, call GitHub API, normalize Copilot usage to widget JSON.
- Create `package/contents/ui/ZaiTab.qml`: render Z.AI token quota, tools quota, and model details.
- Create `package/contents/ui/CopilotTab.qml`: render Copilot premium request quota and account/reset stats.
- Modify `package/contents/config/main.xml`: add provider toggles, credential fields, and Copilot quota setting.
- Modify `package/contents/ui/KeyRow.qml`: support Z.AI and GitHub token setting keys.
- Modify `package/contents/ui/SettingsPanel.qml`: add provider toggles and credential rows.
- Modify `package/contents/ui/main.qml`: add provider state, colors, tooltip text, chart routing, `DataSource` parsers, `loadCreds()` branches, panel slots, tabs, and total history fields.
- Modify `package/contents/ui/UsageChart.qml`: include Z.AI and Copilot in visibility and chart series selection.
- Modify `README.md` and `kde-store-description.md`: document new providers and credentials.

This is a personal-use workspace. Use verification checkpoints only:

```bash
find . -maxdepth 3 -type d -name .git -print
git rev-parse --show-toplevel
```

Expected: the command shows the imported source repositories, while `git rev-parse --show-toplevel` fails at the workspace root. At each checkpoint, run verification commands and summarize changed files.

### Task 1: Add Helper Scripts

**Files:**
- Create: `package/contents/tools/sh/get-zai-usage`
- Create: `package/contents/tools/sh/get-copilot-usage`
- Test: shell commands in this task

- [ ] **Step 1: Write `get-zai-usage`**

Create `package/contents/tools/sh/get-zai-usage` with this content:

```bash
#!/usr/bin/env bash
set -u

API_KEY="${WIDGET_ZAI_TOKEN:-}"
[ -z "$API_KEY" ] && [ -n "${ZAI_TOKEN:-}" ] && API_KEY="$ZAI_TOKEN"
[ -z "$API_KEY" ] && [ -f "$HOME/.config/zai/token" ] && API_KEY=$(tr -d '\n\r ' < "$HOME/.config/zai/token" 2>/dev/null)

if [ -z "$API_KEY" ]; then
    echo "{}"
    exit 0
fi

if [ -n "${ZAI_RESPONSE_FILE:-}" ] && [ -f "$ZAI_RESPONSE_FILE" ]; then
    BODY=$(cat "$ZAI_RESPONSE_FILE")
    HTTP_CODE=200
else
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Accept: application/json" \
        -H "User-Agent: kde-ai-usage/zai" \
        --max-time 10 \
        "https://api.z.ai/api/monitor/usage/quota/limit" 2>/dev/null)
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | head -n -1)
fi

case "$HTTP_CODE" in
    200)
        echo "$BODY" | jq --arg key "$API_KEY" '
            if (.success == false) then
                {
                    zaiToken: "",
                    keyValid: false,
                    error: (.msg // "Z.AI API error")
                }
            else
                (.data // {}) as $d |
                (($d.limits // []) | map(select(.type == "TOKENS_LIMIT")) | first // {}) as $tok |
                (($d.limits // []) | map(select(.type == "TIME_LIMIT")) | first // {}) as $tools |
                {
                    zaiToken: $key,
                    keyValid: true,
                    level: ($d.level // ""),
                    tokenPct: ($tok.percentage // 0),
                    tokenResetMs: ($tok.nextResetTime // null),
                    tokenUsed: ($tok.used // $tok.usage // null),
                    tokenLimit: ($tok.limit // $tok.total // null),
                    toolsPct: ($tools.percentage // 0),
                    toolsRemaining: ($tools.remaining // null),
                    toolsResetMs: ($tools.nextResetTime // null),
                    models: ($tools.usageDetails // [])
                }
            end'
        ;;
    401|403)
        jq -n '{zaiToken: "", keyValid: false, error: "Invalid Z.AI token"}'
        ;;
    000)
        jq -n '{zaiToken: "", keyValid: false, error: "Z.AI network error"}'
        ;;
    *)
        jq -n --arg code "$HTTP_CODE" '{zaiToken: "", keyValid: false, error: ("Z.AI HTTP " + $code)}'
        ;;
esac
```

- [ ] **Step 2: Write `get-copilot-usage`**

Create `package/contents/tools/sh/get-copilot-usage` with this content:

```bash
#!/usr/bin/env bash
set -u

API_KEY="${WIDGET_GITHUB_TOKEN:-}"
[ -z "$API_KEY" ] && [ -n "${GITHUB_TOKEN:-}" ] && API_KEY="$GITHUB_TOKEN"
[ -z "$API_KEY" ] && [ -f "$HOME/.config/github-copilot/token" ] && API_KEY=$(tr -d '\n\r ' < "$HOME/.config/github-copilot/token" 2>/dev/null)

QUOTA="${WIDGET_COPILOT_QUOTA:-}"
[ -z "$QUOTA" ] && [ -n "${COPILOT_QUOTA:-}" ] && QUOTA="$COPILOT_QUOTA"
case "$QUOTA" in
    ''|*[!0-9]*) QUOTA=300 ;;
esac

if [ -z "$API_KEY" ]; then
    echo "{}"
    exit 0
fi

github_get() {
    local url="$1"
    if [ "$url" = "user" ] && [ -n "${COPILOT_USER_RESPONSE_FILE:-}" ] && [ -f "$COPILOT_USER_RESPONSE_FILE" ]; then
        cat "$COPILOT_USER_RESPONSE_FILE"
        printf '\n200'
        return
    fi
    if [ "$url" = "usage" ] && [ -n "${COPILOT_USAGE_RESPONSE_FILE:-}" ] && [ -f "$COPILOT_USAGE_RESPONSE_FILE" ]; then
        cat "$COPILOT_USAGE_RESPONSE_FILE"
        printf '\n200'
        return
    fi
    curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        -H "User-Agent: kde-ai-usage/copilot" \
        --max-time 10 \
        "$url" 2>/dev/null
}

USER_RESPONSE=$(github_get "https://api.github.com/user")
USER_HTTP=$(echo "$USER_RESPONSE" | tail -1)
USER_BODY=$(echo "$USER_RESPONSE" | head -n -1)

if [ "$USER_HTTP" != "200" ]; then
    case "$USER_HTTP" in
        401|403) jq -n '{githubToken: "", keyValid: false, error: "Invalid GitHub token"}' ;;
        000) jq -n '{githubToken: "", keyValid: false, error: "GitHub network error"}' ;;
        *) jq -n --arg code "$USER_HTTP" '{githubToken: "", keyValid: false, error: ("GitHub HTTP " + $code)}' ;;
    esac
    exit 0
fi

USERNAME=$(echo "$USER_BODY" | jq -r '.login // empty')
if [ -z "$USERNAME" ]; then
    jq -n '{githubToken: "", keyValid: false, error: "GitHub username missing"}'
    exit 0
fi

USAGE_RESPONSE=$(github_get "https://api.github.com/users/$USERNAME/settings/billing/premium_request/usage")
USAGE_HTTP=$(echo "$USAGE_RESPONSE" | tail -1)
USAGE_BODY=$(echo "$USAGE_RESPONSE" | head -n -1)

case "$USAGE_HTTP" in
    200)
        echo "$USAGE_BODY" | jq --arg key "$API_KEY" --arg username "$USERNAME" --argjson quota "$QUOTA" '
            (if type == "array" then . else (.usageItems // []) end) as $items |
            ($items | map(.grossQuantity // 0) | add // 0) as $used |
            {
                githubToken: $key,
                keyValid: true,
                username: $username,
                used: ($used | tonumber),
                quota: $quota,
                pct: (if $quota > 0 then ([100, (($used / $quota) * 100)] | min) else 0 end)
            }'
        ;;
    401|403|404)
        jq -n '{githubToken: "", keyValid: false, error: "GitHub token cannot read Copilot premium request usage"}'
        ;;
    000)
        jq -n '{githubToken: "", keyValid: false, error: "GitHub Copilot network error"}'
        ;;
    *)
        jq -n --arg code "$USAGE_HTTP" '{githubToken: "", keyValid: false, error: ("GitHub Copilot HTTP " + $code)}'
        ;;
esac
```

- [ ] **Step 3: Make helpers executable**

Run:

```bash
chmod +x package/contents/tools/sh/get-zai-usage package/contents/tools/sh/get-copilot-usage
```

Expected: command exits with code 0.

- [ ] **Step 4: Verify shell syntax**

Run:

```bash
bash -n package/contents/tools/sh/get-zai-usage
bash -n package/contents/tools/sh/get-copilot-usage
```

Expected: both commands exit with code 0 and print nothing.

- [ ] **Step 5: Verify missing-token JSON**

Run:

```bash
env -u WIDGET_ZAI_TOKEN -u ZAI_TOKEN HOME="$(mktemp -d)" package/contents/tools/sh/get-zai-usage | jq -e 'type == "object" and length == 0'
env -u WIDGET_GITHUB_TOKEN -u GITHUB_TOKEN HOME="$(mktemp -d)" package/contents/tools/sh/get-copilot-usage | jq -e 'type == "object" and length == 0'
```

Expected: both commands print `true`.

- [ ] **Step 6: Verify mocked success parsing**

Run:

```bash
tmpdir=$(mktemp -d)
cat > "$tmpdir/zai.json" <<'JSON'
{"success":true,"data":{"level":"pro","limits":[{"type":"TOKENS_LIMIT","percentage":42,"nextResetTime":3600000,"used":420,"limit":1000},{"type":"TIME_LIMIT","percentage":25,"remaining":75,"nextResetTime":86400000,"usageDetails":[{"modelCode":"glm-4.5","usage":12}]}]}}
JSON
WIDGET_ZAI_TOKEN=test ZAI_RESPONSE_FILE="$tmpdir/zai.json" package/contents/tools/sh/get-zai-usage | jq -e '.keyValid == true and .tokenPct == 42 and .toolsPct == 25 and .models[0].modelCode == "glm-4.5"'

cat > "$tmpdir/user.json" <<'JSON'
{"login":"octocat"}
JSON
cat > "$tmpdir/usage.json" <<'JSON'
{"usageItems":[{"grossQuantity":10},{"grossQuantity":5.5}]}
JSON
WIDGET_GITHUB_TOKEN=test WIDGET_COPILOT_QUOTA=100 COPILOT_USER_RESPONSE_FILE="$tmpdir/user.json" COPILOT_USAGE_RESPONSE_FILE="$tmpdir/usage.json" package/contents/tools/sh/get-copilot-usage | jq -e '.keyValid == true and .username == "octocat" and .used == 15.5 and .pct == 15.5'
```

Expected: both `jq -e` checks print `true`.

- [ ] **Step 7: Checkpoint**

Run:

```bash
ls -l package/contents/tools/sh/get-zai-usage package/contents/tools/sh/get-copilot-usage
```

Expected: both files exist and have executable bits. Record this checkpoint in the final task summary.

### Task 2: Add Config And Settings

**Files:**
- Modify: `package/contents/config/main.xml`
- Modify: `package/contents/ui/KeyRow.qml`
- Modify: `package/contents/ui/SettingsPanel.qml`

- [ ] **Step 1: Add config entries**

In `package/contents/config/main.xml`, inside `<group name="General">`, add these entries after `openrouterEnabled` and the existing API key entries:

```xml
    <entry name="zaiEnabled" type="Bool">
      <default>false</default>
    </entry>
    <entry name="copilotEnabled" type="Bool">
      <default>false</default>
    </entry>
    <entry name="zaiToken" type="String">
      <default></default>
    </entry>
    <entry name="githubToken" type="String">
      <default></default>
    </entry>
    <entry name="copilotQuota" type="Int">
      <default>300</default>
    </entry>
```

- [ ] **Step 2: Add KeyRow mappings**

In `package/contents/ui/KeyRow.qml`, extend both the read and write branches:

```qml
            if (kr.configKey === "zaiToken")
                return Plasmoid.configuration.zaiToken || "";
            if (kr.configKey === "githubToken")
                return Plasmoid.configuration.githubToken || "";
```

```qml
            if (kr.configKey === "zaiToken")
                Plasmoid.configuration.zaiToken = text;
            if (kr.configKey === "githubToken")
                Plasmoid.configuration.githubToken = text;
```

- [ ] **Step 3: Add provider toggles**

In `package/contents/ui/SettingsPanel.qml`, extend the services repeater model with:

```qml
                {
                    id: "zai",
                    label: "Z.AI",
                    color: "#126ef4"
                },
                {
                    id: "copilot",
                    label: "Copilot",
                    color: "#8b5cf6"
                },
```

Add checked-state branches:

```qml
                        if (modelData.id === "zai")
                            return Plasmoid.configuration.zaiEnabled;
                        if (modelData.id === "copilot")
                            return Plasmoid.configuration.copilotEnabled;
```

Add toggle-write branches:

```qml
                        if (modelData.id === "zai")
                            Plasmoid.configuration.zaiEnabled = checked;
                        if (modelData.id === "copilot")
                            Plasmoid.configuration.copilotEnabled = checked;
```

- [ ] **Step 4: Add credential rows**

Near the existing Mistral/OpenRouter `KeyRow` instances, add:

```qml
        KeyRow {
            rootItem: settingsPanelRoot.rootItem
            label: "Z.AI Token"
            configKey: "zaiToken"
            rowVisible: Plasmoid.configuration.zaiEnabled
            placeholder: "ZAI_TOKEN"
        }

        KeyRow {
            rootItem: settingsPanelRoot.rootItem
            label: "GitHub Token"
            configKey: "githubToken"
            rowVisible: Plasmoid.configuration.copilotEnabled
            placeholder: "GITHUB_TOKEN"
        }
```

- [ ] **Step 5: Add Copilot quota input**

Below the GitHub token row, add a compact quota row:

```qml
        RowLayout {
            Layout.fillWidth: true
            visible: Plasmoid.configuration.copilotEnabled
            spacing: 6

            PlasmaComponents.Label {
                text: "Copilot quota"
                font.pixelSize: 11
                color: Kirigami.Theme.textColor
                Layout.preferredWidth: 90
            }

            QQC2.TextField {
                text: String(Plasmoid.configuration.copilotQuota || 300)
                inputMethodHints: Qt.ImhDigitsOnly
                validator: IntValidator { bottom: 1; top: 1000000 }
                Layout.preferredWidth: 90
                font.pixelSize: 10
                onEditingFinished: {
                    var val = parseInt(text);
                    if (isNaN(val) || val < 1)
                        val = 300;
                    Plasmoid.configuration.copilotQuota = val;
                    text = String(val);
                }
            }

            PlasmaComponents.Label {
                text: "monthly premium requests"
                font.pixelSize: 9
                opacity: 0.45
                color: Kirigami.Theme.textColor
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }
```

- [ ] **Step 6: Verify settings text references**

Run:

```bash
rg -n "zaiEnabled|copilotEnabled|zaiToken|githubToken|copilotQuota" package/contents/config/main.xml package/contents/ui/KeyRow.qml package/contents/ui/SettingsPanel.qml
```

Expected: every new config key appears in the appropriate file.

- [ ] **Step 7: Checkpoint**

Record the changed config/settings files in the final task summary.

### Task 3: Wire Main QML State, Fetching, Panel, And Chart

**Files:**
- Modify: `package/contents/ui/main.qml`
- Modify: `package/contents/ui/UsageChart.qml`

- [ ] **Step 1: Add provider enablement and tab ordering**

In `main.qml`, near existing provider enablement properties, add:

```qml
    property bool zaiEnabled: Plasmoid.configuration.zaiEnabled
    property bool copilotEnabled: Plasmoid.configuration.copilotEnabled
```

In `enabledTabs`, after `openrouter`, add:

```qml
        if (root.zaiEnabled)
            t.push("zai");
        if (root.copilotEnabled)
            t.push("copilot");
```

- [ ] **Step 2: Add provider state**

Near the OpenRouter/Mistral state blocks, add:

```qml
    // ── Z.AI data ─────────────────────────────────────────────────────────────
    property string _zaiToken: ""
    property bool zaiKeyValid: false
    property string zaiLevel: ""
    property real zaiTokenPct: 0
    property var zaiTokenUsed: null
    property var zaiTokenLimit: null
    property var zaiTokenResetDate: null
    property string zaiTokenCountdown: ""
    property real zaiToolsPct: 0
    property var zaiToolsRemaining: null
    property var zaiToolsResetDate: null
    property string zaiToolsCountdown: ""
    property var zaiModels: []
    property string zaiError: ""

    // ── GitHub Copilot data ──────────────────────────────────────────────────
    property string _githubToken: ""
    property bool copilotKeyValid: false
    property string copilotUsername: ""
    property real copilotUsed: 0
    property int copilotQuota: Plasmoid.configuration.copilotQuota || 300
    property real copilotPct: 0
    property var copilotResetDate: null
    property string copilotCountdown: ""
    property string copilotError: ""
```

- [ ] **Step 3: Add colors and icon labels**

Near existing color properties, add:

```qml
    readonly property color zaiBlue: "#126ef4"
    readonly property color copilotPurple: "#8b5cf6"
```

Extend provider color helpers with:

```qml
        if (tabId === "zai")
            return root.zaiBlue;
        if (tabId === "copilot")
            return root.copilotPurple;
```

Extend provider display-name helpers with:

```qml
        if (tabId === "zai")
            return "Z.AI";
        if (tabId === "copilot")
            return "Copilot";
```

- [ ] **Step 4: Add chart window routing**

In `_windowForTab` and related chart-window helpers, add `zai` and `copilot` as single-window provider chart IDs, matching `kiro`, `antigravity`, and `openrouter`:

```qml
        if (tab === "zai")
            return "zai";
        if (tab === "copilot")
            return "copilot";
```

Where single-window tabs are checked, include:

```qml
win === "zai" || win === "copilot"
```

- [ ] **Step 5: Add history record functions**

Near `recordOpenRouterUsage` and `recordMistralVibeUsage`, add:

```qml
    function recordZaiUsage(pct) {
        root.recordUsagePoint({ zai: Math.max(0, Math.min(100, pct || 0)) });
    }

    function recordCopilotUsage(pct) {
        root.recordUsagePoint({ copilot: Math.max(0, Math.min(100, pct || 0)) });
    }
```

If the existing history function does not accept partial objects, mirror the exact implementation style of existing `recordOpenRouterUsage` and use field names `zai` and `copilot`.

- [ ] **Step 6: Add tooltip lines**

In `toolTipSubText`, add branches:

```qml
        } else if (tab === "zai") {
            if (root.zaiKeyValid) {
                lines.push("Z.AI 5H: " + Math.round(root.zaiTokenPct) + "%" + (root.zaiTokenCountdown ? " (" + root.zaiTokenCountdown + ")" : ""));
                lines.push("Tools: " + Math.round(root.zaiToolsPct) + "%" + (root.zaiToolsRemaining !== null ? " · " + root.zaiToolsRemaining + " remaining" : ""));
            }
            if (root.zaiError)
                lines.push("⚠ " + root.zaiError);
        } else if (tab === "copilot") {
            if (root.copilotKeyValid) {
                lines.push("Copilot: " + Math.round(root.copilotPct) + "%");
                lines.push("Requests: " + root.copilotUsed + " / " + root.copilotQuota);
                if (root.copilotCountdown)
                    lines.push("Resets: " + root.copilotCountdown);
            }
            if (root.copilotError)
                lines.push("⚠ " + root.copilotError);
```

- [ ] **Step 7: Add DataSources**

Near the OpenRouter `DataSource`, add:

```qml
    Plasma5Support.DataSource {
        id: zaiUsageSource
        engine: "executable"
        connectedSources: []
        onNewData: function (src, data) {
            disconnectSource(src);
            if (root.enabledTabs[root.activeTab] !== "zai")
                return;
            var output = (data["stdout"] || "").trim();
            if (!output || output === "{}") {
                root.zaiError = "";
                root.errorMsg = "Z.AI: no token configured";
                root.stale = root.lastUpdate !== "";
                return;
            }
            try {
                var res = JSON.parse(output);
                if (res.error) {
                    root._zaiToken = res.zaiToken || "";
                    root.zaiKeyValid = res.keyValid === true;
                    root.zaiError = res.error;
                    root.errorMsg = res.error;
                    root.stale = root.lastUpdate !== "";
                    return;
                }
                root._zaiToken = res.zaiToken || "";
                root.zaiKeyValid = res.keyValid === true;
                root.zaiLevel = res.level || "";
                root.zaiTokenPct = res.tokenPct || 0;
                root.zaiTokenUsed = res.tokenUsed !== undefined ? res.tokenUsed : null;
                root.zaiTokenLimit = res.tokenLimit !== undefined ? res.tokenLimit : null;
                root.zaiTokenResetDate = root.msFromNowToDate(res.tokenResetMs);
                root.zaiToolsPct = res.toolsPct || 0;
                root.zaiToolsRemaining = res.toolsRemaining !== undefined ? res.toolsRemaining : null;
                root.zaiToolsResetDate = root.msFromNowToDate(res.toolsResetMs);
                root.zaiModels = res.models || [];
                root.zaiError = "";
                root.errorMsg = "";
                root.stale = false;
                root.lastUpdate = Qt.formatTime(new Date(), "hh:mm");
                root._offline = false;
                offlineRetryTimer.stop();
                root.recordZaiUsage(root.zaiTokenPct);
            } catch (e) {
                root.zaiError = "Z.AI: parse error";
                root.errorMsg = "Z.AI: parse error";
                root.stale = root.lastUpdate !== "";
            }
        }
    }

    Plasma5Support.DataSource {
        id: copilotUsageSource
        engine: "executable"
        connectedSources: []
        onNewData: function (src, data) {
            disconnectSource(src);
            if (root.enabledTabs[root.activeTab] !== "copilot")
                return;
            var output = (data["stdout"] || "").trim();
            if (!output || output === "{}") {
                root.copilotError = "";
                root.errorMsg = "Copilot: no GitHub token configured";
                root.stale = root.lastUpdate !== "";
                return;
            }
            try {
                var res = JSON.parse(output);
                if (res.error) {
                    root._githubToken = res.githubToken || "";
                    root.copilotKeyValid = res.keyValid === true;
                    root.copilotError = res.error;
                    root.errorMsg = res.error;
                    root.stale = root.lastUpdate !== "";
                    return;
                }
                root._githubToken = res.githubToken || "";
                root.copilotKeyValid = res.keyValid === true;
                root.copilotUsername = res.username || "";
                root.copilotUsed = res.used || 0;
                root.copilotQuota = res.quota || (Plasmoid.configuration.copilotQuota || 300);
                root.copilotPct = res.pct || 0;
                root.copilotResetDate = root.nextMonthResetDate();
                root.copilotError = "";
                root.errorMsg = "";
                root.stale = false;
                root.lastUpdate = Qt.formatTime(new Date(), "hh:mm");
                root._offline = false;
                offlineRetryTimer.stop();
                root.recordCopilotUsage(root.copilotPct);
            } catch (e) {
                root.copilotError = "Copilot: parse error";
                root.errorMsg = "Copilot: parse error";
                root.stale = root.lastUpdate !== "";
            }
        }
    }
```

- [ ] **Step 8: Add date helper functions**

Near countdown/date helpers, add:

```qml
    function msFromNowToDate(ms) {
        if (ms === undefined || ms === null || ms <= 0)
            return null;
        return new Date(Date.now() + ms);
    }

    function nextMonthResetDate() {
        var now = new Date();
        return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1, 0, 0, 0));
    }
```

In the countdown timer update block, add:

```qml
        root.zaiTokenCountdown = root.zaiTokenResetDate ? root.formatCountdown(root.zaiTokenResetDate) : "";
        root.zaiToolsCountdown = root.zaiToolsResetDate ? root.formatCountdown(root.zaiToolsResetDate) : "";
        root.copilotCountdown = root.copilotResetDate ? root.formatCountdown(root.copilotResetDate) : "";
```

- [ ] **Step 9: Add `loadCreds()` branches**

In `loadCreds()`, add:

```qml
        } else if (tab === "zai") {
            var cfgKey = Plasmoid.configuration.zaiToken || "";
            var envPrefix = cfgKey ? "WIDGET_ZAI_TOKEN=\"$(printf %s '" + Qt.btoa(cfgKey) + "' | base64 -d)\" " : "";
            var cmd = envPrefix + root.scriptDir + "get-zai-usage";
            zaiUsageSource.disconnectSource(cmd);
            zaiUsageSource.connectSource(cmd);
        } else if (tab === "copilot") {
            var cfgKey = Plasmoid.configuration.githubToken || "";
            var quota = Plasmoid.configuration.copilotQuota || 300;
            var envPrefix = cfgKey ? "WIDGET_GITHUB_TOKEN=\"$(printf %s '" + Qt.btoa(cfgKey) + "' | base64 -d)\" " : "";
            envPrefix += "WIDGET_COPILOT_QUOTA=\"" + quota + "\" ";
            var cmd = envPrefix + root.scriptDir + "get-copilot-usage";
            copilotUsageSource.disconnectSource(cmd);
            copilotUsageSource.connectSource(cmd);
```

- [ ] **Step 10: Add panel slots**

Near the OpenRouter panel slot, add:

```qml
            PanelSlot {
                pct: root.zaiTokenPct
                iconColor: root.zaiBlue
                stale: root.stale && root.panelTab === "zai"
                visible: root.panelTab === "zai" && !root.showSettings
                showCost: false
                tooltipText: "Z.AI" + (root.zaiLevel ? "\nLevel: " + root.zaiLevel : "") + "\n5h Tokens: " + Math.round(root.zaiTokenPct) + "%" + (root.zaiTokenCountdown ? "\nResets: " + root.zaiTokenCountdown : "") + "\nTools: " + Math.round(root.zaiToolsPct) + "%"
            }

            PanelSlot {
                pct: root.copilotPct
                iconColor: root.copilotPurple
                stale: root.stale && root.panelTab === "copilot"
                visible: root.panelTab === "copilot" && !root.showSettings
                showCost: false
                tooltipText: "GitHub Copilot" + (root.copilotUsername ? "\n@" + root.copilotUsername : "") + "\nRequests: " + root.copilotUsed + " / " + root.copilotQuota + "\nUsage: " + Math.round(root.copilotPct) + "%" + (root.copilotCountdown ? "\nResets: " + root.copilotCountdown : "")
            }
```

- [ ] **Step 11: Add tab instances**

In the popup content area where other provider tabs are instantiated, add:

```qml
                        ZaiTab {
                            rootItem: root
                        }

                        CopilotTab {
                            rootItem: root
                        }
```

- [ ] **Step 12: Update `UsageChart.qml` provider visibility**

Where the chart visibility explicitly lists providers, include:

```qml
|| rootItem.enabledTabs[rootItem.activeTab] === "zai"
|| rootItem.enabledTabs[rootItem.activeTab] === "copilot"
```

Where chart window data chooses series fields, add cases for `zai` and `copilot` using the history fields created in Step 5.

- [ ] **Step 13: Verify references**

Run:

```bash
rg -n "zai|copilot|ZaiTab|CopilotTab|get-zai-usage|get-copilot-usage" package/contents/ui/main.qml package/contents/ui/UsageChart.qml
```

Expected: all provider state, route, fetch, panel, chart, and tab references are present.

- [ ] **Step 14: Checkpoint**

Record QML state-wiring changes in the final task summary.

### Task 4: Add Provider Tabs

**Files:**
- Create: `package/contents/ui/ZaiTab.qml`
- Create: `package/contents/ui/CopilotTab.qml`

- [ ] **Step 1: Create `ZaiTab.qml`**

Create `package/contents/ui/ZaiTab.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: zaiTabRoot
    property Item rootItem

    visible: rootItem.enabledTabs[rootItem.activeTab] === "zai" && !rootItem.showSettings
    Layout.fillWidth: true
    spacing: 14

    function fmt(value) {
        if (value === undefined || value === null)
            return "—";
        if (value >= 1000000)
            return (value / 1000000).toFixed(1) + "M";
        if (value >= 1000)
            return (value / 1000).toFixed(1) + "K";
        return String(value);
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        visible: rootItem.zaiKeyValid

        Kirigami.Icon {
            source: "network-server"
            width: 14
            height: 14
            color: rootItem.zaiBlue
            isMask: true
            opacity: 0.75
        }

        PlasmaComponents.Label {
            text: rootItem.zaiLevel ? "Z.AI · " + rootItem.zaiLevel : "Z.AI"
            font.pixelSize: 10
            opacity: 0.65
            color: Kirigami.Theme.textColor
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Rectangle {
            height: 18
            width: zaiBadgeLabel.implicitWidth + 12
            radius: 4
            color: Qt.rgba(0.07, 0.43, 0.96, 0.18)
            border.width: 1
            border.color: Qt.rgba(0.07, 0.43, 0.96, 0.35)
            PlasmaComponents.Label {
                id: zaiBadgeLabel
                anchors.centerIn: parent
                text: "CONNECTED"
                font.pixelSize: 9
                font.bold: true
                color: rootItem.zaiBlue
            }
        }
    }

    ColumnLayout {
        visible: !rootItem.zaiKeyValid && rootItem._zaiToken === ""
        Layout.fillWidth: true
        spacing: 6
        PlasmaComponents.Label {
            text: "Not connected"
            font.pixelSize: 12
            font.bold: true
            color: Kirigami.Theme.textColor
            opacity: 0.7
        }
        PlasmaComponents.Label {
            text: "Set a Z.AI token in settings or via $ZAI_TOKEN / ~/.config/zai/token"
            font.pixelSize: 10
            opacity: 0.5
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    ColumnLayout {
        visible: rootItem.zaiError !== "" && !rootItem.zaiKeyValid
        Layout.fillWidth: true
        spacing: 6
        PlasmaComponents.Label {
            text: "Z.AI error"
            font.pixelSize: 12
            font.bold: true
            color: "#ef4444"
        }
        PlasmaComponents.Label {
            text: rootItem.zaiError
            font.pixelSize: 10
            opacity: 0.7
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    ColumnLayout {
        visible: rootItem.zaiKeyValid
        Layout.fillWidth: true
        spacing: 8

        PopupRow {
            label: "5h Tokens"
            value: rootItem.zaiTokenPct
            barColor: rootItem.zaiBlue
            etaText: rootItem.zaiTokenCountdown ? "resets in " + rootItem.zaiTokenCountdown : ""
            deltaText: rootItem.periodDelta("zai", value, 5 * 3600000, "last window")
            tokenText: zaiTabRoot.fmt(rootItem.zaiTokenUsed) + " / " + zaiTabRoot.fmt(rootItem.zaiTokenLimit)
            tooltipText: "Z.AI token quota"
        }

        PopupRow {
            label: "Monthly Tools"
            value: rootItem.zaiToolsPct
            barColor: rootItem.zaiBlue
            etaText: rootItem.zaiToolsCountdown ? "resets in " + rootItem.zaiToolsCountdown : ""
            deltaText: ""
            tokenText: rootItem.zaiToolsRemaining !== null ? zaiTabRoot.fmt(rootItem.zaiToolsRemaining) + " remaining" : "—"
            tooltipText: "Z.AI monthly tool quota"
        }

        Rectangle {
            visible: rootItem.zaiModels.length > 0
            Layout.fillWidth: true
            height: Math.min(rootItem.zaiModels.length, 5) * 34 + 42
            radius: 8
            color: Qt.rgba(0.07, 0.43, 0.96, 0.08)
            border.width: 1
            border.color: Qt.rgba(0.07, 0.43, 0.96, 0.22)

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                PlasmaComponents.Label {
                    text: "Model usage"
                    font.pixelSize: 11
                    font.bold: true
                    opacity: 0.75
                    color: Kirigami.Theme.textColor
                }

                Repeater {
                    model: rootItem.zaiModels.slice(0, 5)
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        PlasmaComponents.Label {
                            text: modelData.modelCode || "unknown"
                            font.pixelSize: 10
                            color: Kirigami.Theme.textColor
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        PlasmaComponents.Label {
                            text: zaiTabRoot.fmt(modelData.usage || 0)
                            font.pixelSize: 10
                            font.bold: true
                            color: rootItem.zaiBlue
                        }
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 2: Create `CopilotTab.qml`**

Create `package/contents/ui/CopilotTab.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: copilotTabRoot
    property Item rootItem

    visible: rootItem.enabledTabs[rootItem.activeTab] === "copilot" && !rootItem.showSettings
    Layout.fillWidth: true
    spacing: 14

    readonly property real remaining: Math.max(0, rootItem.copilotQuota - rootItem.copilotUsed)

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        visible: rootItem.copilotKeyValid

        Kirigami.Icon {
            source: "im-user"
            width: 14
            height: 14
            color: rootItem.copilotPurple
            isMask: true
            opacity: 0.75
        }

        PlasmaComponents.Label {
            text: rootItem.copilotUsername ? "GitHub · @" + rootItem.copilotUsername : "GitHub Copilot"
            font.pixelSize: 10
            opacity: 0.65
            color: Kirigami.Theme.textColor
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        Rectangle {
            height: 18
            width: copilotBadgeLabel.implicitWidth + 12
            radius: 4
            color: Qt.rgba(0.55, 0.36, 0.96, 0.18)
            border.width: 1
            border.color: Qt.rgba(0.55, 0.36, 0.96, 0.35)
            PlasmaComponents.Label {
                id: copilotBadgeLabel
                anchors.centerIn: parent
                text: "CONNECTED"
                font.pixelSize: 9
                font.bold: true
                color: rootItem.copilotPurple
            }
        }
    }

    ColumnLayout {
        visible: !rootItem.copilotKeyValid && rootItem._githubToken === ""
        Layout.fillWidth: true
        spacing: 6
        PlasmaComponents.Label {
            text: "Not connected"
            font.pixelSize: 12
            font.bold: true
            color: Kirigami.Theme.textColor
            opacity: 0.7
        }
        PlasmaComponents.Label {
            text: "Set a GitHub token in settings or via $GITHUB_TOKEN / ~/.config/github-copilot/token"
            font.pixelSize: 10
            opacity: 0.5
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    ColumnLayout {
        visible: rootItem.copilotError !== "" && !rootItem.copilotKeyValid
        Layout.fillWidth: true
        spacing: 6
        PlasmaComponents.Label {
            text: "Copilot error"
            font.pixelSize: 12
            font.bold: true
            color: "#ef4444"
        }
        PlasmaComponents.Label {
            text: rootItem.copilotError
            font.pixelSize: 10
            opacity: 0.7
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    ColumnLayout {
        visible: rootItem.copilotKeyValid
        Layout.fillWidth: true
        spacing: 8

        PopupRow {
            label: "Premium Requests"
            value: rootItem.copilotPct
            barColor: rootItem.copilotPurple
            etaText: rootItem.copilotCountdown ? "resets in " + rootItem.copilotCountdown : ""
            deltaText: rootItem.periodDelta("copilot", value, 30 * 24 * 3600000, "last month")
            tokenText: rootItem.copilotUsed.toFixed(rootItem.copilotUsed % 1 === 0 ? 0 : 1) + " / " + rootItem.copilotQuota
            tooltipText: "GitHub Copilot premium requests"
        }

        Rectangle {
            Layout.fillWidth: true
            height: copilotStatsCol.implicitHeight + 16
            radius: 8
            color: Qt.rgba(0.55, 0.36, 0.96, 0.08)
            border.width: 1
            border.color: Qt.rgba(0.55, 0.36, 0.96, 0.22)

            ColumnLayout {
                id: copilotStatsCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents.Label {
                        text: "Used"
                        font.pixelSize: 11
                        opacity: 0.65
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                    }
                    PlasmaComponents.Label {
                        text: rootItem.copilotUsed.toFixed(rootItem.copilotUsed % 1 === 0 ? 0 : 1)
                        font.pixelSize: 14
                        font.bold: true
                        color: rootItem.copilotPurple
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents.Label {
                        text: "Remaining"
                        font.pixelSize: 11
                        opacity: 0.65
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                    }
                    PlasmaComponents.Label {
                        text: copilotTabRoot.remaining.toFixed(copilotTabRoot.remaining % 1 === 0 ? 0 : 1)
                        font.pixelSize: 12
                        font.bold: true
                        color: rootItem.usageColor(rootItem.copilotPct)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents.Label {
                        text: "Reset"
                        font.pixelSize: 11
                        opacity: 0.65
                        color: Kirigami.Theme.textColor
                        Layout.fillWidth: true
                    }
                    PlasmaComponents.Label {
                        text: rootItem.copilotCountdown || "next month"
                        font.pixelSize: 12
                        color: Kirigami.Theme.textColor
                        opacity: 0.85
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 3: Verify tab files are referenced**

Run:

```bash
rg -n "ZaiTab|CopilotTab" package/contents/ui/main.qml package/contents/ui/ZaiTab.qml package/contents/ui/CopilotTab.qml
```

Expected: `main.qml` instantiates both components and both files exist.

- [ ] **Step 4: Checkpoint**

Record created tab files in the final task summary.

### Task 5: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `kde-store-description.md`
- Verify: whole package

- [ ] **Step 1: Update README feature list**

In `README.md`, update the service list sentence to include Z.AI and GitHub Copilot:

```markdown
A KDE Plasma 6 panel widget for tracking AI API quota usage across multiple services. Monitor your **Claude** (5-hour session & 7-day weekly), **Antigravity/Google AI Studio**, **OpenAI API**, **Kiro**, **Mistral AI**, **OpenRouter**, **Z.AI**, and **GitHub Copilot** usage at a glance with animated segmented bars, live countdown timers, account status, and per-model breakdowns where providers expose them.
```

Add supported-service sections:

```markdown
### Z.AI
- **5-hour token quota** — Shows current token usage percentage and reset countdown.
- **Monthly tools quota** — Shows tool usage percentage, remaining quota, reset countdown, and per-model usage details when returned by the API.
- **Credential lookup** — Reads the widget setting first, then `$ZAI_TOKEN`, then `~/.config/zai/token`.

### GitHub Copilot
- **Premium request usage** — Shows monthly premium request usage, quota, remaining requests, and reset countdown.
- **Configurable quota** — Defaults to 300 requests and can be changed in widget settings.
- **Credential lookup** — Reads the widget setting first, then `$GITHUB_TOKEN`, then `~/.config/github-copilot/token`.
- **Requires** — A GitHub token that can read Copilot premium request usage.
```

- [ ] **Step 2: Update requirements**

In `README.md`, add requirements rows:

```markdown
### For Z.AI Support
| Dependency | Notes |
|---|---|
| Z.AI token | Widget settings, `$ZAI_TOKEN`, or `~/.config/zai/token` |

### For GitHub Copilot Support
| Dependency | Notes |
|---|---|
| GitHub token | Widget settings, `$GITHUB_TOKEN`, or `~/.config/github-copilot/token` |
| Copilot quota | Optional; defaults to 300 monthly premium requests |
```

- [ ] **Step 3: Update KDE store description**

In `kde-store-description.md`, add Z.AI and GitHub Copilot to the provider list and credential notes using the same wording as README, shortened to match the file’s existing style.

- [ ] **Step 4: Run shell verification**

Run:

```bash
bash -n package/contents/tools/sh/get-zai-usage
bash -n package/contents/tools/sh/get-copilot-usage
env -u WIDGET_ZAI_TOKEN -u ZAI_TOKEN HOME="$(mktemp -d)" package/contents/tools/sh/get-zai-usage | jq -e 'type == "object" and length == 0'
env -u WIDGET_GITHUB_TOKEN -u GITHUB_TOKEN HOME="$(mktemp -d)" package/contents/tools/sh/get-copilot-usage | jq -e 'type == "object" and length == 0'
```

Expected: syntax checks print nothing; JSON checks print `true`.

- [ ] **Step 5: Run repository search checks**

Run:

```bash
rg -n "zaiEnabled|copilotEnabled|zaiToken|githubToken|copilotQuota|get-zai-usage|get-copilot-usage|ZaiTab|CopilotTab" package README.md kde-store-description.md
```

Expected: all new provider keys and files are represented in config, settings, main UI, helper invocation, docs, and tabs.

- [ ] **Step 6: Run package install test**

Run:

```bash
./test_install.sh
```

Expected: the test plasmoid installs or updates successfully. If the command fails because KDE packaging tools are absent, capture the exact missing command or error in the final summary.

- [ ] **Step 7: Final checkpoint**

Run:

```bash
find package/contents/tools/sh package/contents/ui package/contents/config -maxdepth 1 -type f | sort
```

Expected: new helper scripts and QML tabs are present. Summarize verification results and changed files.

## Self-Review Checklist

- The plan covers Z.AI helper, UI, settings, panel, tooltip, and chart support.
- The plan covers GitHub Copilot helper, UI, settings, panel, tooltip, and chart support.
- The plan excludes browser-cookie scraping, Python dependencies, and waybar config files.
- The plan includes concrete shell smoke tests and package verification.
- The plan uses explicit verification checkpoints only.
