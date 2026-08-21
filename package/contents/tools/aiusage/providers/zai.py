"""Resolve a Z.AI token and fetch quota/limit data.

Ported from tools/sh/get-zai-usage.
"""

import datetime
import os

from ..http import as_json, error_json, fetch_json, http_error_json, resolve_key

# The API rejects ISO-8601 with a "T" separator by name, asking for this.
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_BALANCE_URL = "https://zcode.z.ai/api/v1/zcode-plan/billing/balance?app_version=3.7.7"


def _report_day():
    """Today's date as the API wants it, plus the epoch at which it changes.

    The bounds are the plain local calendar date, deliberately sent without
    timezone conversion — that is what the vendor's own dashboard does, and
    matching it is the point of the figure. Verified against a live account:
    the string "2026-08-11" returned 41,175,632 tokens with a per-model split
    of 36.11M / 5.06M / 2.41K, which is what the dashboard showed for that day
    down to the last digit.

    The service applies those bounds on their own clock, which runs ahead of
    Europe, so the day being summed is shifted by some hours and the total
    stops growing before local midnight. That shift is the vendor's, not ours;
    converting it away would produce a number the account holder cannot find
    anywhere.
    """
    today = datetime.date.today()
    start = datetime.datetime.combine(today, datetime.time(0, 0, 0))
    end = datetime.datetime.combine(today, datetime.time(23, 59, 59))
    rolls_over = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(0, 0, 0))
    return start.strftime(_TIME_FORMAT), end.strftime(_TIME_FORMAT), int(rolls_over.timestamp())


def _fetch_window(path, api_key, start, end, fixture_env):
    """One monitor time-series call. Returns its `data` object, or None."""
    from urllib.parse import quote

    result = fetch_json(
        f"https://api.z.ai/api/monitor/usage/{path}?startTime={quote(start)}&endTime={quote(end)}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "kde-ai-usage/zai",
        },
        timeout=10,
        fixture_path=os.environ.get(fixture_env),
    )
    if result.status != 200:
        return None
    body = as_json(result.body)
    if not isinstance(body, dict) or body.get("success") is not True:
        return None
    data = body.get("data")
    return data if isinstance(data, dict) else None


def _today_usage(api_key):
    """Today's totals, or None. Never raises the caller's failure mode: the
    quota windows are the point of this provider, and losing an extra
    statistic must not cost us those."""
    start, end, rolls_over = _report_day()
    models = _fetch_window("model-usage", api_key, start, end, "ZAI_MODEL_USAGE_RESPONSE_FILE")
    tools = _fetch_window("tool-usage", api_key, start, end, "ZAI_TOOL_USAGE_RESPONSE_FILE")
    if models is None and tools is None:
        return None

    totals = (models or {}).get("totalUsage") or {}
    tool_totals = (tools or {}).get("totalUsage") or {}
    summary = (models or {}).get("modelSummaryList")
    return {
        "date": start[:10],
        "rollsOverAt": rolls_over,
        "tokens": totals.get("totalTokensUsage"),
        "calls": totals.get("totalModelCallCount"),
        "models": [
            {"name": m.get("modelName") or "", "tokens": m.get("totalTokens")}
            for m in (summary if isinstance(summary, list) else [])
            if isinstance(m, dict)
        ],
        "tools": {
            "search": tool_totals.get("totalNetworkSearchCount"),
            "reader": tool_totals.get("totalWebReadMcpCount"),
            "zread": tool_totals.get("totalZreadMcpCount"),
        },
    }


def _glm_acp_key():
    """The key `glm-acp-agent --setup` stores, read as a last resort.

    That ACP agent (used from Zed and other ACP clients) talks to the same
    Z.AI coding plan with the same key, and its setup command is where a lot
    of people paste it. Without this, a machine can hold a perfectly valid
    credential while this provider still reports "no token configured" —
    which is what happened to me. Same courtesy `_vibe_key` extends to
    Mistral, and it ranks last so an explicit token always wins.
    """
    path = os.path.expanduser("~/.config/glm-acp-agent/credentials.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, errors="replace") as f:
            data = as_json(f.read())
    except OSError:
        return ""
    key = data.get("z_ai_api_key") if isinstance(data, dict) else None
    return key.strip() if isinstance(key, str) else ""


def _zcode_credentials():
    """The ZCode desktop app's own session, read as the very last resort.

    The app authenticates against the same Z.AI account (`oauth:zai:*`) and
    keeps a long-lived access token plus a separate JWT for its plan APIs in
    plain JSON, so a machine that is simply logged in holds a working
    credential this provider can use without anything being pasted into
    settings. The JWT unlocks the free Start Plan balance endpoint, which the
    API token itself cannot reach. `WIDGET_ZCODE_CREDENTIALS` lets a test (or
    a user) point somewhere else.
    """
    path = os.environ.get("WIDGET_ZCODE_CREDENTIALS") or os.path.expanduser("~/.zcode/v2/credentials.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, errors="replace") as f:
            data = as_json(f.read())
    except OSError:
        return None
    if not isinstance(data, dict):
        return None
    access = data.get("oauth:zai:access_token")
    access = access.strip() if isinstance(access, str) else ""
    if not access:
        return None
    jwt = data.get("zcodejwttoken")
    return {"access_token": access, "zcode_jwt": jwt.strip() if isinstance(jwt, str) else ""}


def _zai_key():
    """The credential search, as one callable so the tests exercise the same
    order production does instead of restating it. Returns the key, where it
    came from ("api" or "zcode"), and the ZCode JWT when there is one."""
    key = resolve_key(
        "WIDGET_ZAI_TOKEN",
        ("ZAI_TOKEN", "Z_AI_API_KEY"),
        os.path.expanduser("~/.config/zai/token"),
        os.path.expanduser("~/.zai/token"),
    )
    if key:
        return key, "api", ""
    key = _glm_acp_key()
    if key:
        return key, "api", ""
    zcode = _zcode_credentials()
    if zcode:
        return zcode["access_token"], "zcode", zcode["zcode_jwt"]
    return "", "api", ""


def _credit_windows(limits):
    """Coding-plan CREDIT_LIMIT windows: the soonest reset is the ~5-hour
    session, the latest the weekly one.

    Coding plans (GLM Coding Lite/Pro/Max) report their quotas as credits
    where `usage` is the window total, `currentValue` the spent amount and
    `percentage` the utilization. The unit and number enums differ between
    tiers, so the windows are told apart by reset time rather than by any
    unit field — the same classification the frontend's old UsageWindows.js
    made.
    """
    windows = [
        {
            "pct": lim.get("percentage") or 0,
            "used": lim.get("currentValue"),
            "total": lim.get("usage"),
            "resetMs": lim.get("nextResetTime"),
        }
        for lim in limits
        if lim.get("type") == "CREDIT_LIMIT"
    ]
    windows.sort(key=lambda w: w["resetMs"] if isinstance(w["resetMs"], (int, float)) else 0)
    if not windows:
        return {"session": None, "weekly": None}
    return {"session": windows[0], "weekly": windows[-1] if len(windows) > 1 else None}


def _start_plan(zcode_jwt):
    """Free Start Plan token buckets, or None. Only the app's own JWT can
    reach this endpoint, which is why it is fetched for auto-detected
    credentials only. Never fatal: it is a bonus beside the quota windows."""
    if not zcode_jwt:
        return None
    result = fetch_json(
        _BALANCE_URL,
        headers={
            "Authorization": f"Bearer {zcode_jwt}",
            "Accept": "application/json",
            "User-Agent": "kde-ai-usage/zai",
        },
        timeout=10,
        fixture_path=os.environ.get("ZCODE_BALANCE_RESPONSE_FILE"),
    )
    if result.status != 200:
        return None
    body = as_json(result.body)
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else None
    if data is None:
        return None
    plans = [p for p in (data.get("plans") or []) if isinstance(p, dict) and p.get("status") == "active"]
    balances = [
        {
            "model": b.get("show_name") or "model",
            "used": b.get("used_units") or 0,
            "total": b.get("total_units") or 0,
            "resetMs": (b.get("period_end") or 0) * 1000,
        }
        for b in (data.get("balances") or [])
        if isinstance(b, dict) and (b.get("total_units") or 0) > 0
    ]
    if not plans or not balances:
        return None
    return {"name": plans[0].get("name") or "", "balances": balances}


def get_zai_usage():
    api_key, source, zcode_jwt = _zai_key()
    if not api_key:
        return {}

    result = fetch_json(
        "https://api.z.ai/api/monitor/usage/quota/limit",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "kde-ai-usage/zai",
        },
        timeout=10,
        fixture_path=os.environ.get("ZAI_RESPONSE_FILE"),
    )
    if result.status != 200:
        # A ZCode-app session that has expired reads very differently to its
        # owner than a pasted token gone bad, and the fix is different too.
        message = "ZCode session expired — log in again in the ZCode app" if source == "zcode" else "Invalid Z.AI token"
        error = http_error_json("Z.AI", result.status, message)
        error["hasKey"] = True
        error["tokenSource"] = source
        return error

    start_plan = _start_plan(zcode_jwt) if source == "zcode" else None

    body = as_json(result.body)
    if body is None:
        return error_json("Z.AI invalid JSON")

    if body.get("success") is False:
        # The quota endpoint can reject the app's access token while the plan
        # itself is alive; the Start Plan buckets are then the whole story.
        if start_plan is not None:
            return {"hasKey": True, "keyValid": True, "tokenSource": source, "credits": {"session": None, "weekly": None}, "startPlan": start_plan}
        return {"hasKey": True, "keyValid": False, "error": body.get("msg") or "Z.AI API error"}

    data = body.get("data") if isinstance(body.get("data"), dict) else None
    limits = data.get("limits") if data and isinstance(data.get("limits"), list) else None
    has_expected = limits is not None and any(lim.get("type") in ("TOKENS_LIMIT", "TIME_LIMIT", "CREDIT_LIMIT") for lim in limits)

    if body.get("success") is True and has_expected:
        # Z.AI exposes multiple TOKENS_LIMIT windows (a short ~5-hour AND a
        # longer ~weekly one). Upstream took only the first via next() and
        # silently dropped the second; collect all in API order instead.
        tok_windows = [lim for lim in limits if lim.get("type") == "TOKENS_LIMIT"]
        tok = tok_windows[0] if tok_windows else {}
        tok2 = tok_windows[1] if len(tok_windows) > 1 else {}
        tools = next((lim for lim in limits if lim.get("type") == "TIME_LIMIT"), {})
        return {
            "hasKey": True,
            "keyValid": True,
            "tokenSource": source,
            "level": data.get("level") or "",
            "credits": _credit_windows(limits),
            "startPlan": start_plan,
            "tokenPct": tok.get("percentage") or 0,
            "tokenResetMs": tok.get("nextResetTime"),
            "tokenUsed": tok.get("used") if tok.get("used") is not None else tok.get("usage"),
            "tokenLimit": tok.get("limit") if tok.get("limit") is not None else tok.get("total"),
            "token2Pct": tok2.get("percentage") or 0,
            "token2ResetMs": tok2.get("nextResetTime"),
            "toolsPct": tools.get("percentage") or 0,
            "toolsRemaining": tools.get("remaining"),
            "toolsResetMs": tools.get("nextResetTime"),
            "models": tools.get("usageDetails") or [],
            "today": _today_usage(api_key),
        }
    if start_plan is not None:
        return {"hasKey": True, "keyValid": True, "tokenSource": source, "credits": {"session": None, "weekly": None}, "startPlan": start_plan}
    return {"hasKey": True, "keyValid": False, "error": "Z.AI unexpected response"}
