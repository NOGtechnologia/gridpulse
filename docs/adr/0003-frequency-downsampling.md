# 0003 – Store grid frequency in 10-second buckets (worst sample)

* Status: accepted · Date: 2026-10-18

## Context

Energy-Charts publishes the grid frequency at 1 s resolution (86 400 rows/day).
Storing all of it for two years would dominate the database; averaging would hide
the excursions that matter for alerting.

## Decision

`parse()` reduces the data to 10 s buckets and keeps, per bucket, **the sample with
the largest |f − 50 Hz|** (not the mean). Frequency raw data has its own shorter
retention (`GRIDPULSE_RETENTION_FREQUENCY_DAYS`, default 30 days); hourly/daily
aggregates are kept.

## Consequences

* + 10× less data, alerting stays conservative (no excursion is averaged away).
* − Very short (<1 s) oscillations are not visible; GridPulse is not a PMU tool.
