---
title: "InfluxDB and Telegraf"
ring: production
quadrant: devops
tags: [fastpi, monitoring]
---

Time-series store next to Prometheus for data that keeps its own timestamps.
Telegraf writes per-container RAM and Pi hardware data, Home Assistant the plug power, and a nightly collector the usage per user; Grafana reads it all.
