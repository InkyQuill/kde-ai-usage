import datetime
import math

from ..contract import compact_tokens, flat_window, jround, monthly_window, num, pct_clamp, provider_base, provider_error, rolling_windows

# Anything at or above this, read as a duration, would be more than 31 years —
# so it is an absolute epoch instead. Live z.ai responses put an absolute
# millisecond timestamp in `nextResetTime`, despite the field name; treating it
# as a duration and adding it to `now` produced reset dates in the 2080s, which
# went unnoticed because the formatted string carries no year.
_ABSOLUTE_MS_FLOOR = 1000000000000


# Two decimals and an uppercase "K" to match how the vendor's dashboard prints
# the same figure — this number exists to be checked against that page, and a
# differently rounded one invites the reader to wonder which is wrong.
_ZAI_UNITS = (("B", 1000000000), ("M", 1000000), ("K", 1000))


def _compact(n):
    return compact_tokens(n, decimals=2, units=_ZAI_UNITS, trim_zeros=False)


def _today_label(today):
    """ "Today (Aug 12)" — the reset column already carries the date this rolls
    over to, and a bare "Today" next to tomorrow's date reads as a mismatch.
    Naming the day being summed removes the question."""
    date = str(today.get("date") or "")
    try:
        d = datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return "Today"
    return "Today (" + d.strftime("%b ") + str(d.day) + ")"


def _today_detail(today):
    """The value itself: "41.18M tokens", or "" if it did not come back."""
    return f"{_compact(today['tokens'])} tokens" if today.get("tokens") is not None else ""


def _today_note(today):
    """The aside: "370 calls". Tokens are what the quota is spent in, so they
    are the value; the call count is context for it."""
    return f"{num(today['calls'])} calls" if today.get("calls") is not None else ""


def _reset_at(value, now):
    """Reset epoch in seconds from a value that may be absolute or relative."""
    ms = num(value)
    if ms <= 0:
        return 0
    if ms >= _ABSOLUTE_MS_FLOOR:
        return math.floor(ms / 1000)
    return math.floor(now + ms / 1000)


def _credit_window(w, now):
    """One CREDIT_LIMIT window from the provider, shaped like `token` above."""
    if not isinstance(w, dict):
        return {"available": False, "pct": 0, "used": None, "total": None, "resetAt": 0}
    return {
        "available": True,
        "pct": pct_clamp(num(w.get("pct"))),
        "used": num(w.get("used")) if w.get("used") is not None else None,
        "total": num(w.get("total")) if w.get("total") is not None else None,
        "resetAt": _reset_at(w.get("resetMs"), now),
    }


def _credit_detail(w):
    if w["used"] is None or w["total"] is None:
        return ""
    return f"{_compact(w['used'])} / {_compact(w['total'])} credits"


def normalize_zai(raw):
    now = raw["now"]
    res = raw["inputs"].get("usage") or {}

    if not isinstance(res, dict) or not res:
        return provider_error("zai", "Z.AI", "#8a8f98", now, "Z.AI: no token configured", {"hasKey": False, "keyValid": False})
    if res.get("error") is not None:
        return provider_error(
            "zai",
            "Z.AI",
            "#8a8f98",
            now,
            f"Z.AI: {res['error']}",
            {"hasKey": res.get("hasKey") is True, "keyValid": res.get("keyValid") is True},
        )

    token_pct = pct_clamp(num(res.get("tokenPct")))
    token2_pct = pct_clamp(num(res.get("token2Pct")))
    tools_pct = pct_clamp(num(res.get("toolsPct")))
    token_reset = _reset_at(res.get("tokenResetMs"), now)
    token2_reset = _reset_at(res.get("token2ResetMs"), now)
    tools_reset = _reset_at(res.get("toolsResetMs"), now)
    token_detail = (
        f"{num(res.get('tokenUsed'))} / {num(res.get('tokenLimit'))} tokens"
        if res.get("tokenUsed") is not None and res.get("tokenLimit") is not None
        else ""
    )
    tools_detail = f"{num(res.get('toolsRemaining'))} remaining" if res.get("toolsRemaining") is not None else ""

    credits_raw = res.get("credits") if isinstance(res.get("credits"), dict) else {}
    credit_session = _credit_window(credits_raw.get("session"), now)
    credit_weekly = _credit_window(credits_raw.get("weekly"), now)
    # Coding plans report their quotas as credits; when they are present they
    # are the binding limits, and the token windows of a plain API account
    # would only repeat them as zeros.
    plan_windows = credit_session["available"] or credit_weekly["available"]
    if credit_session["available"]:
        summary_pct = credit_session["pct"]
    elif credit_weekly["available"]:
        summary_pct = credit_weekly["pct"]
    else:
        summary_pct = token_pct

    r = provider_base("zai", "Z.AI", "#8a8f98", now)
    r["summary"] = {"pct": summary_pct, "text": f"{jround(summary_pct)}%", "detail": res.get("level") or "", "hasChart": True}
    today = res.get("today") if isinstance(res.get("today"), dict) else None
    today_detail = _today_detail(today) if today else ""

    r["quotaWindows"] = []
    if credit_session["available"]:
        r["quotaWindows"].append(
            flat_window("zai_session", "5-hour credits", credit_session["pct"], credit_session["resetAt"], _credit_detail(credit_session), True)
        )
    if credit_weekly["available"]:
        r["quotaWindows"].append(
            flat_window("zai_weekly", "Weekly credits", credit_weekly["pct"], credit_weekly["resetAt"], _credit_detail(credit_weekly), True)
        )
    if not plan_windows:
        r["quotaWindows"].append(flat_window("zai_tokens", "5-hour tokens", token_pct, token_reset, token_detail, True))
        r["quotaWindows"].append(flat_window("zai_tokens_long", "7-day tokens", token2_pct, token2_reset, "", True))
    r["quotaWindows"].append(flat_window("zai_tools", "Monthly tools", tools_pct, tools_reset, tools_detail, True))
    if today_detail:
        # Consumption so far, not a share of anything, so it carries a value
        # instead of a meter. The reset column holds the date change, so a
        # total that has stopped growing (see _report_day) has a visible
        # horizon instead of looking stuck.
        r["quotaWindows"].append(
            flat_window("zai_today", _today_label(today), 0, num(today.get("rollsOverAt")), today_detail, False, note=_today_note(today))
        )
    start_plan = res.get("startPlan") if isinstance(res.get("startPlan"), dict) else None
    raw_balances = start_plan.get("balances") if start_plan is not None else None
    start_balances = [
        {
            "model": b.get("model") or "model",
            "used": num(b.get("used")),
            "total": num(b.get("total")),
            "resetAt": _reset_at(b.get("resetMs"), now),
        }
        for b in (raw_balances if isinstance(raw_balances, list) else [])
        if isinstance(b, dict)
    ]
    for i, b in enumerate(start_balances):
        # Same shape as the day total: a consumed amount with a reset horizon,
        # not a share of a meter. These buckets refill daily, which `note`
        # says because `resets daily` otherwise reads as an assumption.
        pct = (b["used"] / b["total"]) * 100 if b["total"] > 0 else 0
        detail = f"{_compact(b['used'])} / {_compact(b['total'])} tokens"
        r["quotaWindows"].append(flat_window(f"zai_start_{i}", b["model"], pct, b["resetAt"], detail, False, note="resets daily"))
    first_pct = credit_session["pct"] if credit_session["available"] else token_pct
    second_pct = credit_weekly["pct"] if credit_weekly["available"] else token2_pct
    second_kind = "credits (weekly)" if credit_weekly["available"] else "tokens (7d)"
    r["slots"] = [
        {"pct": first_pct, "color": "#8a8f98", "text": None, "tooltip": f"Z.AI credits (5h): {jround(first_pct)}%"},
        {"pct": second_pct, "color": "#a9aeb6", "text": None, "tooltip": f"Z.AI {second_kind}: {jround(second_pct)}%"},
        {"pct": tools_pct, "color": "#c5c9cf", "text": None, "tooltip": f"Z.AI tools: {jround(tools_pct)}%"},
    ]
    if plan_windows:
        # The same rolling windows Claude and Codex chart, on the credit
        # series, so the ETA and comparison machinery works unchanged.
        r["chartWindows"] = rolling_windows("zai_primary", "zai_day", "zai_weekly", "zs", "zw", credit_session, credit_weekly)
        r["historyValues"] = {
            **({"zs": credit_session["pct"]} if credit_session["available"] else {}),
            **({"zw": credit_weekly["pct"]} if credit_weekly["available"] else {}),
        }
    else:
        r["chartWindows"] = monthly_window("zai", "za", False)
        r["historyValues"] = {"za": token_pct}
    r["details"] = {
        "hasKey": res.get("hasKey") is True,
        "keyValid": res.get("keyValid") is True,
        "tokenSource": res.get("tokenSource") or "api",
        "level": res.get("level") or "",
        "credits": {
            "available": plan_windows,
            "session": credit_session,
            "weekly": credit_weekly,
        },
        "startPlan": {
            "available": start_plan is not None,
            "name": (start_plan or {}).get("name") or "",
            "balances": start_balances,
        },
        "token": {
            "pct": token_pct,
            "used": num(res.get("tokenUsed")) if res.get("tokenUsed") is not None else None,
            "limit": num(res.get("tokenLimit")) if res.get("tokenLimit") is not None else None,
            "resetAt": token_reset,
        },
        "tokenLong": {
            "pct": token2_pct,
            "resetAt": token2_reset,
        },
        "tools": {
            "pct": tools_pct,
            "remaining": num(res.get("toolsRemaining")) if res.get("toolsRemaining") is not None else None,
            "resetAt": tools_reset,
        },
        "models": res.get("models") or [],
        "today": {
            "available": today is not None,
            "date": (today or {}).get("date") or "",
            "rollsOverAt": num((today or {}).get("rollsOverAt")),
            "tokens": num((today or {}).get("tokens")) if (today or {}).get("tokens") is not None else None,
            "calls": num((today or {}).get("calls")) if (today or {}).get("calls") is not None else None,
            "models": [
                {"name": m.get("name") or "", "tokens": num(m.get("tokens"))} for m in ((today or {}).get("models") or []) if isinstance(m, dict)
            ],
            "tools": (today or {}).get("tools") or {},
        },
    }
    return r
