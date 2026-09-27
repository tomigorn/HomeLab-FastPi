# HA Lifetime Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a tariff-correct lifetime cost, and the lifetime start date, on the Home Assistant "Measured" view.

**Architecture:** 5 new template sensors wrap the existing cost odometers
(`sensor.<x>_cost_accumulated`, integration sensors that charge each moment's
power at that moment's price and never reset). They are rounded to 2 dp as
monetary sensors. The dashboard's Lifetime conditional gets a Cost card instead
of its "no lifetime cost" note. Spec:
`docs/superpowers/specs/2026-09-27-ha-lifetime-cost-design.md`.

**Tech Stack:** Home Assistant 2026.6 YAML packages (template sensors), Lovelace YAML dashboard, Docker Compose.

**Environment facts (read first):**
- Project dir: `/home/pi/Projects/Docker/Home-Assistant/` (git repo root: `/home/pi/Projects`, branch `main`).
- Config files are **root-owned**: edit with `sudo` (e.g. `sudo python3` / `sudo tee`), or run `sudo chown` nothing — keep ownership root.
- Container name: `homeassistant`. Restart: `cd /home/pi/Projects/Docker/Home-Assistant && docker compose restart homeassistant`.
- Config check: `docker exec homeassistant python3 -m homeassistant --script check_config -c /config` (prints only "Testing configuration at /config" when OK).
- There is no API token; read live states from the recorder DB (read-only) as in the test script below.
- Commit format: `Home-Assistant: <short description>`. **No Co-Authored-By / AI trailer.** Stage only the files you changed (the repo has unrelated dirty files).

---

### Task 1: Lifetime cost sensors

**Files:**
- Modify: `Docker/Home-Assistant/config/packages/plug_fastpi.yaml` (after the `FastPi Plug Cost This Year` sensor, ~line 134)
- Modify: `Docker/Home-Assistant/config/packages/plug_beefy.yaml` (after the `Beefy Plug Cost This Year` sensor, ~line 134)
- Modify: `Docker/Home-Assistant/config/packages/plug_vampire.yaml` (before `# --- Projected yearly cost (estimate) — same extrapolation as the plugs,`, ~line 63)
- Modify: `Docker/Home-Assistant/config/packages/electricity.yaml` (after `Total Incl Vampire Cost This Year`, ~line 207, and after `Plugs Total Cost This Year`, ~line 272)
- Test: `/tmp/claude-1000/-home-pi/e8561715-bccb-470a-888d-ff963450556b/scratchpad/verify_lifetime.py`

- [ ] **Step 1: Write the failing test**

Create `/tmp/claude-1000/-home-pi/e8561715-bccb-470a-888d-ff963450556b/scratchpad/verify_lifetime.py`:

```python
import sqlite3, sys
c = sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)
def st(e):
    r = c.execute("""select s.state from states s join states_meta m using(metadata_id)
        where m.entity_id=? order by state_id desc limit 1""", (e,)).fetchone()
    return r[0] if r else None
def num(e):
    v = st(e)
    try: return float(v)
    except (TypeError, ValueError): sys.exit(f'FAIL {e} = {v!r}')
f, b, v = num('sensor.fastpi_plug_cost_lifetime'), num('sensor.beefy_plug_cost_lifetime'), num('sensor.vampire_cost_lifetime')
t, tv = num('sensor.plugs_total_cost_lifetime'), num('sensor.total_incl_vampire_cost_lifetime')
for life, odo in ((f, 'sensor.fastpi_plug_cost_accumulated'), (b, 'sensor.beefy_plug_cost_accumulated'), (v, 'sensor.vampire_plug_cost_accumulated')):
    assert abs(life - num(odo)) <= 0.011, (life, odo, num(odo))
assert abs(t - (f + b)) <= 0.011, (t, f, b)
assert abs(tv - (t + v)) <= 0.011, (tv, t, v)
print(f'PASS fastpi={f} beefy={b} vampire={v} total={t} total_incl_vampire={tv}')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
S=/tmp/claude-1000/-home-pi/e8561715-bccb-470a-888d-ff963450556b/scratchpad/verify_lifetime.py
docker cp $S homeassistant:/tmp/verify_lifetime.py && docker exec homeassistant python3 /tmp/verify_lifetime.py
```
Expected: `FAIL sensor.fastpi_plug_cost_lifetime = None` (exit 1).

- [ ] **Step 3: Add the per-plug sensors**

In `plug_fastpi.yaml`, insert directly after the `FastPi Plug Cost This Year` block's `state:` lines (before the blank line + `# --- Projected yearly cost`):

```yaml
      # Lifetime cost = the cost odometer (each moment priced at its own tariff
      # and year's price, so correct across price changes), rounded for display.
      - name: "FastPi Plug Cost Lifetime"
        unique_id: fastpi_plug_cost_lifetime
        unit_of_measurement: "CHF"
        device_class: monetary
        state_class: total
        availability: "{{ is_number(states('sensor.fastpi_plug_cost_accumulated')) }}"
        state: "{{ states('sensor.fastpi_plug_cost_accumulated') | float(0) | round(2) }}"
```

In `plug_beefy.yaml`, same position after `Beefy Plug Cost This Year`:

```yaml
      # Lifetime cost = the cost odometer (each moment priced at its own tariff
      # and year's price, so correct across price changes), rounded for display.
      - name: "Beefy Plug Cost Lifetime"
        unique_id: beefy_plug_cost_lifetime
        unit_of_measurement: "CHF"
        device_class: monetary
        state_class: total
        availability: "{{ is_number(states('sensor.beefy_plug_cost_accumulated')) }}"
        state: "{{ states('sensor.beefy_plug_cost_accumulated') | float(0) | round(2) }}"
```

In `plug_vampire.yaml`, insert before the line `      # --- Projected yearly cost (estimate) — same extrapolation as the plugs,`:

```yaml
      # Lifetime cost = the cost odometer below, rounded for display.
      - name: "Vampire Cost Lifetime"
        unique_id: vampire_cost_lifetime
        unit_of_measurement: "CHF"
        device_class: monetary
        state_class: total
        availability: "{{ is_number(states('sensor.vampire_plug_cost_accumulated')) }}"
        state: "{{ states('sensor.vampire_plug_cost_accumulated') | float(0) | round(2) }}"

```

- [ ] **Step 4: Add the combined sensors**

In `electricity.yaml`, after the `Plugs Total Cost This Year` block (before `# ---- Projected yearly cost (estimate) — sum of both plugs`):

```yaml
      - name: "Plugs Total Cost Lifetime"
        unique_id: plugs_total_cost_lifetime
        unit_of_measurement: "CHF"
        device_class: monetary
        state_class: total
        availability: "{{ is_number(states('sensor.fastpi_plug_cost_lifetime')) and is_number(states('sensor.beefy_plug_cost_lifetime')) }}"
        state: "{{ (states('sensor.fastpi_plug_cost_lifetime')|float(0) + states('sensor.beefy_plug_cost_lifetime')|float(0)) | round(2) }}"
```

After the `Total Incl Vampire Cost This Year` block:

```yaml
      - name: "Total Incl Vampire Cost Lifetime"
        unique_id: total_incl_vampire_cost_lifetime
        unit_of_measurement: "CHF"
        device_class: monetary
        state_class: total
        availability: "{{ is_number(states('sensor.plugs_total_cost_lifetime')) and is_number(states('sensor.vampire_cost_lifetime')) }}"
        state: "{{ (states('sensor.plugs_total_cost_lifetime')|float(0) + states('sensor.vampire_cost_lifetime')|float(0)) | round(2) }}"
```

Note: the new sensors' entity_ids are derived from `name` (e.g. "Vampire Cost Lifetime" → `sensor.vampire_cost_lifetime`), matching the test.

- [ ] **Step 5: Check config, restart, run test**

```bash
docker exec homeassistant python3 -m homeassistant --script check_config -c /config
cd /home/pi/Projects/Docker/Home-Assistant && docker compose restart homeassistant
# wait until the test passes (sensors need ~30-60 s after start)
until docker exec homeassistant python3 /tmp/verify_lifetime.py; do sleep 5; done
sudo grep -E "^$(date +%F) " config/home-assistant.log | grep -E "ERROR|Invalid" | grep -vi bluetooth | tail
```
Expected: check_config prints only the "Testing configuration" line; the test prints `PASS ...`; no new template/config errors. Also confirm `Setup failed` does not appear.

- [ ] **Step 6: Commit**

```bash
cd /home/pi/Projects
git add Docker/Home-Assistant/config/packages/plug_fastpi.yaml Docker/Home-Assistant/config/packages/plug_beefy.yaml Docker/Home-Assistant/config/packages/plug_vampire.yaml Docker/Home-Assistant/config/packages/electricity.yaml
git commit -m "Home-Assistant: add tariff-correct lifetime cost sensors from the cost odometers"
```

### Task 2: Dashboard Lifetime cost card + README

**Files:**
- Modify: `Docker/Home-Assistant/config/ui-lovelace.yaml` (Measured view, `# ---- Lifetime` conditional, ~lines 478-512)
- Modify: `Docker/Home-Assistant/README.md` (lines ~124-125, ~277, ~288)

- [ ] **Step 1: Replace the Lifetime section comment and energy title**

In `ui-lovelace.yaml`:
- `          # ---- Lifetime (energy only — no reset-period lifetime cost, by design) ----` → `          # ---- Lifetime (all measured data; cost from the tariff-correct odometers) ----`
- `                  title: Energy — Lifetime (kWh)` → `                  title: Energy — Lifetime since 3 Jul 2026 (kWh)`

- [ ] **Step 2: Replace the markdown card with the cost card**

Replace exactly these lines:

```yaml
                - type: markdown
                  content: >
                    **No lifetime cost — by design.** Costs reset each period, so
                    they never run as a single lifetime total. Use **This year**,
                    or the native **Energy** dashboard for an arbitrary date range.
```

with:

```yaml
                - type: entities
                  title: Cost — Lifetime since 3 Jul 2026 (CHF)
                  entities:
                    - entity: sensor.fastpi_plug_cost_lifetime
                      name: FastPi
                    - entity: sensor.beefy_plug_cost_lifetime
                      name: Beefy
                    - entity: sensor.plugs_total_cost_lifetime
                      name: Total
                    - type: conditional
                      conditions:
                        - entity: input_boolean.measured_show_vampire
                          state: "on"
                      row:
                        entity: sensor.vampire_cost_lifetime
                        name: Vampire
                    - type: conditional
                      conditions:
                        - entity: input_boolean.measured_show_vampire
                          state: "on"
                      row:
                        entity: sensor.total_incl_vampire_cost_lifetime
                        name: Total incl. vampire
```

Verify YAML parses (HA's loader tolerates `!include`-free lovelace; plain safe_load works here):

```bash
sudo python3 -c "import yaml; yaml.safe_load(open('/home/pi/Projects/Docker/Home-Assistant/config/ui-lovelace.yaml')); print('YAML OK')"
```
Expected: `YAML OK`. The YAML-mode dashboard reloads on browser refresh; no restart needed.

- [ ] **Step 3: Update README**

In `Docker/Home-Assistant/README.md`:
- Lines ~124-125: `Lifetime shows\n    energy only (no reset-period lifetime cost — see below).` → `Lifetime shows\n    all measured data since 3 Jul 2026 — energy and cost (see below).`
- Line ~277: `There is deliberately **no lifetime cost sum**.` → `Lifetime cost comes from the odometer instead (next bullet).`
- In the **Per-plug cost odometer** bullet, replace `Never shown directly; its per-day / per-month *change* drives` with `Shown (rounded) as `sensor.<p>_plug_cost_lifetime` / `sensor.vampire_cost_lifetime` on the Lifetime view; its per-day / per-month *change* drives`
- Line ~288: `(No combined lifetime cost, by design.)` → `Plus `sensor.plugs_total_cost_lifetime` and `sensor.total_incl_vampire_cost_lifetime` (sums of the lifetime odometers).`

Check: `grep -n -i "no lifetime\|by design" Docker/Home-Assistant/README.md` returns no lifetime-cost "by design" lines.

- [ ] **Step 4: Commit**

```bash
cd /home/pi/Projects
git add Docker/Home-Assistant/config/ui-lovelace.yaml Docker/Home-Assistant/README.md
git commit -m "Home-Assistant: show lifetime cost and start date on the Measured view"
```
