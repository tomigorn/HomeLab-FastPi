# HA Electricity dashboard — 24/7 cost calculator tab

## Goal
A 4th tab on the "Electricity" dashboard: type a wattage, see what running it
24/7 for a year costs at the current EWZ (Zürich) high/low tariffs. Pure
calculator — not tied to any plug.

## Design
- **Input:** `input_number.calculator_watts` (box mode, W, 0–10000, step 0.1),
  new package `config/packages/cost_calculator.yaml`. No `initial:` so HA
  restores the last value typed.
- **Output:** one `markdown` card whose Jinja template computes everything live.
  No template sensors, so the what-if numbers never reach InfluxDB/Grafana,
  long-term statistics or the Energy dashboard.
- **Maths (24/7 load):** HIGH = Mon–Sat 06:00–22:00 = 96 h/week, LOW = 72 h/week
  → 96/168 = 57.14 % high, 42.86 % low. Year = 8760 h.
  `kWh/yr = W × 8760 / 1000`; `cost = kWh × (0.5714 × high + 0.4286 × low)`.
  Prices from `sensor.electricity_price_high` / `_low` (the per-year table in
  `electricity.yaml`), so the calculator follows the current year automatically.
  Public holidays ignored (same as the rest of the metering).
- **Shows:** CHF/year (headline), CHF/month (÷12), CHF/day (÷365), kWh/year,
  high- vs low-tariff share of the cost, blended CHF/kWh.
- **Missing prices:** if either price sensor is not numeric, the card shows a
  warning instead of numbers (consistent with the "no silent wrong numbers" rule).
- **View:** `Calculator`, icon `mdi:calculator`, path `calculator`.

## Testing
`check_config` passes; restart; set the input to a known value (e.g. 10 W →
87.6 kWh/yr) and check the card's CHF/year by hand against the 2026 prices.
