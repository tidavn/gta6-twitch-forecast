# gta6-twitch-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tidavn/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/tidavn/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts GTA VI's launch-day Twitch concurrent viewers hour by hour (hours 2–24, five quantiles each) from hour 1's print plus a library of past big launches shipped in the case. Python 3.13, standard library only, offline, deterministic.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` case in the input directory and writes one `<id>.out` forecast per case to the output directory.

## How it forecasts

All modelling happens in log space, per hour of the release day:

- **Library curves.** Each past launch in the case's comparables contributes a log-ratio curve `ln(viewers_h / viewers_1)` for hours 2–24. Launches whose hour-1 print is under 2,000 are left out — their category was essentially empty at midnight, so their ratios are not comparable to a real launch's.
- **Centre curve.** The median of the library's log-ratio curves, hour by hour.
- **Two adjustments**, fitted by least squares on the library and shrunk by 0.75:
  - *Size:* log-ratio curves fall as hour 1 grows — a launch that already draws 800k viewers at 01:00 UTC has little room left to grow, while one at 20k can grow tenfold (correlation between `ln(hour 1)` and `ln(peak / hour 1)` across comparables is about −0.94). The hour-1 deviation is winsorised to ±1.5 log units so the fit is never extrapolated far past the launches it was fitted on.
  - *Unlock pattern:* launches that unlock at midnight local time, rolling around the world, build through the day as each region wakes and unlocks; launches with one simultaneous global unlock spike early and fade. The case's notes say which pattern this launch follows (GTA VI is a rolling-midnight launch).
- **Quantiles.** The five quantiles sit on a normal spread of 0.35 log units around the centre: `q = p1 * exp(centre_h + z * 0.35)`.

If the library is too small to fit on, the forecast falls back to persistence (every hour at hour 1's print, spread widening like a random walk), so the program still writes a valid file.

## Practice results (local scorer, past launches)

Scored against the true hourly viewers for the four practice cases, using the same pinball loss on the log scale the bounty grades with (lower is better):

| case | launch | pinball loss | typical miss | 90% coverage |
| --- | --- | --- | --- | --- |
| p00 | Marvel's Wolverine | 0.130 | 24% | 1.00 |
| p01 | Red Dead Redemption 2 | 0.132 | 22% | 1.00 |
| p02 | God of War Ragnarök | 0.124 | 23% | 1.00 |
| p03 | Marvel's Spider-Man 2 | 0.195 | 33% | 0.91 |
| **mean** | | **0.145** | | |

House baseline practice loss: **0.387**. This entry scores about 62% below the baseline on practice. Runtime is ~0.15 s per case (limit 8 s); outputs are byte-identical across repeated runs.

## Files

- `main.py` — the forecaster (no network, no clock, no randomness)
- `LICENSE` — MIT

---

<sub>Entered on [make.fun](https://make.fun/?ref=k73yfdz2&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
