"""Regression checks for todo sections 14 and 15; no Kubernetes connection."""

import datetime as dt
import json
import math
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


M = runpy.run_path(str(Path(__file__).with_name("ktop-py.py")), run_name="ktop_test")
Client = M["KubectlClient"]
App = M["KtopApp"]
Usage = M["ResourceUsage"]
DataError = M["DataError"]


def args(*values):
    return M["normalize_display_scope"](M["build_arg_parser"]().parse_args(list(values)))


class Screen:
    def __init__(self):
        self.writes = []

    def getmaxyx(self):
        return 45, 160

    def addstr(self, y, x, text, attr=0):
        self.writes.append(text)

    def erase(self):
        self.writes.clear()

    def refresh(self):
        pass


class SecurityTests(unittest.TestCase):
    def test_literal_and_bounded_regex(self):
        app = object.__new__(App)
        self.assertEqual(app.query_match_spans("a.b axb", "a.b"), [(0, 3)])
        self.assertEqual(app.query_match_spans("re:x", "lit:re:x"), [(0, 4)])
        self.assertEqual(app.search_match_lines(["abc", "123"], "re:^[0-9]+$"), [1])
        started = time.monotonic()
        self.assertEqual(app.search_match_lines(["a" * 32 + "!"] * 100, "re:((a)+)+$"), [])
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIn("timed out", app.query_error("re:((a)+)+$"))
        # Failed expressions remain disabled across frames, rather than timing out again.
        started = time.monotonic()
        app.search_match_lines(["a" * 32 + "!"] * 100, "re:((a)+)+$")
        self.assertLess(time.monotonic() - started, 0.1)

    def test_invalid_regex_fallback(self):
        app = object.__new__(App)
        self.assertEqual(app.search_match_lines(["[literal]"], "re:["), [0])
        self.assertTrue(app.query_error("re:["))

    def test_terminal_output(self):
        snapshot = M["DemoClient"](args("--demo")).load_snapshot()
        snapshot.pods[0].status = "\x1b[2J\u202eFAKE"
        snapshot.warnings = ["bad\x1b[H\rmessage\nnext"]
        output = M["dump_snapshot"](snapshot)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\u202e", output)
        self.assertIn("\nnext", output)
        self.assertEqual(json.loads(M["dump_snapshot_json"](snapshot))["warnings"], snapshot.warnings)

    def test_bounded_process_success_and_both_pipes(self):
        result = M["bounded_command"]([sys.executable, "-c", "import sys; print('ok'); sys.stderr.write('err')"], 2, 1024)
        self.assertEqual(result, (0, b"ok\n", b"err"))

    def test_output_and_timeout_limits(self):
        for source in ("import sys; sys.stdout.write('x'*100000)", "import sys; sys.stderr.write('x'*100000)"):
            with self.assertRaisesRegex(DataError, "exceeds"):
                M["bounded_command"]([sys.executable, "-c", source], 2, 1024)
        started = time.monotonic()
        with self.assertRaisesRegex(DataError, "timed out"):
            M["bounded_command"]([sys.executable, "-c", "import time; time.sleep(10)"], 0.1, 1024)
        self.assertLess(time.monotonic() - started, 1)

    def test_invalid_utf8_text_and_json(self):
        client = Client(args())
        client.base_cmd = lambda: [sys.executable]
        self.assertEqual(client.run(["-c", "import os; os.write(1,bytes([255]))"]), "\\xff")
        with self.assertRaisesRegex(DataError, "invalid UTF-8 JSON"):
            client.run(["-c", "import os; os.write(1,bytes([255]))", "json"])

    def test_log_byte_limit(self):
        client = Client(args("--log-limit-bytes", "4096"))
        calls = []
        client.run = lambda command, timeout=None: calls.append(command) or "text"
        self.assertEqual(client.get_logs("ns", "pod", "app", 200, True), ["text"])
        self.assertEqual(calls[0][calls[0].index("--limit-bytes") + 1], "4096")

    def test_history_ttl_global_budget_and_zero(self):
        client = Client(args("--prometheus-retention", "1s", "--max-metric-series", "10", "--max-history-points", "12"))
        for i in range(100):
            client.add_history_sample(("pod", "ns", str(i), "cpu"), 1, 0.0)
            client.prom_counter_rate("node", "cpu", {"pod": str(i)}, 1, 1)
        self.assertLessEqual(len(client.metric_history), 10)
        self.assertLessEqual(client.history_points, 12)
        self.assertLessEqual(len(client.prom_counter_previous), 10)
        client.prune_metric_caches(10)
        self.assertFalse(client.metric_history)
        self.assertFalse(client.prom_counter_previous)
        self.assertEqual(client.history_points, 0)
        key = ("pod", "ns", "p", "mem")
        client.add_gauge_history_sample(key, 10, 0)
        self.assertEqual(M["history_values"](client.current_metric_history(), key), [0])

    def test_recreated_uid_does_not_inherit_history(self):
        client = Client(args("--context", "prod"))
        pods = {"items": [{"metadata": {"namespace": "ns", "name": "p", "uid": "old"}}]}
        client.sync_object_identities({"items": []}, pods)
        client.add_history_sample(("pod", "ns", "p", "cpu"), time.time(), 1)
        pods["items"][0]["metadata"]["uid"] = "new"
        client.sync_object_identities({"items": []}, pods)
        self.assertFalse(client.metric_history)
        client.add_history_sample(("pod", "ns", "p", "cpu"), time.time(), 2)
        self.assertEqual(M["history_values"](client.current_metric_history(), ("pod", "ns", "p", "cpu")), [2])
        client.cluster_identity = ("", "other")
        self.assertFalse(client.current_metric_history())

    def test_context_pinning_and_no_raw_credentials(self):
        client = Client(args("--context", "prod"))
        calls = []
        def run(command, timeout=None):
            calls.append(command)
            if command[:2] == ["config", "current-context"]:
                return "dev"
            if command[:2] == ["config", "view"]:
                return "prod-user"
            return '{"serverVersion":{"gitVersion":"v1.test"}}'
        client.run = run
        self.assertEqual(client.cluster_info([])[0], "prod")
        self.assertNotIn(["config", "current-context"], calls)
        self.assertFalse(any("--raw" in call for call in calls))
        client = Client(args())
        client.run = run
        client.pin_context()
        client.run = lambda *a, **k: self.fail("context must not be reread")
        client.pin_context()
        self.assertEqual(client.base_cmd()[1:3], ["--context", "dev"])

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_local_kubeconfig_field_selection(self):
        with tempfile.TemporaryDirectory(prefix=".ktop-test-", dir=Path(__file__).parent) as directory:
            path = Path(directory) / "config.json"
            config = {"apiVersion": "v1", "kind": "Config", "current-context": "dev",
                      "contexts": [{"name": name, "context": {"cluster": name, "user": name + "-user"}} for name in ("dev", "prod")],
                      "clusters": [{"name": name, "cluster": {"server": "https://example.invalid"}} for name in ("dev", "prod")],
                      "users": [{"name": name + "-user", "user": {"token": "SYNTHETIC_SECRET"}} for name in ("dev", "prod")]}
            path.write_text(json.dumps(config), encoding="utf-8")
            client = Client(args("--kubeconfig", str(path), "--context", "prod"))
            real_run = client.run
            outputs = []
            def local_only(command, timeout=None):
                if command[0] == "version":
                    return '{}'
                self.assertEqual(command[0], "config")
                value = real_run(command, timeout)
                outputs.append(value)
                return value
            client.run = local_only
            self.assertEqual(client.cluster_info([])[:2], ("prod", "prod-user"))
            self.assertNotIn("SYNTHETIC_SECRET", "".join(outputs))

    def test_partial_metrics_server_measurement(self):
        pods, _ = M["parse_metrics_server_pods"]({"items": [{"metadata": {"namespace": "ns", "name": "p"},
            "containers": [{"name": "a", "usage": {"cpu": "0", "memory": "1Mi"}},
                           {"name": "b", "usage": {"cpu": "0"}}]}]})
        self.assertEqual(pods[("ns", "p")].cpu_m, 0)
        self.assertTrue(math.isnan(pods[("ns", "p")].mem_b))

    def test_secondary_cache_keeps_data_and_error(self):
        client = Client(args())
        client.fetch_secondary_resource = lambda *a: ({"items": [{"metadata": {"name": "old"}}]}, [])
        client.load_secondary_resources([])
        client.fetch_secondary_resource = lambda *a: ({"items": []}, ["Forbidden"])
        first, second = [], []
        failed = client.load_secondary_resources(first, force=True)
        client.load_secondary_resources(second)
        self.assertTrue(failed["jobs"]["items"])
        self.assertEqual(len(first), len(second))
        self.assertIn("Forbidden", second[0])
        client.fetch_secondary_resource = lambda *a: ({"items": []}, [])
        client.load_secondary_resources([], force=True)
        self.assertFalse(client.secondary_errors)

    def test_namespace_only_collection(self):
        client = Client(args("--namespace-only", "-n", "team", "--context", "prod"))
        self.assertEqual(client.args.metrics_source, "metrics-server")
        self.assertEqual(client.metrics_server_pods_path(), "/apis/metrics.k8s.io/v1beta1/namespaces/team/pods")
        commands = []
        client.ensure_available = lambda: None
        def run(command, timeout=None):
            commands.append(command)
            if command[:2] == ["config", "view"]:
                return "user"
            if command[0] == "version":
                return '{}'
            if "--raw" in command:
                return '{"items":[{"metadata":{"namespace":"team","name":"p"},"containers":[{"name":"c","usage":{"cpu":"0","memory":"0"}}]}]}'
            if command[:2] == ["get", "pods"]:
                return '{"items":[{"metadata":{"namespace":"team","name":"p","uid":"uid"},"spec":{"containers":[{"name":"c"}]}}]}'
            return '{"items":[]}'
        client.run = run
        snapshot = client.load_snapshot()
        self.assertFalse(snapshot.cluster_scope_available)
        self.assertTrue(snapshot.metrics_available)
        self.assertFalse(any(c[:2] in (["get", "nodes"], ["get", "pv"], ["get", "namespaces"]) for c in commands))
        self.assertFalse(any("-A" in c or any("/nodes" in x for x in c) for c in commands))
        payload = json.loads(M["dump_snapshot_json"](snapshot))
        self.assertIsNone(payload["cluster"]["nodes"])
        self.assertIsNone(payload["cluster"]["usage"])
        self.assertEqual(payload["pods"][0]["usage"]["cpu_m"]["current"], 0)
        self.assertIn("Nodes: N/A", M["dump_snapshot"](snapshot))
        app = App(Screen(), client.args, client)
        app.snapshot = snapshot
        app.draw()
        findings = app.health_scheduling_findings(snapshot)
        self.assertTrue(all(severity != "critical" for _, severity in findings))
        self.assertIn("N/A", findings[0][0])

    def test_metric_zero_missing_stale(self):
        usage = Usage(cpu_m=0, mem_b=10, observed_at=time.time())
        self.assertEqual(M["usage_with_fallback"](usage, Usage(cpu_m=999)).cpu_m, 0)
        self.assertTrue(math.isnan(M["dump_current_value"](0, 999, [], False)))
        quality = M["metric_quality"](usage)
        self.assertEqual(quality["cpu_m"]["state"], "zero")
        self.assertEqual(quality["net_rx_bps"]["state"], "missing")
        usage.observed_at = time.time() - 60
        self.assertEqual(M["metric_quality"](usage)["cpu_m"]["state"], "stale")
        self.assertIsNone(M["json_metric"](M["MISSING"]))
        self.assertEqual(M["format_bytes"](M["MISSING"]), "N/A")

    def test_time_aligned_histories_and_gaps(self):
        history = M["TimedHistory"]
        result = M["aggregate_histories"]([history([(10, 1), (20, 2)]), history([(20, 10), (30, 20)])])
        self.assertEqual(result.timestamps, [10, 20, 30])
        self.assertTrue(math.isnan(result[0]))
        self.assertEqual(result[1], 12)
        self.assertTrue(math.isnan(result[2]))
        app = object.__new__(App)
        app.args = args()
        self.assertEqual(app.graph_line([1, M["MISSING"], 1], 1, 3), "█ █")
        chart = app.chart_values(history([(10, 1), (30, 1)]), 1, 5)
        self.assertTrue(math.isnan(chart[2]))

    def test_missing_percent_and_chart(self):
        app = object.__new__(App)
        app.args = args()
        self.assertTrue(math.isnan(M["ratio"](M["MISSING"], 100)))
        self.assertEqual(M["format_percent_value"](M["MISSING"]), "N/A")
        self.assertEqual(app.bar(4, M["MISSING"]), "[    ]")

    def test_cron_unknown_timezone(self):
        now = dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc)
        self.assertIsNone(M["cron_next_after"]("* * * * *", now)[0])
        self.assertIsNone(M["cron_next_after"]("* * * * *", now, "Unknown/Zone")[0])
        self.assertEqual(M["cron_next_after"]("* * * * *", now, "UTC")[0], now + dt.timedelta(minutes=1))

    def test_timezone_compatibility(self):
        now = dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc)
        with patch.dict(sys.modules, {"zoneinfo": None}):
            next_time, warning = M["cron_next_after"]("* * * * *", now, "Europe/Moscow")
            self.assertIsNone(next_time)
            self.assertIn("unavailable", warning)

    def test_diagnostics_respect_metrics_source_and_scope(self):
        client = Client(args("--namespace-only", "-n", "team", "--context", "prod"))
        client.ensure_available = lambda: None
        calls = []
        client.run = lambda command, timeout=None: calls.append(command) or ("yes" if command[0] == "auth" else '{"items":[]}')
        client.diagnostics_lines()
        self.assertFalse(any("nodes/proxy" in call or "nodes.metrics.k8s.io" in call for call in calls))
        self.assertTrue(any("pods.metrics.k8s.io" in call and "team" in call for call in calls))

    def test_oversized_labels_are_not_retained(self):
        client = Client(args())
        self.assertIsNone(client.prom_counter_rate("node", "counter", {"label": "x" * 5000}, 1, time.time()))
        self.assertFalse(client.prom_counter_previous)
        self.assertTrue(client.cache_warnings)

    def test_last_good_log_survives_failure(self):
        app = App(Screen(), args("--demo"), M["DemoClient"](args("--demo")))
        snapshot = M["DemoClient"](args("--demo")).load_snapshot()
        app.snapshot = snapshot
        pod = snapshot.pods[0]
        app.current_pod = (pod.namespace, pod.name)
        app.current_container = pod.containers[0].name
        app.log_lines = ["last good"]
        app.log_tail, app.log_timestamps, app.log_previous = 200, True, False
        client = Client(args())
        def failed(*a, **kw):
            raise DataError("output exceeds limit")
        client.get_logs = failed
        app.client = client
        app.load_logs()
        deadline = time.monotonic() + 2
        while app.jobs and time.monotonic() < deadline:
            app.poll_results()
            time.sleep(0.005)
        self.assertEqual(app.log_lines, ["last good"])
        self.assertIn("exceeds", app.message)

    def test_container_types_and_effective_requests(self):
        def container(name, cpu, **extra):
            return dict(name=name, resources={"requests": {"cpu": cpu}}, **extra)
        pod = {"spec": {"containers": [container("app", "1")],
                        "initContainers": [container("sidecar", "500m", restartPolicy="Always"), container("init", "2")],
                        "ephemeralContainers": [container("debug", "99")], "overhead": {"cpu": "100m"}}}
        self.assertEqual(M["sum_pod_requests"](pod)[0], 2600)
        self.assertEqual([c.kind for c in M["make_container_infos"](pod)], ["app", "sidecar", "init", "ephemeral"])
        pod["spec"]["resources"] = {"requests": {"cpu": "3"}}
        self.assertEqual(M["sum_pod_requests"](pod)[0], 3100)
        pod["spec"]["containers"][0]["resources"]["limits"] = {"cpu": "1"}
        pod["spec"]["initContainers"][0]["resources"]["limits"] = {"cpu": "500m"}
        pod["spec"]["initContainers"][1]["resources"]["limits"] = {"cpu": "2"}
        self.assertEqual(M["pod_resource_totals"](pod, "limits")[0], 2600)

    def test_valid_exponent_quantities(self):
        self.assertEqual(M["parse_cpu_millis"]("1e-3"), 1)
        self.assertEqual(M["parse_cpu_millis"](".5"), 500)
        self.assertEqual(M["parse_bytes"]("1e6"), 1000000)
        self.assertEqual(M["parse_bytes"]("1E"), 10 ** 18)

    def test_all_demo_pages_render(self):
        config = args("--demo")
        client = M["DemoClient"](config)
        app = App(Screen(), config, client)
        app.snapshot = client.load_snapshot()
        app.current_node = app.snapshot.nodes[0].name
        app.current_pod = (app.snapshot.pods[0].namespace, app.snapshot.pods[0].name)
        app.current_namespace = app.snapshot.pods[0].namespace
        for page in ("overview", "node", "namespace", "pod", "health", "resources", "cronjobs", "logs", "viewer"):
            with self.subTest(page=page):
                app.page = page
                app.draw()
        # Render the same pages with missing metrics and gaps, including NaN percentages.
        app.snapshot.metrics_available = False
        for row in app.snapshot.nodes + app.snapshot.pods:
            for name in ("usage_cpu_m", "usage_mem_b", "net_rx_bps", "net_tx_bps", "fs_read_bps", "fs_write_bps"):
                setattr(row, name, M["MISSING"])
            row.cpu_history = M["TimedHistory"]([(time.time() - 10, 1), (time.time(), M["MISSING"])])
        for page in ("overview", "node", "namespace", "pod", "health", "resources"):
            with self.subTest(missing_page=page):
                app.page = page
                app.draw()


if __name__ == "__main__":
    unittest.main()
