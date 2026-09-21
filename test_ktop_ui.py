"""Regression tests for todo 16/17. Synthetic clients only; no cluster access."""
import copy
import curses
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_ktop_security import M, App, Client, DataError, args


class Screen:
    def __init__(self, height=45, width=160):
        self.height, self.width = height, width
        self.writes = []

    def getmaxyx(self):
        return self.height, self.width

    def addstr(self, y, x, text, attr=0):
        if not (0 <= y < self.height and 0 <= x < self.width):
            raise AssertionError((y, x))
        if M['cell_width'](text) > self.width - x:
            raise AssertionError((x, text, self.width))
        self.writes.append((y, x, text, attr))

    def erase(self):
        self.writes.clear()

    def refresh(self):
        pass


def app_for(height=45, width=160):
    options = args('--demo')
    client = M['DemoClient'](options)
    app = App(Screen(height, width), options, client)
    app.snapshot = client.load_snapshot()
    return app


def finish(app):
    deadline = time.monotonic() + 3
    while (app.jobs or app.job_threads) and time.monotonic() < deadline:
        app.poll_results()
        time.sleep(0.002)
    app.poll_results()
    if app.jobs or app.job_threads:
        raise AssertionError('background job did not finish')


class UiTests(unittest.TestCase):
    def test_latest_request_and_bounded_lane(self):
        app = app_for()
        entered, release = threading.Event(), threading.Event()
        applied = []
        def old():
            entered.set()
            release.wait(2)
            return 'old'
        app.start_job('viewer', 0, old, applied.append)
        self.assertTrue(entered.wait(1))
        for index in range(1, 100):
            app.start_job('viewer', index, lambda index=index: index, applied.append)
        self.assertEqual(len(app.job_threads), 1)
        release.set()
        finish(app)
        self.assertEqual(applied, [99])

    def test_navigation_cancels_late_viewer_and_keeps_last_good(self):
        app = app_for()
        app.page = 'viewer'
        target = M['ObjectTarget']('pod', 'default', 'api', 'api')
        app.viewer_target, app.viewer_mode = target, 'yaml'
        app.viewer_lines = ['last good']
        entered, release = threading.Event(), threading.Event()
        def delayed(*unused):
            entered.set()
            release.wait(2)
            return ['late']
        app.client.yaml_object = delayed
        app.reload_viewer()
        self.assertTrue(entered.wait(1))
        self.assertEqual(app.viewer_lines, ['last good'])
        app.pop_page()
        release.set()
        finish(app)
        self.assertEqual(app.viewer_lines, ['last good'])
        self.assertEqual(app.page, 'overview')

    def test_slow_diagnostics_does_not_block_keys(self):
        app = app_for()
        release = threading.Event()
        app.client.diagnostics_lines = lambda: (release.wait(2), ['done'])[1]
        started = time.monotonic()
        app.handle_key('x')
        durations = []
        for _ in range(100):
            before = time.monotonic()
            app.handle_key(curses.KEY_DOWN)
            durations.append(time.monotonic() - before)
        self.assertLess(time.monotonic() - started, 0.1)
        self.assertLess(sorted(durations)[94], 0.1)
        app.handle_key('\x07')
        release.set()
        finish(app)
        self.assertEqual(app.diagnostics_cache, [])

    def test_cancel_reaps_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.05, cancel.set)
        timer.start()
        before = time.monotonic()
        try:
            with self.assertRaisesRegex(DataError, 'cancelled'):
                M['bounded_command']([sys.executable, '-c', 'import time; time.sleep(20)'], 10, 1024, cancel=cancel)
        finally:
            timer.join()
        self.assertLess(time.monotonic() - before, 0.5)

    def test_global_api_concurrency(self):
        client = Client(args('--kubectl-parallelism', '2'))
        active, peak = 0, 0
        lock = threading.Lock()
        def command(*unused, **kw):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return 0, b'{}', b''
        with patch.dict(M['bounded_command'].__globals__, bounded_command=command):
            with ThreadPoolExecutor(max_workers=10) as executor:
                self.assertEqual(list(executor.map(lambda _: client.run(['get', 'pods']), range(10))), ['{}'] * 10)
        self.assertEqual(peak, 2)

    def test_parallel_endpoints_backoff_and_deadline(self):
        client = Client(args('--kubectl-parallelism', '3', '--scrape-deadline', '1s'))
        calls = []
        def raw(path, timeout=None):
            calls.append(path)
            time.sleep(min(0.03, timeout))
            if path == '/bad':
                raise DataError('forbidden')
            return path
        client.raw = raw
        endpoints = [('node', 'kubelet', '/%d' % i) for i in range(9)]
        started = time.monotonic()
        result = list(client.endpoint_responses(endpoints))
        self.assertLess(time.monotonic() - started, 0.22)
        self.assertEqual(len(result), 9)
        self.assertTrue(all(item[3] is None for item in result))
        list(client.endpoint_responses([('n', 'kubelet', '/bad')]))
        self.assertIn('backoff', list(client.endpoint_responses([('n', 'kubelet', '/bad')]))[0][3])
        self.assertEqual(calls.count('/bad'), 1)
        client.args.scrape_deadline = 0.02
        started = time.monotonic()
        result = list(client.endpoint_responses(endpoints * 100))
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertTrue(any('omitted' in (item[3] or '') for item in result))

    def test_history_deque_and_budgets(self):
        client = Client(args('--max-history-points', '200', '--max-metric-series', '20', '--prometheus-max-samples', '10'))
        now = time.time()
        for index in range(4000):
            client.add_history_sample(('pod', 'ns', str(index % 40), 'cpu'), now + index / 1000, index)
        self.assertLessEqual(client.history_points, 200)
        self.assertLessEqual(len(client.metric_history), 20)
        self.assertTrue(all(isinstance(samples, M['deque']) for samples in client.metric_history.values()))
        self.assertEqual(client.history_points, sum(map(len, client.metric_history.values())))
        client.prune_metric_caches(now + 100000)
        self.assertEqual(client.history_points, 0)

    def test_stream_filters_before_label_parsing(self):
        count = 0
        original = M['parse_prometheus_labels']
        def labels(raw):
            nonlocal count
            count += 1
            return original(raw)
        text = 'unneeded{x="value"} 1\n' * 10000 + 'node_memory_working_set_bytes 42\n'
        with patch.dict(M['iter_prometheus_samples'].__globals__, parse_prometheus_labels=labels):
            result = list(M['iter_prometheus_samples'](text, {'node_memory_working_set_bytes'}))
        self.assertEqual(result, [('node_memory_working_set_bytes', {}, 42)])
        self.assertEqual(count, 1)

    def test_selectors_and_detail_demand(self):
        client = Client(args('-n', 'demo', '--label-selector', 'app=api', '--field-selector', 'status.phase=Running'))
        calls = []
        client.json = lambda command, required, warnings: (calls.append(command), {'items': []})[1]
        client.json_all_namespaces_or_scoped('pods', True, [])
        self.assertEqual(calls, [['get', 'pods', '-n', 'demo', '--selector', 'app=api', '--field-selector', 'status.phase=Running']])
        app = App(Screen(), client.args, client)
        calls.clear()
        client.load_secondary_resources([])
        resources = {command[1] for command in calls}
        self.assertEqual(resources, {'namespaces', 'deployments', 'pv', 'pvc'})
        app.push_page('cronjobs')
        calls.clear()
        client.load_secondary_resources([])
        self.assertEqual({command[1] for command in calls}, {'cronjobs', 'jobs', 'events'})

    def test_derived_cache_and_time_invalidation(self):
        app = app_for()
        first = app.current_pods()
        self.assertIs(first, app.current_pods())
        self.assertIs(app.health_data(), app.health_data())
        self.assertIs(app.resource_risk_data(), app.resource_risk_data())
        self.assertIs(app.all_namespace_rows(), app.all_namespace_rows())
        app.pod_sort = ('CPU', False)
        self.assertIsNot(first, app.current_pods())
        old_health = app.health_data()
        with patch.object(M['time'], 'time', return_value=time.time() + 10):
            self.assertIsNot(old_health, app.health_data())
        old_index = app.pods_by_namespace()
        app.snapshot = copy.deepcopy(app.snapshot)
        self.assertIsNot(old_index, app.pods_by_namespace())
        self.assertIsNot(first, app.current_pods())

    def test_uid_selection_sort_replace_and_reselect(self):
        app = app_for()
        app.focus = 'pods'
        rows = copy.deepcopy(app.current_pods())
        for index, row in enumerate(rows):
            row.raw.setdefault('metadata', {})['uid'] = str(index)
        app.reconcile_selection('pods', rows)
        selected = app.row_identity(rows[0])
        self.assertEqual(app.reconcile_selection('pods', list(reversed(rows))), len(rows) - 1)
        self.assertEqual(app.selection_ids['pods'], selected)
        new = copy.deepcopy(rows)
        new[0].raw['metadata']['uid'] = 'replacement'
        self.assertEqual(app.reconcile_selection('pods', new), -1)
        self.assertIn('disappeared', app.message)
        app.handle_key('\n')
        self.assertEqual(app.page, 'overview')
        app.handle_key(curses.KEY_DOWN)
        self.assertGreaterEqual(app.selected['pods'], 0)

    def test_unicode_wrap_search_and_cache(self):
        app = app_for()
        self.assertEqual(M['cell_width']('界e\u0301'), 3)
        self.assertEqual(M['truncate']('界界x', 4), '界 ~')
        lines = ['界e\u0301界test']
        rendered = app.text_view_lines(lines, 4, True, True)
        self.assertTrue(all(M['cell_width'](line) <= 4 for line in rendered))
        self.assertEqual(''.join(rendered), lines[0])
        self.assertIs(rendered, app.text_view_lines(lines, 4, True, True))
        matches = app.search_match_lines(rendered, 'test')
        self.assertIs(matches, app.search_match_lines(rendered, 'test'))
        self.assertIsNot(rendered, app.text_view_lines(list(lines), 4, True, True))
        app.add_highlighted(0, 0, '界test', 'test', 10)
        highlighted = [item for item in app.stdscr.writes if item[2] == 'test']
        self.assertEqual(highlighted[-1][1], 2)

    def test_all_pages_at_multiple_sizes(self):
        for height, width in [(45, 160), (22, 80), (16, 60), (8, 30)]:
            app = app_for(height, width)
            pod = app.snapshot.pods[0]
            app.current_pod = (pod.namespace, pod.name)
            app.current_node = app.snapshot.nodes[0].name
            app.current_namespace = pod.namespace
            app.current_container = pod.containers[0].name
            app.log_lines, app.viewer_lines = ['界e\u0301 test'] * 20, ['kind: Pod']
            for page in ('overview', 'pod', 'node', 'namespace', 'namespaces', 'logs', 'viewer', 'cronjobs', 'health', 'resources', 'owner', 'diagnostics', 'sources', 'help'):
                with self.subTest(size=(height, width), page=page):
                    app.page = page
                    app.draw()
                    self.assertTrue(app.stdscr.writes)
            app.handle_key(curses.KEY_F1)
            app.draw()
            self.assertIn('Command', app.stdscr.writes[0][2])

    def test_replaced_viewer_uid_rejects_completed_result(self):
        app = app_for()
        pod = app.snapshot.pods[0]
        pod.raw.setdefault('metadata', {})['uid'] = 'old'
        app.viewer_target = M['ObjectTarget']('pod', pod.namespace, pod.name, pod.name)
        app.viewer_title = pod.name
        app.viewer_lines = ['last good']
        app.page = 'viewer'
        release, entered = threading.Event(), threading.Event()
        def slow():
            entered.set()
            release.wait(2)
            return ['wrong incarnation']
        app.start_job('viewer', 'old', slow, lambda lines: setattr(app, 'viewer_lines', lines))
        self.assertTrue(entered.wait(1))
        snapshot = copy.deepcopy(app.snapshot)
        snapshot.pods[0].raw['metadata']['uid'] = 'new'
        app.pending_snapshot = snapshot
        app.poll_results()
        release.set()
        finish(app)
        self.assertEqual(app.viewer_lines, ['last good'])
        self.assertIsNone(app.viewer_target)
        self.assertIn('replaced', app.viewer_title)

    def test_clock_tick_does_not_redraw_body(self):
        app = app_for()
        app.draw()
        app.stdscr.writes.clear()
        app.draw_clock_tick()
        rows = {entry[0] for entry in app.stdscr.writes}
        self.assertTrue(rows.issubset(set(range(app.header_height)) | {43, 44}))

    def test_view_row_budget_and_narrow_unicode(self):
        view = M['ViewLines'](['x' * 200000], 1, True, True)
        self.assertEqual(len(view), 100001)
        self.assertIn('budget', view.lines[-1])
        self.assertLessEqual(M['cell_width'](M['ViewLines'](['界'], 1, True, True)[0]), 1)

    def test_source_age_and_forbidden_visible(self):
        app = app_for()
        app.snapshot.source_status = {
            'pods': {'state': 'fresh', 'observed_at': time.time() - 100},
            'events': {'state': 'forbidden', 'observed_at': None},
        }
        lines = app.source_lines()
        self.assertIn('pods: stale', lines[0])
        self.assertIn('UTC', lines[0])
        self.assertIn('events: forbidden', lines[1])
        app.draw()
        self.assertTrue(any('events:forbidden' in text for _, _, text, _ in app.stdscr.writes))

    def test_palette_presets_and_hotkeys(self):
        app = app_for()
        with tempfile.TemporaryDirectory(prefix='.ktop-ui-test-', dir=Path(__file__).parent) as directory:
            app.args.preset_file = str(Path(directory) / 'presets.json')
            app.set_columns(True)
            app.filters['pods'] = 'api'
            app.preset_action('save', 'my view')
            self.assertTrue(Path(app.args.preset_file).exists())
            self.assertEqual(Path(app.args.preset_file).stat().st_mode & 0o777, 0o600)
            app.set_columns(False)
            app.filters['pods'] = ''
            app.preset_action('load', 'my view')
            self.assertEqual(app.filters['pods'], 'api')
            self.assertIn('POD', app.args.pod_columns)
            app.page = 'logs'
            app.filters['logs'] = 'literal.'
            app.handle_key(curses.KEY_F2)
            self.assertEqual(app.filters['logs'], 're:literal.')
            app.handle_key(curses.KEY_F2)
            self.assertEqual(app.filters['logs'], 'literal.')
            app.editing_filter = 'logs'
            app.filter_buffer = 'draft'
            app.handle_key(curses.KEY_F2)
            self.assertEqual(app.filter_buffer, 're:draft')
            self.assertEqual(app.filters['logs'], 'literal.')
            app.handle_key('\x1b')
            self.assertEqual(app.filters['logs'], 'literal.')
            app.handle_key(curses.KEY_F1)
            app.handle_key('s')
            app.handle_key('\x1b')
            self.assertFalse(app.palette_open)
            self.assertEqual(M['hotkey']('ч'), 'x')
            app.page = 'cronjobs'
            app.handle_key('x')
            self.assertEqual(app.page, 'cronjobs')
            self.assertEqual(app.cronjob_sort[0], 'NEXT')


if __name__ == '__main__':
    unittest.main()
