# Home Assistant: device + charts on the default Overview dashboard

**Date:** 2026-06-29
**Project:** `Docker/Home-Assistant`

## Problem

The default **Overview** dashboard is HA's auto-generated one (all auto-discovered
entities, no structure). The polished device controls and charts live on a
*separate* YAML dashboard ("Home", `config/dashboards/home.yaml`). The user wants
the device + charts on the **Overview** page itself, kept config-as-code.

## Decision

Promote the existing `Home` YAML dashboard to **be** the default Overview, rather
than duplicate its cards. The auto-generated Overview clutter is replaced.

Trade-off (accepted): the default Overview becomes YAML-managed, losing UI
drag-and-drop editing. This matches the project's config-as-code philosophy.

## Changes

1. **Move** `config/dashboards/home.yaml` → `config/ui-lovelace.yaml`
   (the file HA reads for the default dashboard when `lovelace.mode: yaml`).
   Rename dashboard `title` and the first view `title` to `Overview`.
2. **Edit** `config/configuration.yaml` — register `ui-lovelace.yaml` as the
   default dashboard by claiming the `lovelace` url_path slot:
   ```yaml
   lovelace:
     dashboards:
       lovelace:
         mode: yaml
         filename: ui-lovelace.yaml
         title: Overview
         icon: mdi:home
         show_in_sidebar: true
   ```
   This replaces HA's auto-generated home dashboard and is the supported
   successor to the deprecated top-level `lovelace: mode: yaml` (removed in
   HA 2026.8). Remove the old `dashboards.home-yaml` block.
3. **Restart** Home Assistant (dashboard registration requires a restart;
   subsequent YAML content edits only need a browser refresh).

### Note — why not top-level `mode: yaml`

First attempt used `lovelace: mode: yaml`. In this HA version that option is
deprecated AND no longer claims the primary Overview slot: HA's new
auto-generated "home" dashboard took the top slot and the YAML dashboard
appeared as a duplicate second "Overview". Registering an explicit dashboard
at the reserved `lovelace` key is the fix.

Config files are root-owned → filesystem edits via `sudo`; git staged as `pi`.

## Result

Sidebar: **Overview** (device + charts, two views: Overview + Energy, in git) +
**Map**. No duplicated dashboard. The `Map` storage dashboard is untouched.

## Out of scope

No changes to sensors, the myStrom package, energy/tariff logic, or card content
beyond the title rename. This is a relocation of an existing dashboard, not a
redesign of its cards.
