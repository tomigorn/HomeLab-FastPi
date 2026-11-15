"""Tests for netns-watch.py. Run: python3 -m unittest discover -s Docker/mouse/scripts"""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("netns_watch", Path(__file__).parent / "netns-watch.py")
nw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nw)

GID = "7e8d" + "0" * 60
OLD = "dead" + "0" * 60
NOW = 1_000_000.0


def inspect(name, pid, mode="mouse_mouse_network", project="mouse", running=True, health=None, cid=None):
    state = {"Running": running, "Pid": pid if running else 0}
    if health:
        state["Health"] = {"Status": health}
    return {"Id": cid or name + "0" * 20, "Name": "/" + name, "State": state, "HostConfig": {"NetworkMode": mode},
            "Config": {"Labels": {"com.docker.compose.project": project, "com.docker.compose.service": name}}}


def stack(gluetun_health="healthy", gluetun_running=True, **netns):
    """gluetun pid 1 in netns 100; dependents pid 2.. in netns 100 unless overridden by name."""
    names = ["qbittorrent_mouse", "sabnzbd", "mousehole", "prowlarr_mouse", "prowlarr-gate"]
    data = [inspect("gluetun_mouse", 1, health=gluetun_health, running=gluetun_running, cid=GID)]
    inos = {1: 100}
    for i, n in enumerate(names, start=2):
        data.append(inspect(n, i, mode=f"container:{GID}", health="healthy"))
        inos[i] = netns.get(n.replace("-", "_"), 100)
    return data, inos.get


class ParseTest(unittest.TestCase):
    def test_finds_gluetun_and_every_container_in_its_netns(self):
        data, ns = stack()
        g, deps = nw.parse(data, ns)
        self.assertEqual((g.id, g.netns, g.health), (GID, 100, "healthy"))
        self.assertEqual(sorted(d.name for d in deps), ["mousehole", "prowlarr-gate", "prowlarr_mouse", "qbittorrent_mouse", "sabnzbd"])

    def test_ignores_containers_of_other_projects_and_own_networks(self):
        data, ns = stack()
        data.append(inspect("traefik", 50, mode=f"container:{GID}", project="infra__traefik"))
        data.append(inspect("port_updater", 51))
        _, deps = nw.parse(data, ns)
        self.assertNotIn("traefik", [d.name for d in deps])
        self.assertNotIn("port_updater", [d.name for d in deps])

    def test_no_gluetun_container(self):
        data, ns = stack()
        g, deps = nw.parse(data[1:], ns)
        self.assertIsNone(g)
        self.assertEqual(len(deps), 5)


class DecideTest(unittest.TestCase):
    def run_decide(self, data, ns, state=None, now=NOW):
        g, deps = nw.parse(data, ns)
        return nw.decide(g, deps, state or {}, now)

    def test_all_in_gluetun_netns_does_nothing(self):
        actions, alerts, state = self.run_decide(*stack())
        self.assertEqual((actions, alerts), ([], []))
        self.assertEqual(state["stale"], [])

    def test_stale_netns_after_gluetun_restart_restarts_only_those(self):
        actions, alerts, state = self.run_decide(*stack(qbittorrent_mouse=99, prowlarr_mouse=99))
        self.assertEqual(sorted(actions), ["prowlarr_mouse", "qbittorrent_mouse"])
        self.assertEqual(alerts, [])
        self.assertEqual(state["containers"]["qbittorrent_mouse"]["attempts"], 1)

    def test_gluetun_unhealthy_no_restarts(self):
        for health in ("unhealthy", "starting"):
            actions, alerts, state = self.run_decide(*stack(gluetun_health=health, qbittorrent_mouse=99, sabnzbd=99))
            self.assertEqual((actions, alerts), ([], []), health)
            self.assertEqual(state.get("containers", {}), {}, "no attempts counted while gluetun is down")

    def test_gluetun_stopped_no_restarts(self):
        actions, alerts, _ = self.run_decide(*stack(gluetun_running=False, qbittorrent_mouse=99))
        self.assertEqual((actions, alerts), ([], []))

    def test_gluetun_missing_no_restarts(self):
        data, ns = stack(qbittorrent_mouse=99)
        self.assertEqual(self.run_decide(data[1:], ns)[:2], ([], []))

    def test_stopped_dependent_is_left_alone(self):
        data, ns = stack()
        data[1] = inspect("qbittorrent_mouse", 2, mode=f"container:{GID}", running=False)
        self.assertEqual(self.run_decide(data, ns)[:2], ([], []))

    def test_unreadable_netns_is_skipped(self):
        data, ns = stack()
        self.assertEqual(self.run_decide(data, lambda pid: None if pid == 2 else ns(pid))[:2], ([], []))

    def test_unreadable_gluetun_netns_no_restarts(self):
        data, ns = stack(sabnzbd=99)
        self.assertEqual(self.run_decide(data, lambda pid: None if pid == 1 else ns(pid))[:2], ([], []))

    def test_dependent_of_a_removed_gluetun_alerts_once_without_restart(self):
        data, ns = stack()
        data[1]["HostConfig"]["NetworkMode"] = f"container:{OLD}"
        actions, alerts, state = self.run_decide(data, ns)
        self.assertEqual(actions, [])
        self.assertEqual(len(alerts), 1)
        self.assertIn("qbittorrent_mouse", alerts[0])
        actions, alerts, _ = self.run_decide(data, ns, state, NOW + 30)
        self.assertEqual((actions, alerts), ([], []))

    def test_waits_for_the_cooldown_before_a_second_restart(self):
        data, ns = stack(sabnzbd=99)
        _, _, state = self.run_decide(data, ns)
        actions, _, state = self.run_decide(data, ns, state, NOW + nw.COOLDOWN - 1)
        self.assertEqual(actions, [])
        actions, _, state = self.run_decide(data, ns, state, NOW + nw.COOLDOWN)
        self.assertEqual(actions, ["sabnzbd"])

    def test_alerts_once_when_restarts_do_not_help_and_stops_restarting(self):
        data, ns = stack(sabnzbd=99)
        state, t, restarts = {}, NOW, 0
        for _ in range(nw.MAX_ATTEMPTS):
            actions, alerts, state = self.run_decide(data, ns, state, t)
            restarts += len(actions)
            self.assertEqual(alerts, [])
            t += nw.COOLDOWN
        actions, alerts, state = self.run_decide(data, ns, state, t)
        self.assertEqual((restarts, actions, len(alerts)), (nw.MAX_ATTEMPTS, [], 1))
        self.assertIn("sabnzbd", alerts[0])
        actions, alerts, state = self.run_decide(data, ns, state, t + 3600)
        self.assertEqual((actions, alerts), ([], []))
        self.assertEqual(state["stale"], ["sabnzbd"])

    def test_back_in_gluetun_netns_resets_the_count(self):
        data, ns = stack(sabnzbd=99)
        _, _, state = self.run_decide(data, ns)
        _, _, state = self.run_decide(*stack(), state, NOW + 30)
        self.assertNotIn("sabnzbd", state["containers"])
        self.assertEqual(state["stale"], [])

    def test_gluetun_down_does_not_drop_known_stale_containers_from_state(self):
        data, ns = stack(sabnzbd=99)
        _, _, state = self.run_decide(data, ns)
        _, _, state = self.run_decide(*stack(gluetun_health="unhealthy", sabnzbd=99), state, NOW + 30)
        self.assertEqual(state["containers"]["sabnzbd"]["attempts"], 1)


class AlertTest(unittest.TestCase):
    def test_message_is_telegram_html_with_escaped_text(self):
        msg = nw.alert_message(["sabnzbd <x>: still outside"])
        self.assertTrue(msg.startswith("🔴 <b>"))
        self.assertIn("• sabnzbd &lt;x&gt;: still outside", msg)


if __name__ == "__main__":
    unittest.main(verbosity=1)
