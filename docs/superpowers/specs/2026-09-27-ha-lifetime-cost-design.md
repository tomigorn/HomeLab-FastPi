# Home Assistant: lifetime cost on the Measured view — design

Date: 2026-09-27 · Project: `Docker/Home-Assistant`

## Goal

The Measured view's timeframe dropdown already has Today / This week / This
month / This year / Lifetime. The user wants:

- **This week** = Monday 00:00 → now, **This month** = 1st 00:00 → now,
  **This year** = 1 Jan 00:00 → now. *Already true*: the `utility_meter` cycles
  `weekly` / `monthly` / `yearly` reset at exactly those boundaries. No change.
- **Lifetime** = all measured data, **showing the start date**, with a
  **cost** total that respects the different tariffs (high/low, and different
  prices per year). Today Lifetime shows energy only plus a "no lifetime cost —
  by design" note. This spec adds lifetime cost.

## Approach

Lifetime cost comes from the existing **cost odometers**
(`sensor.fastpi_plug_cost_accumulated`, `sensor.beefy_plug_cost_accumulated`,
`sensor.vampire_plug_cost_accumulated`). Each integrates the live CHF/h rate
(power × `sensor.electricity_current_price`), so every moment is priced at the
tariff (high/low) *and* the year's price in force at that moment. That makes the
total correct across price changes. These integration sensors never reset and
don't depend on `utility_meter`, so they also kept counting through the
2026-09-01 outage. On 2026-09-27 they agree with the tariff-split yearly cost:
FastPi 3.9016 vs 3.90, Beefy 0.808 vs 0.80, vampire 3.5208 vs 3.5207.

Rejected: lifetime high/low kWh (`*_plug_total_high/low`) × the current
price. That prices all past years at today's price, so it is wrong once prices
change.

## Components

1. **Per-plug template sensors** (in each plug's package, beside the other cost
   sensors). Each one rounds the odometer to 2 dp, with `device_class: monetary`,
   `state_class: total` and unit CHF, so the dashboard shows `CHF x.xx` like the
   other cost rows:
   - `sensor.fastpi_plug_cost_lifetime` (`packages/plug_fastpi.yaml`)
   - `sensor.beefy_plug_cost_lifetime` (`packages/plug_beefy.yaml`)
   - `sensor.vampire_cost_lifetime` (`packages/plug_vampire.yaml`)
   The `availability:` of each is `is_number(<its odometer>)`. There is no price
   guard, because the odometer already holds priced CHF.
2. **Combined sensors** (`packages/electricity.yaml`):
   - `sensor.plugs_total_cost_lifetime` = FastPi + Beefy
   - `sensor.total_incl_vampire_cost_lifetime` = plugs total + vampire
   Each is available only when all its inputs are numbers.
3. **Dashboard** (`ui-lovelace.yaml`, Measured → Lifetime conditional):
   - Energy card title: `Energy — Lifetime since 3 Jul 2026 (kWh)`.
   - Replace the markdown "No lifetime cost" card with an `entities` card
     `Cost — Lifetime since 3 Jul 2026 (CHF)`. It has the same rows and vampire
     conditionals as the other periods' cost cards.
   - Start date is hardcoded. Measurement began 2026-07-03 (the first
     long-term statistics for the plug energy/cost sensors), and a lifetime
     start never moves.
4. **README**: replace the three "no lifetime cost, by design" statements with
   the lifetime-cost sensors and the reasoning above.

## Out of scope

- The known once-a-year New-Year-week approximation in `this_week` cost
  (already documented in the README).
- The Vampire row's `0.0002 CHF` formatting in the other periods.

## Verification

- `check_config` passes; restart HA; no `Invalid config` / template errors in
  the log.
- New sensors are numeric. Per plug, lifetime cost equals its odometer to 2 dp.
  Total = FastPi + Beefy, and total incl. vampire = total + vampire.
- On 2026-09-27 lifetime cost ≈ this-year cost (±0.01), since all data is from
  2026.
