function unavailableWindow() {
    return { available: false, pct: 0, resetAt: null };
}

function finiteNumber(value) {
    return typeof value === "number" && isFinite(value);
}

function windowValue(pct, resetAt, active) {
    if (active === false || !finiteNumber(pct))
        return unavailableWindow();

    return {
        available: true,
        pct: pct,
        resetAt: resetAt === undefined ? null : resetAt
    };
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

    return {
        kind: kind,
        value: kind ? windowValue(pct, resetAt, true) : unavailableWindow()
    };
}

function assignCodexWindow(result, raw) {
    var classified = classifyCodexWindow(raw);
    if (classified.kind)
        result[classified.kind] = classified.value;
}

function normalizeCodex(payload) {
    var result = {
        session: unavailableWindow(),
        weekly: unavailableWindow(),
        additional: []
    };
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
            var entry = {
                name: snapshot.limitName || snapshot.limitId || id,
                session: unavailableWindow(),
                weekly: unavailableWindow(),
                limitReached: snapshot.rateLimitReachedType !== null && snapshot.rateLimitReachedType !== undefined
            };
            assignCodexWindow(entry, snapshot.primary);
            assignCodexWindow(entry, snapshot.secondary);
            result.additional.push(entry);
        }
    } else {
        var legacy = payload && payload.additional_rate_limits || [];
        for (var i = 0; i < legacy.length; i++) {
            var legacyRate = legacy[i].rate_limit || {};
            var legacyEntry = {
                name: legacy[i].limit_name || "Model " + (i + 1),
                session: unavailableWindow(),
                weekly: unavailableWindow(),
                limitReached: legacyRate.limit_reached === true
            };
            assignCodexWindow(legacyEntry, legacyRate.primary_window);
            assignCodexWindow(legacyEntry, legacyRate.secondary_window);
            result.additional.push(legacyEntry);
        }
    }

    return result;
}

function normalizeClaude(payload) {
    var result = {
        session: unavailableWindow(),
        weekly: unavailableWindow(),
        additional: []
    };
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

// Z.AI coding plans report CREDIT_LIMIT entries where `usage` is the window
// total, `currentValue` the spent amount, and `percentage` the utilization.
// The unit/number enums differ between tiers, so windows are classified by
// reset time instead: the soonest reset is the ~5h session window, the latest
// is the weekly one.
function normalizeZaiWindow(item) {
    if (!item || !finiteNumber(item.percentage))
        return null;

    return {
        available: true,
        pct: item.percentage,
        used: finiteNumber(item.currentValue) ? item.currentValue : null,
        total: finiteNumber(item.usage) ? item.usage : null,
        resetAt: finiteNumber(item.nextResetTime) ? item.nextResetTime : null
    };
}

function normalizeZai(payload) {
    var result = {
        session: unavailableWindow(),
        weekly: unavailableWindow()
    };
    var limits = payload && payload.limits || [];
    var windows = [];
    for (var i = 0; i < limits.length; i++) {
        if ((limits[i] || {}).type !== "CREDIT_LIMIT")
            continue;

        var window = normalizeZaiWindow(limits[i]);
        if (window)
            windows.push(window);
    }

    windows.sort(function (a, b) {
        return (a.resetAt === null ? Infinity : a.resetAt) - (b.resetAt === null ? Infinity : b.resetAt);
    });
    if (windows.length > 0)
        result.session = windows[0];

    if (windows.length > 1)
        result.weekly = windows[windows.length - 1];

    return result;
}

function chartChoices(provider, sessionAvailable, weeklyAvailable) {
    var result = [];
    if (provider === "zai") {
        if (sessionAvailable) {
            result.push({
                id: "zai_primary",
                label: "5H"
            });
            result.push({
                id: "zai_day",
                label: "24H"
            });
        }

        if (weeklyAvailable) {
            result.push({
                id: "zai_weekly",
                label: "7D"
            });
        }

        // Without plan windows keep the legacy 30-day API-token trend.
        if (result.length === 0)
            result.push({
                id: "zai",
                label: "30D"
            });

        return result;
    }

    if (sessionAvailable) {
        result.push({
            id: provider === "openai" ? "codex_primary" : "session",
            label: "5H"
        });
        result.push({
            id: provider === "openai" ? "codex_day" : "day",
            label: "24H"
        });
    }

    if (weeklyAvailable) {
        result.push({
            id: provider === "openai" ? "codex_weekly" : "weekly",
            label: "7D"
        });
    }

    return result;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        chartChoices: chartChoices,
        normalizeClaude: normalizeClaude,
        normalizeCodex: normalizeCodex,
        normalizeZai: normalizeZai
    };
}
