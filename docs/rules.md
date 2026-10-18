# Event rules

All rules are deterministic, pure functions in `backend/src/gridpulse/domain/rules/`
or `validation/`. Every event has: timestamp (UTC), severity, rule ID, value,
threshold, unit, source. Event IDs are a hash of rule, timestamp, metric, area and
source, so re-evaluating the same data never creates duplicates.

Consecutive point violations of the same rule are merged into one **episode**
(gap ≤ 30 min, frequency ≤ 1 min); the event keeps the episode start and the worst
value. Notifications are additionally debounced per (rule, area, metric)
(`GRIDPULSE_ALERT_DEBOUNCE_MINUTES`).

| ID | Category | Condition (defaults, all configurable) | Severity |
|---|---|---|---|
| FREQ-001 | grid | \|f − 50 Hz\| > 100 mHz; > 200 mHz | warning; critical |
| FCST-001 | forecast | \|actual − forecast\| > 10 % of max(forecast, 1000 MW) for load, wind onshore, PV | warning |
| PRICE-001 | price | day-ahead > 500 EUR/MWh; > 1000 EUR/MWh | warning; critical |
| OUT-001 | outlook | window with negative day-ahead prices | info |
| OUT-002 | outlook | wind + PV < 10 % of load for ≥ 6 h (forecast) | warning |
| STAT-001 | statistical | residual load robust MAD score > 4 vs. preceding 96 points | warning |
| STAT-002 | statistical | frequency z-score > 4 vs. preceding 96 points | warning |
| DATA-001 | data_quality | newest data of a source older than 3 h | warning |
| DATA-002 | data_quality | schema validation failed (data rejected) | warning |
| PLAUS-001 | data_quality | frequency outside 49–51 Hz | warning |
| PLAUS-002 | data_quality | negative value for a metric that cannot be negative | warning |
| PLAUS-003 | data_quality | PV > 50 MW while the sun is below −6° over Germany | warning |
| PLAUS-004 | data_quality | price outside −500…4000 EUR/MWh | warning |
| PLAUS-005 | data_quality | duplicate timestamps or gaps on the resolution grid | warning |
| PLAUS-006 | data_quality | generation + import − pumped consumption deviates > 15 % from load | warning |
| XCHK-001 | data_quality | SMARD vs. Energy-Charts deviate > 5 % (load, wind, PV, price) | warning |

The frequency traffic light shown in the UI: green ≤ 50 mHz, yellow ≤ 100 mHz, red above.
