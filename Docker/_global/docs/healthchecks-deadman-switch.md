# Dead-man's switch with healthchecks.io

**Goal:** fastpi sends a "I am alive" ping every 5 minutes. If the pings stop, healthchecks.io emails you and sends a Telegram message.

**Guide only.** Nothing here is set up yet.

## 1. Sign up

1. Open https://healthchecks.io and sign up (free tier is enough).
2. Confirm your email.

## 2. Create the check

1. Click **Add Check**.
2. Name: `fastpi-alive`.
3. **Period:** `5 minutes`.
4. **Grace time:** `10 minutes`.
5. Save.
6. Copy the **ping URL**. It looks like `https://hc-ping.com/<UUID>`. Keep it private.

## 3. Ping from fastpi (systemd timer)

Replace `YOUR-UUID` with your UUID in both commands below. Do not commit the real URL.

### 3a. Service: `/etc/systemd/system/healthcheck-ping.service`

```ini
[Unit]
Description=Ping healthchecks.io dead-man's switch

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -fsS -m 10 --retry 3 https://hc-ping.com/YOUR-UUID
```

### 3b. Timer: `/etc/systemd/system/healthcheck-ping.timer`

```ini
[Unit]
Description=Run the healthchecks.io ping every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=10s

[Install]
WantedBy=timers.target
```

### 3c. Install and start

```bash
sudo nano /etc/systemd/system/healthcheck-ping.service   # paste 3a, save
sudo nano /etc/systemd/system/healthcheck-ping.timer     # paste 3b, save
sudo systemctl daemon-reload
sudo systemctl enable --now healthcheck-ping.timer
```

### 3d. Check it works

```bash
systemctl list-timers healthcheck-ping.timer   # shows next run
sudo systemctl start healthcheck-ping.service  # manual ping now
systemctl status healthcheck-ping.service      # "succeeded" = ok
```

In healthchecks.io the check should turn **green** within a minute.

## 4. Alerts: email and Telegram

1. In healthchecks.io go to **Integrations**.
2. **Email:** the account email is usually added already. Make sure it is enabled for the check.
3. **Telegram:**
   1. Click **Add Integration** → **Telegram**.
   2. Follow the link, open the bot in Telegram and press **Start**.
   3. Pick your chat and save.
   4. Tick it for the `fastpi-alive` check.
4. Button **Send test notification** on each integration, to confirm both arrive.

Note: the UI wording can change. Look for the same names in the Integrations page.

## 5. Test the alert

Quickest test (alert right away):

```bash
curl -fsS https://hc-ping.com/YOUR-UUID/fail
```

Expected: email and Telegram alert within about a minute. Then send a good ping to recover:

```bash
sudo systemctl start healthcheck-ping.service
```

Full test (real dead-man case, about 15 minutes):

```bash
sudo systemctl stop healthcheck-ping.timer    # pings stop
# wait ~15 min (period 5 + grace 10)
sudo systemctl start healthcheck-ping.timer   # restore
```

Expected: the check goes **down** and both alerts arrive.

## Done when

- [ ] Check `fastpi-alive` is green.
- [ ] Timer is active: `systemctl is-active healthcheck-ping.timer` → `active`.
- [ ] Test alert arrived by email.
- [ ] Test alert arrived by Telegram.
- [ ] Recovery ping makes the check green again.
