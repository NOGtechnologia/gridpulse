# 0008 – Merge consecutive violations into episodes

* Status: accepted · Date: 2026-10-18

## Context

With live data, point rules (forecast error, frequency, price, cross-check) fired
once per 15-minute interval, e.g. 40+ FCST-001 events during one PV morning ramp –
unusable in the event list and noisy for operators.

## Decision

`merge_episodes()` collapses events of the same rule/metric/area/source/severity
whose timestamps are ≤ 30 min apart (≤ 1 min for frequency) into one event with
the episode start as timestamp (stable ID while the episode grows) and the worst
value. Notifications are additionally debounced per (rule, area, metric).

## Consequences

One event per real-world situation; the message states the episode span.
