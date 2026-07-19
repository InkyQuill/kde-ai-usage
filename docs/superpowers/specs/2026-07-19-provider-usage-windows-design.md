# Provider Usage Window Compatibility

## Goal

Show only the usage windows that OpenAI Codex and Anthropic Claude currently report, without deleting support for the legacy five-hour window. A window must never be labelled from its position in a response; its provider metadata or duration determines its meaning.

## Current provider behavior

- The current Codex rate-limit snapshot contains a single 10,080-minute weekly window and no secondary window. The widget currently mislabels this primary window as five hours.
- Anthropic still reports a five-hour session limit. Its current response also exposes semantic entries in `limits[]`; the legacy top-level `seven_day` value may be null even when weekly information is available in that array.
- Both subscription-usage sources are separate from OpenAI and Anthropic API billing usage. Their response contracts may change independently of the public billing APIs.

## Data normalization

The widget will normalize provider-specific payloads into semantic session and weekly windows with an explicit availability flag, percentage, and reset date. A window is available only when its payload exists and contains a finite numeric percentage; an inactive or null-valued placeholder is unavailable.

For Codex, the preferred source is the local Codex app-server `account/rateLimits/read` snapshot. Its `primary` and `secondary` objects are classified from `windowDurationMins`. The existing authenticated web endpoint remains a compatibility fallback and is classified from `limit_window_seconds`. A 300-minute/18,000-second window is a session window; a 10,080-minute/604,800-second window is weekly. Unknown durations are not guessed or displayed.

For Claude, entries in `limits[]` are selected by semantic identifiers: `session` for the five-hour window and `weekly` or `weekly_scoped` for the weekly window. The widget falls back to the legacy `five_hour` and `seven_day` objects when the new entries are absent. The new `percent` field and legacy `utilization` field normalize to the same percentage property.

## Compatibility and deprecation

Existing five-hour QML properties, stored history keys (`s` and `cp`), and legacy payload parsing remain in place. They are marked as deprecated compatibility surfaces and populated only when a real five-hour window exists. This allows five-hour UI to return automatically if either provider reports that window again.

Existing Codex `primary` and `secondary` properties remain available during the transition, but presentation code uses semantic session and weekly properties. No saved history is deleted or rewritten.

## Presentation behavior

- Hide a five-hour popup row when its session window is unavailable.
- Hide a weekly popup row when its weekly window is unavailable.
- Apply the same rule to per-model Codex limit rows.
- Hide the corresponding panel slot and separator when a window is unavailable.
- For a weekly-only Codex account, show one weekly `7D` panel slot; do not show a zero-valued or mislabeled five-hour slot.
- Hide five-hour and 24-hour chart selectors when no current session window exists. Retain stored session history so selectors can reappear if session limits return.
- Tooltips, countdowns, ETA, and comparison text use the semantic window rather than provider field position.

## Failure handling

If the preferred Codex app-server lookup is unavailable, the widget falls back to the existing web usage request. If neither source yields a recognized window, plan-limit rows remain hidden while login identity and API billing information continue to work.

Malformed or unknown windows are ignored rather than displayed under an inferred label. A provider fetch failure retains the widget's existing stale/error behavior.

## Testing and verification

Parser-focused tests will cover:

- a current weekly-only Codex snapshot;
- a legacy Codex response with five-hour and weekly windows;
- reversed Codex window positions to prove duration-based classification;
- unknown Codex durations, which must remain hidden;
- current Claude `limits[]` session and weekly entries;
- legacy Claude `five_hour` and `seven_day` entries;
- missing session or weekly data and the resulting availability flags.

Widget verification will additionally check QML syntax/build validation, package creation, and the visible row/slot conditions for weekly-only and two-window fixtures.
