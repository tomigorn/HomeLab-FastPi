# _global/scripts

| Script | What |
|---|---|
| `docker-user-lan-guard.sh [--persist]` | DOCKER-USER: which containers may reach the LAN (FORWARD) |
| `host-input-guard.sh [--persist]` | HOST-GUARD/HOST-GUARD6: which containers / VPN peers may reach the host itself (INPUT) |
| `host-output-guard.sh [--persist]` | HOST-OUT-GUARD: what the host itself (incl. host-network containers) may open on beefy (OUTPUT) |
| `iptables-persist.sh` | writes `/etc/iptables/rules.v4/v6` with only those chains; never `netfilter-persistent save` |
| `smoke-test.sh` | end-to-end checks, must stay green |
| `update-project.sh`, `auto_update.py` | image updates |
| `oob-alert.sh` | Telegram alert that bypasses the edge |

## host-input-guard
- New host port needed by a container or the VPN: add it to the port lists in the script, `sudo ./host-input-guard.sh --persist`.
- Something from a container to the host times out: `sudo journalctl -k | grep 'host-guard drop'`.
- Remove the OUTPUT guard: `sudo iptables -D OUTPUT -d 192.168.1.102/32 -j HOST-OUT-GUARD`, then `sudo ./iptables-persist.sh`. Something on the host can't reach beefy: `sudo journalctl -k | grep 'host-out-guard drop'` (shows UID).
- Remove (one command): `for i in docker0 br-+; do sudo iptables -D INPUT -i $i -j HOST-GUARD; done; for i in docker0 br-+ eth0; do sudo ip6tables -D INPUT -i $i -j HOST-GUARD6; done`, then `sudo ./iptables-persist.sh`.
