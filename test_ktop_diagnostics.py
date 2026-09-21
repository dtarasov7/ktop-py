"""Regression tests for todo section 18; no Kubernetes connection."""

import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_ktop_security import M, DataError, args
from test_ktop_ui import app_for


def demo_snapshot():
    snapshot = M["DemoClient"](args("--demo")).load_snapshot()
    snapshot.cluster_name = "cluster-a"
    snapshot.context = "context-a"
    snapshot.collection_selectors = {"label_selector": "", "field_selector": ""}
    for source in ("pods", "events", "metrics") + M["NETWORK_SOURCES"]:
        snapshot.source_status[source] = {
            "state": "fresh",
            "observed_at": snapshot.loaded_at.timestamp(),
            "age_seconds": 0,
            "errors": [],
        }
    return snapshot


class DiagnosticsTests(unittest.TestCase):
    def test_cadvisor_throttling_uses_counter_rates(self):
        client = M["KubectlClient"](args("--metrics-source", "prometheus"))
        labels = '{namespace="default",pod="api",container="app",image="example/app"}'
        first = "\n".join((
            "container_cpu_cfs_periods_total%s 100" % labels,
            "container_cpu_cfs_throttled_periods_total%s 10" % labels,
        ))
        second = "\n".join((
            "container_cpu_cfs_periods_total%s 120" % labels,
            "container_cpu_cfs_throttled_periods_total%s 14" % labels,
        ))
        nodes, pods, containers = {}, {}, {}
        client.process_cadvisor_prometheus_samples("node-a", first, 100.0, nodes, pods, containers)
        self.assertNotIn(("default", "api", "app"), containers)
        client.process_cadvisor_prometheus_samples("node-a", second, 102.0, nodes, pods, containers)
        usage = containers[("default", "api", "app")]
        self.assertEqual(usage.cpu_periods_ps, 10.0)
        self.assertEqual(usage.throttled_periods_ps, 2.0)
        self.assertEqual(usage.observed_at, 102.0)

    def test_network_static_chain_and_unknown_inventory(self):
        snapshot = demo_snapshot()
        pod = snapshot.pods[0]
        pod.raw.setdefault("metadata", {})["uid"] = "pod-uid"
        pod.raw["metadata"]["labels"] = {"app": "api"}
        pod.raw.setdefault("status", {})["conditions"] = [{"type": "Ready", "status": "False"}]
        namespace = pod.namespace
        snapshot.network_resources = {
            "services": [{
                "metadata": {"namespace": namespace, "name": "api"},
                "spec": {"selector": {"app": "api"}},
            }, {
                "metadata": {"namespace": namespace, "name": "missing"},
                "spec": {"selector": {"app": "missing"}},
            }],
            "endpointslices": [{
                "metadata": {"namespace": namespace, "name": "api-a", "labels": {"kubernetes.io/service-name": "api"}},
                "endpoints": [{
                    "addresses": ["10.0.0.1"],
                    "conditions": {"ready": False, "serving": True, "terminating": True},
                    "targetRef": {"kind": "Pod", "namespace": namespace, "name": pod.name, "uid": "pod-uid"},
                }],
            }],
            "ingresses": [{
                "metadata": {"namespace": namespace, "name": "api"},
                "spec": {"ingressClassName": "nginx", "rules": [{"http": {"paths": [{"backend": {"service": {"name": "api"}}}]}}]},
            }],
            "networkpolicies": [{
                "metadata": {"namespace": namespace, "name": "api"},
                "spec": {"podSelector": {"matchLabels": {"app": "api"}}, "policyTypes": ["Ingress"]},
            }],
        }
        lines = M["network_lines"](snapshot)
        text = "\n".join(lines)
        self.assertIn("connectivity NOT tested", text)
        self.assertIn("ready=False,serving=True,terminating=True", text)
        self.assertIn("Pod/%s Ready=False" % pod.name, text)
        self.assertIn("Ingress/api", text)
        self.assertIn("NetworkPolicy/api", text)
        self.assertIn("selector mismatch: no matching pods", text)

        snapshot.collection_selectors["label_selector"] = "app=api"
        snapshot.source_status["endpointslices"]["state"] = "forbidden"
        snapshot.network_resources["endpointslices"] = []
        text = "\n".join(M["network_lines"](snapshot))
        self.assertIn("matching pods unknown", text)
        self.assertIn("endpoints unknown", text)

    def test_degradation_evidence_and_throttling_source(self):
        snapshot = demo_snapshot()
        pod = snapshot.pods[0]
        pod.raw["status"] = {
            "reason": "Evicted",
            "message": "ephemeral-storage threshold exceeded",
            "conditions": [{"type": "Ready", "status": "False", "reason": "ContainersNotReady", "lastTransitionTime": "2026-01-01T00:00:00Z"}],
            "containerStatuses": [{
                "name": pod.containers[0].name,
                "lastTerminationState": {"terminated": {"reason": "OOMKilled", "exitCode": 137, "finishedAt": "2026-01-01T00:00:00Z"}},
            }],
            "initContainerStatuses": [{"name": "migrate", "state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
        }
        key = "/".join((pod.namespace, pod.name, pod.containers[0].name))
        snapshot.throttling[key] = {
            "fraction": 0.25,
            "observed_at": snapshot.loaded_at.timestamp(),
            "source": "cadvisor/container_cpu_cfs_*_periods_total",
        }
        snapshot.events.append(M["EventInfo"](
            pod.namespace, "Pod", pod.name, "Unhealthy", "Warning", "Readiness probe failed",
            snapshot.loaded_at, "pod-uid", "event-uid", 2,
        ))
        text = "\n".join(M["degradation_lines"](snapshot))
        self.assertIn("OOMKilled", text)
        self.assertIn("exitCode=137", text)
        self.assertIn("init waiting: CrashLoopBackOff", text)
        self.assertIn("ephemeral-storage threshold exceeded", text)
        self.assertIn("CPU throttling=25.0% periods source=cAdvisor", text)
        self.assertIn("Readiness probe failed", text)
        self.assertIn("Ephemeral-storage bytes: N/A", text)

    def test_security_context_inventory_with_inheritance(self):
        snapshot = demo_snapshot()
        pod = snapshot.pods[0]
        pod.raw["spec"].update({
            "hostNetwork": True,
            "hostPID": True,
            "automountServiceAccountToken": False,
            "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
            "volumes": [{"name": "host", "hostPath": {"path": "/var/run", "type": "Directory"}}],
        })
        pod.raw["spec"]["containers"][0]["securityContext"] = {
            "privileged": True,
            "allowPrivilegeEscalation": True,
            "capabilities": {"add": ["NET_ADMIN"]},
        }
        text = "\n".join(M["security_context_lines"](snapshot))
        self.assertIn("findings do not establish compromise", text)
        self.assertIn("hostNetwork=True hostPID=True", text)
        self.assertIn("automountServiceAccountToken=False", text)
        self.assertIn("hostPath=/var/run", text)
        self.assertIn("privileged=True", text)
        self.assertIn("NET_ADMIN", text)
        self.assertIn("runAsNonRoot=True", text)
        self.assertIn("RuntimeDefault", text)

    def test_timeline_tracks_uid_changes_events_and_bounds(self):
        before = demo_snapshot()
        before.loaded_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        pod = before.pods[0]
        pod.raw.setdefault("metadata", {})["uid"] = "pod-1"
        tracker = M["IncidentTimeline"]()
        tracker.update(before)

        after = copy.deepcopy(before)
        after.loaded_at += dt.timedelta(seconds=5)
        after.pods[0].status = "CrashLoopBackOff"
        after.pods[0].restarts += 1
        after.events.append(M["EventInfo"](
            pod.namespace, "Pod", pod.name, "BackOff", "Warning", "restart back-off",
            after.loaded_at, "pod-1", "event-1", 1,
        ))
        timeline = tracker.update(after)
        text = json.dumps(timeline)
        self.assertIn("snapshot observation", text)
        self.assertIn("restarts", text)
        self.assertIn("event-1", str(tracker.seen))
        self.assertIn("restart back-off", text)

        for index in range(1100):
            tracker.entries.append({"at": str(index)})
        self.assertEqual(len(tracker.entries), 1000)

    def test_versioned_roundtrip_diff_and_replay(self):
        before = demo_snapshot()
        before.loaded_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        before.pods[0].raw.setdefault("metadata", {})["uid"] = "pod-1"
        after = copy.deepcopy(before)
        after.loaded_at += dt.timedelta(seconds=10)
        after.pods[0].restarts += 2
        after.pods[0].status = "CrashLoopBackOff"
        after.events.append(M["EventInfo"](
            after.pods[0].namespace, "Pod", after.pods[0].name, "BackOff", "Warning",
            "restart back-off", after.loaded_at, "pod-1", "event-new", 1,
        ))
        output_args = args("--demo", "--dump", "--output", "json", "--include-raw")

        with tempfile.TemporaryDirectory(prefix=".ktop-diagnostics-", dir=Path(__file__).parent) as directory:
            paths = []
            for index, snapshot in enumerate((before, after)):
                path = Path(directory) / ("%d.json" % index)
                path.write_text(M["dump_snapshot_json"](snapshot, output_args), encoding="utf-8")
                paths.append(str(path))
            restored = M["read_snapshot_file"](paths[0])
            self.assertEqual(restored.loaded_at, before.loaded_at)
            self.assertEqual(len(restored.pods), len(before.pods))
            self.assertEqual(M["compare_snapshots"](before, restored), [])
            changes = M["compare_snapshots"](restored, M["read_snapshot_file"](paths[1]))
            changed = next(item for item in changes if item["uid"] == "pod-1")
            self.assertEqual(changed["fields"]["restarts"], {"before": before.pods[0].restarts, "after": after.pods[0].restarts})
            event = next(item for item in changes if item["uid"] == "event-new")
            self.assertEqual(event["kind"], "Event")
            self.assertEqual(event["change"], "added")

            different = copy.deepcopy(after)
            different.cluster_name = "another-cluster"
            with self.assertRaisesRegex(DataError, "different cluster/context"):
                M["compare_snapshots"](before, different)
            with self.assertRaisesRegex(DataError, "chronological"):
                M["compare_snapshots"](after, before)
            partial = copy.deepcopy(after)
            partial.collection_selectors["label_selector"] = "app=selected"
            removed_uid = partial.pods[0].raw["metadata"]["uid"]
            partial.pods = partial.pods[1:]
            disappearance = next(item for item in M["compare_snapshots"](after, partial)
                                 if item["uid"] == removed_uid)
            self.assertEqual(disappearance["change"], "no-longer-visible")

            replay = M["ReplayClient"](paths)
            self.assertEqual(replay.index, 0)
            self.assertEqual(replay.step(1).loaded_at, after.loaded_at)
            with self.assertRaisesRegex(DataError, "offline replay"):
                replay.get_logs("ns", "pod", "container", 10, False)

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                self.assertEqual(M["main"](["--diff", paths[0], paths[1], "--output", "json"]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["changes"][0]["at"], "2026-01-01T00:00:10Z")

            invalid = Path(directory) / "invalid.json"
            invalid.write_text('{"schema_version":2,"snapshot":{}}', encoding="utf-8")
            with self.assertRaisesRegex(DataError, "schema_version"):
                M["read_snapshot_file"](str(invalid))
            invalid.write_text('{"schema_version":1,"snapshot":{"unknown":true}}', encoding="utf-8")
            with self.assertRaisesRegex(DataError, "unknown snapshot field"):
                M["read_snapshot_file"](str(invalid))
            with self.assertRaisesRegex(DataError, "exceeds"):
                M["read_snapshot_file"](paths[0], 10)

    def test_support_bundle_selection_redaction_and_permissions(self):
        snapshot = demo_snapshot()
        selected = snapshot.pods[0]
        selected.raw.setdefault("metadata", {}).setdefault("annotations", {})["example"] = "ANNOTATION_SECRET"
        selected.raw["spec"]["containers"][0]["env"] = [{"name": "PASSWORD", "value": "ENV_SECRET"}]
        selected.raw["spec"]["containers"][0]["command"] = ["run", "COMMAND_SECRET"]
        selected.raw["status"]["message"] = "MESSAGE_SECRET"
        bundle_args = args("--demo", "--include-raw")
        bundle_args.bundle_namespace = [selected.namespace]
        bundle_args.bundle_object = []
        payload = M["support_bundle"](snapshot, bundle_args)
        serialized = json.dumps(payload)
        for secret in ("ANNOTATION_SECRET", "ENV_SECRET", "COMMAND_SECRET", "MESSAGE_SECRET"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(payload["bundle"]["partial_selection"])
        self.assertIn("no guarantee", payload["bundle"]["redaction"])
        self.assertTrue(all(pod["namespace"] == selected.namespace for pod in payload["pods"]))
        self.assertIsNone(payload["cluster"]["nodes"])
        self.assertIn("configuration", "\n".join(payload["diagnostics"]["network"]))
        self.assertIn("findings do not establish compromise", "\n".join(payload["diagnostics"]["security"]))
        self.assertEqual(payload["diagnostics"]["degradation"], ["[REDACTED free text]"])

        with tempfile.TemporaryDirectory(prefix=".ktop-bundle-", dir=Path(__file__).parent) as directory:
            path = Path(directory) / "bundle.json"
            M["write_support_bundle"](str(path), payload, 10 * 1024 * 1024)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 1)

    def test_new_tui_pages_and_demand_groups(self):
        app = app_for(22, 80)
        app.snapshot.diagnostic_views = M["diagnostic_views"](app.snapshot)
        app.snapshot.timeline = [{"at": "2026-01-01T00:00:00Z", "kind": "Pod", "namespace": "default", "name": "api", "uid": "1", "change": "Ready", "source": "snapshot"}]
        for page in ("network", "degradation", "timeline", "security"):
            app.page = page
            app.draw()
            self.assertTrue(app.stdscr.writes)
        labels = [label for label, _ in app.palette_commands()]
        self.assertIn("Network Service/EndpointSlice/Pod", labels)
        self.assertIn("Workload securityContext", labels)


if __name__ == "__main__":
    unittest.main()
