# KDE AI Usage Direct-Token Provider Design

Date: 2026-06-22

## Goal

Add Z.AI and GitHub Copilot support to the KDE Plasma AI Usage widget as first-class providers. The implementation adapts the behavior from the waybar sources, but remains KDE-centric: no waybar config files, no Python runtime requirement, and no browser-cookie scraping.

## Scope

In scope:

- Add Z.AI usage tracking.
- Add GitHub Copilot premium request tracking.
- Add provider toggles and credential settings in the KDE widget settings.
- Add panel, popup, tooltip, and chart support for both providers.
- Use the existing helper-script plus QML `DataSource` architecture.

Out of scope:

- OpenCode Zen support.
- Browser-cookie based Copilot fallback.
- A generic provider runtime or plugin framework.
- Reading `~/.config/waybar-ai-usage/*.conf`.
- Refactoring existing providers beyond changes needed to integrate the new tabs.

## Architecture

The implementation will follow the existing provider pattern used by Mistral and OpenRouter.

New helper scripts:

- `package/contents/tools/sh/get-zai-usage`
- `package/contents/tools/sh/get-copilot-usage`

New QML tabs:

- `package/contents/ui/ZaiTab.qml`
- `package/contents/ui/CopilotTab.qml`

Updated files:

- `package/contents/ui/main.qml`
- `package/contents/ui/SettingsPanel.qml`
- `package/contents/ui/KeyRow.qml`
- `package/contents/config/main.xml`
- `README.md`
- `kde-store-description.md`

`main.qml` will gain provider state, tab routing, polling, panel slots, tooltip lines, colors, and chart recording for the two new providers. The settings UI will expose enable switches and credential fields.

## Credential Lookup

Credential lookup is KDE-centric and does not depend on waybar files.

Z.AI token precedence:

1. KDE widget setting, passed as `WIDGET_ZAI_TOKEN`
2. `ZAI_TOKEN`
3. `~/.config/zai/token`

GitHub Copilot token precedence:

1. KDE widget setting, passed as `WIDGET_GITHUB_TOKEN`
2. `GITHUB_TOKEN`
3. `~/.config/github-copilot/token`

GitHub Copilot quota precedence:

1. KDE widget setting
2. `COPILOT_QUOTA`
3. Default `300`

Tokens from KDE settings will be passed to shell helpers using the existing base64-decoded environment assignment pattern, so shell metacharacters in credentials do not break command execution. Tokens must not be rendered in the UI or logs.

## Z.AI Data Model

The Z.AI helper will query:

- `GET https://api.z.ai/api/monitor/usage/quota/limit`
- Header: `Authorization: Bearer <token>`
- Header: `Accept: application/json`

The helper will extract the API response's `data.limits` array:

- `TOKENS_LIMIT` becomes the 5-hour token quota.
- `TIME_LIMIT` becomes the monthly tools quota.

QML state includes:

- `zaiKeyValid`
- `zaiLevel`
- `zaiTokenPct`
- `zaiTokenResetTime`
- `zaiTokenCountdown`
- `zaiTokenUsed`
- `zaiTokenLimit`
- `zaiToolsPct`
- `zaiToolsRemaining`
- `zaiToolsResetTime`
- `zaiToolsCountdown`
- `zaiModels`
- `zaiError`

If the payload does not include token used/limit fields, the UI shows percentage and reset data without inventing values.

## Z.AI UI

Panel:

- Primary bar: 5-hour token percentage.
- Tooltip: token percentage/reset plus monthly tools percentage/remaining/reset.

Popup:

- Dedicated `ZaiTab.qml`.
- Primary `PopupRow`: "5h Tokens".
- Secondary `PopupRow`: "Monthly Tools".
- Compact model usage list from `usageDetails` when present.
- Connection state badge: connected, invalid token, or not connected.

Chart:

- Record the token percentage as the primary Z.AI history value.
- Keep the chart scale at 0-100%.

## GitHub Copilot Data Model

The Copilot helper will use token-based GitHub API access only.

Request flow:

1. `GET https://api.github.com/user` to determine the authenticated username.
2. `GET https://api.github.com/users/<username>/settings/billing/premium_request/usage` to fetch premium request usage.

Headers:

- `Authorization: Bearer <token>`
- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`

The helper will sum `grossQuantity` values from either:

- a list response, or
- a response object containing `usageItems`.

QML state includes:

- `copilotKeyValid`
- `copilotUsername`
- `copilotUsed`
- `copilotQuota`
- `copilotPct`
- `copilotResetTime`
- `copilotCountdown`
- `copilotError`

The reset time is the first day of the next month at 00:00 UTC.

## GitHub Copilot UI

Panel:

- Primary bar: premium request percentage.
- Tooltip: used/quota, percentage, and next monthly reset.

Popup:

- Dedicated `CopilotTab.qml`.
- Primary `PopupRow`: "Premium Requests".
- Stats card for used, quota, remaining, and reset.
- Empty state explaining that a GitHub token is required.
- Auth error state explaining that the token must have access to the premium request usage endpoint.

Chart:

- Record `copilotPct` as a 0-100% history series.

## Error Handling

Helper scripts must always print valid JSON.

Expected outputs:

- Missing credentials: `{}`
- Invalid credentials: JSON with `keyValid: false` and `error`
- Network/API failure: JSON with `keyValid: false` and a provider-specific `error`
- Success: provider-specific fields plus `keyValid: true`

QML behavior:

- `{}` renders "not connected".
- Invalid credentials and network failures set the provider error, global `errorMsg`, and stale state when prior data exists.
- Successful responses clear provider error and global error state, update `lastUpdate`, and record chart history.

Shell helper behavior:

- Use `curl --max-time`.
- Handle HTTP status explicitly.
- Use `jq` for JSON shaping.
- Avoid printing tokens.

## Verification

Before claiming implementation complete:

- Run `bash -n` on new and modified shell helpers.
- Smoke test missing-token behavior and confirm output is valid JSON.
- Smoke test helper parsing with representative saved/mock API payloads if live credentials are unavailable.
- Run QML formatting or syntax-level checks if local KDE/QML tooling is available.
- Run `./test_install.sh` if local Plasma packaging tools are available.
- If a verification step is unavailable, report it explicitly.

## Acceptance Criteria

- Z.AI can be enabled from settings and displays token quota, tools quota, reset countdowns, and model details when available.
- GitHub Copilot can be enabled from settings and displays premium request usage, quota, remaining requests, percentage, and reset countdown.
- Both providers have panel slots, popup tabs, tooltips, and chart history.
- Missing credentials produce a clear not-connected state.
- Invalid credentials produce a clear provider-specific error state.
- The widget does not require waybar, Python, browser cookies, or waybar config files for these providers.
