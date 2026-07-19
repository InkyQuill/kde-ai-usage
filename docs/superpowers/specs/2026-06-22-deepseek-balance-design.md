# DeepSeek Balance Provider Design

Date: 2026-06-22

## Goal

Add DeepSeek as a balance-only provider in the KDE Plasma AI Usage widget.

## Behavior

- Fetch `GET https://api.deepseek.com/user/balance` with bearer authentication.
- Resolve credentials from widget settings, then `$DEEPSEEK_API_KEY`, then `~/.config/deepseek/api-key`.
- Show account availability, total balance, granted balance, and topped-up balance.
- Prefer USD when DeepSeek returns multiple currencies; otherwise use the first returned currency.
- Store the primary balance as a raw chart value and auto-scale the chart for the visible window.

## Scope

DeepSeek has no coding-plan quota in this widget. The tab must not invent usage limits or reset times.
