"""Forecast GTA VI's launch-day Twitch viewers hour by hour (make.fun).

Reads one case file at a time from the input directory (each a
makefun/twitch-ccu-case/v1 object: hour 1's print plus the launch's
history and a library of past big launches) and writes one forecast
file per case to the output directory: for each of hours 2..24, five
quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent viewers
in the game's Twitch category.

Model, in log space, per hour h of the release day:
  - Each past launch in the case's comparables gives a log-ratio curve
    ln(viewers_h / viewers_1). Launches whose category was nearly empty
    at midnight (hour-1 print under 2,000) are left out: their hour 1
    is not a launch hour at all, and their ratios are wild.
  - The centre curve is the median of the library's log-ratio curves.
  - Two adjustments move that centre for this launch, fitted by least
    squares on the library and shrunk by a factor of 0.75:
      * the launch's size: log-ratio curves fall as hour 1 grows
        (a launch that already draws 800k viewers at 01:00 UTC has
        little room left to grow; one at 20k can grow tenfold). The
        hour-1 deviation is winsorised to +/-1.5 log units so the fit
        is never extrapolated far past the launches it was fitted on.
      * the unlock pattern: launches that unlock at midnight local
        time, rolling around the world, build through the day as each
        region wakes and unlocks; launches with one simultaneous
        global unlock spike early and fade. The case's notes say which
        pattern this launch follows.
  - The five quantiles sit on a normal spread of 0.35 log units around
    the centre: q_tau = p1 * exp(centre_h + z_tau * 0.35).

Standard library only, no network, no clock, no randomness: the same
case always yields the same bytes. If the library is empty or the fit
fails, the forecast falls back to persistence (every hour at hour 1's
print, spread widening like a random walk), so the program still
writes a valid file.
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels.
Z_SCORES = [-1.645, -0.674, 0.0, 0.674, 1.645]

# A comparable whose hour-1 print is below this is not a launch hour:
# the category was essentially empty at midnight, so its ratios are
# not comparable to a real launch's.
MIN_HOUR_ONE = 2000
# How far the hour-1 size adjustment may reach, in log units, past
# the library's centre: the fit is linear, so beyond this the
# extrapolation is capped instead of trusted.
SIZE_WINSOR = 1.5
# Shrinkage applied to the fitted adjustments (0 = the plain median
# curve, 1 = the full least-squares fit).
SHRINK = 0.75
# Log-space spread of the five quantiles around the centre.
SPREAD = 0.35
# Fallback spread (random-walk widening) when the library is unusable.
FALLBACK_SIGMA = 0.15


def parse_time(text):
    """An ISO 8601 UTC instant such as 2026-11-19T00:00:00Z."""
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))


def normal_quantile(probability):
    """The standard normal's quantile at probability, by Acklam's
    rational approximation (accurate to about 1e-9). Only used when
    a case asks for levels other than the standard five; the
    standard levels use the house baseline's rounded z-scores."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285984469534e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    p_low = 0.02425
    if probability < p_low:
        q = math.sqrt(-2 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if probability <= 1 - p_low:
        q = probability - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
        )
    q = math.sqrt(-2 * math.log(1 - probability))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def z_scores_for(levels):
    """Normal quantiles for the case's levels: the house baseline's
    rounded values for the standard five, Acklam's approximation
    otherwise."""
    if levels == LEVELS:
        return Z_SCORES
    return [normal_quantile(level) for level in levels]


def round_half_up_2dp(value):
    """Round to 2 decimals, halves away from zero (matches the
    house baseline's rounding, so outputs compare cleanly)."""
    scaled = math.floor(value * 100 + 0.5)
    out = scaled / 100
    return int(out) if out == int(out) else out


def is_rolling_unlock(unlock_note):
    """True when a launch unlocked at midnight local time, rolling
    around the world, rather than in one simultaneous global moment."""
    text = (unlock_note or "").lower()
    return "rolling" in text or "midnight local" in text


def release_day_curve(comparable):
    """A past launch's hourly viewers for its release day, keyed by
    hour 1..24, or None when the day is incomplete or degenerate."""
    day_start = parse_time(comparable["day_start"])
    by_hour = {}
    for row in comparable.get("hourly", []):
        try:
            viewers = row["viewers"]
            when = parse_time(row["from"])
        except (KeyError, TypeError, ValueError):
            continue
        hour = int((when - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24 and viewers is not None:
            by_hour[hour] = viewers
    if len(by_hour) != 24:
        return None
    first = by_hour.get(1)
    if not first or first < MIN_HOUR_ONE:
        return None
    if any(not v or v <= 0 for v in by_hour.values()):
        return None
    return by_hour


def build_library(case):
    """The usable past launches: each a dict with its hour-1 print,
    its rolling-unlock flag, and its 23 log-ratio values for hours
    2..24."""
    library = []
    for comparable in case.get("comparables", []):
        day = release_day_curve(comparable)
        if day is None:
            continue
        first = day[1]
        library.append(
            {
                "log_first": math.log(first),
                "rolling": 1 if is_rolling_unlock(comparable.get("unlock")) else 0,
                "ratios": [math.log(day[h] / first) for h in range(2, 25)],
            }
        )
    return library


def solve_two_by_two(a11, a12, a22, b1, b2):
    """Solve [[a11, a12], [a12, a22]] x = [b1, b2]; None when the
    system is singular."""
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return None
    return ((b1 * a22 - b2 * a12) / det, (b2 * a11 - b1 * a12) / det)


def fit_hour(library, hour_index, centre_log_first, centre_rolling):
    """Least-squares slopes of one hour's log-ratio on (log hour-1,
    rolling flag), both centred, for the library's launches."""
    xs_size = [entry["log_first"] for entry in library]
    xs_roll = [entry["rolling"] for entry in library]
    ys = [entry["ratios"][hour_index] for entry in library]
    middle_y = statistics.median(ys)
    s11 = sum((x - centre_log_first) ** 2 for x in xs_size)
    s22 = sum((x - centre_rolling) ** 2 for x in xs_roll)
    s12 = sum(
        (a - centre_log_first) * (b - centre_rolling)
        for a, b in zip(xs_size, xs_roll)
    )
    t1 = sum((x - centre_log_first) * (y - middle_y) for x, y in zip(xs_size, ys))
    t2 = sum((x - centre_rolling) * (y - middle_y) for x, y in zip(xs_roll, ys))
    slopes = solve_two_by_two(s11, s12, s22, t1, t2)
    return slopes if slopes is not None else (0.0, 0.0)


def target_is_rolling(case):
    """Whether this launch unlocks at midnight local, rolling around
    the world. The case's notes state the real unlock; a console
    launch in this competition unlocks that way, so when the notes
    say nothing the answer defaults to rolling.

    Positive evidence wins: a note can deny a simultaneous launch
    ("rolling, no simultaneous launch") while still describing a
    rolling one, so "rolling" is checked before "simultaneous"."""
    notes = (case.get("notes") or "").lower()
    if "rolling" in notes or "midnight local" in notes:
        return 1
    if "simultaneous" in notes or "single global" in notes:
        return 0
    return 1


def centre_curve(library):
    """The median log-ratio curve of the library, one value per hour
    2..24, plus the centres the slopes are measured from."""
    middle = [
        statistics.median([entry["ratios"][i] for entry in library])
        for i in range(23)
    ]
    centre_log_first = statistics.median(
        [entry["log_first"] for entry in library]
    )
    centre_rolling = statistics.mean([entry["rolling"] for entry in library])
    return middle, centre_log_first, centre_rolling


def forecast_case(case, name):
    """The 23 forecast rows for one case."""
    levels = case.get("levels") or LEVELS
    z_scores = z_scores_for(levels)
    known = [row for row in case.get("known", []) if row.get("hour") == 1]
    if not known:
        raise ValueError(f"{name} has no hour-1 print")
    first_print = known[0]["viewers"]
    if not first_print or first_print <= 0:
        first_print = 1
    hours = [row["hour"] for row in case.get("forecast", [])]
    if not hours:
        hours = list(range(2, 25))

    library = build_library(case)
    if len(library) < 5:
        # Too little to fit on: persistence with a widening spread.
        rows = []
        for hour in hours:
            spread = FALLBACK_SIGMA * math.sqrt(max(hour - 1, 0))
            rows.append(
                {
                    "hour": hour,
                    "q": [
                        round_half_up_2dp(
                            max(0.01, min(1e9, first_print * math.exp(z * spread)))
                        )
                        for z in z_scores
                    ],
                }
            )
        return {"hours": rows}

    middle, centre_log_first, centre_rolling = centre_curve(library)
    size_deviation = math.log(first_print) - centre_log_first
    size_deviation = max(-SIZE_WINSOR, min(SIZE_WINSOR, size_deviation))
    rolling_here = target_is_rolling(case)
    rolling_deviation = rolling_here - centre_rolling

    rows = []
    for hour in hours:
        index = hour - 2
        slope_size, slope_rolling = fit_hour(
            library, index, centre_log_first, centre_rolling
        )
        centre = middle[index] + SHRINK * (
            slope_size * size_deviation + slope_rolling * rolling_deviation
        )
        quantiles = []
        previous = 0.0
        for z in z_scores:
            value = first_print * math.exp(centre + z * SPREAD)
            value = max(0.01, min(1e9, value))
            value = round_half_up_2dp(value)
            # Rounding can only tie neighbours; keep the row ordered.
            value = max(value, previous)
            quantiles.append(value)
            previous = value
        rows.append({"hour": hour, "q": quantiles})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
