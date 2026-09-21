"""Reproducible synthetic benchmark for todo 16/17; never contacts Kubernetes."""
import gc
import json
import statistics
import threading
import time
import tracemalloc
from dataclasses import replace

from test_ktop_ui import M, Client, args, app_for, finish


def milliseconds(action, repeat=7):
    samples = []
    for _ in range(repeat):
        before = time.perf_counter()
        action()
        samples.append((time.perf_counter() - before) * 1000)
    return statistics.median(samples)


def benchmark():
    app = app_for(45, 160)
    template = app.snapshot.pods[0]
    app.snapshot = replace(app.snapshot, pods=[replace(template, name='pod-%d' % i, namespace='ns-%d' % (i % 50)) for i in range(2000)],
                           namespaces=['ns-%d' % i for i in range(50)], namespaces_count=50)
    def cold():
        app.derived_cache = M['OrderedDict']()
        app.all_namespace_rows()
    cold_ms = milliseconds(cold, 3)
    cached_ms = milliseconds(app.all_namespace_rows, 100)
    app.draw()
    draw_ms = milliseconds(app.draw)
    clock_ms = milliseconds(app.draw_clock_tick)
    app.page = 'diagnostics'
    release = threading.Event()
    app.client.diagnostics_lines = lambda: (release.wait(5), ['done'])[1]
    app.open_diagnostics()
    keys = []
    for _ in range(200):
        before = time.perf_counter()
        app.handle_key(M['curses'].KEY_DOWN)
        keys.append((time.perf_counter() - before) * 1000)
    app.cancel_jobs()
    release.set()
    finish(app)

    def scrape(parallelism):
        client = Client(args('--kubectl-parallelism', str(parallelism)))
        client.raw = lambda path, timeout=None: (time.sleep(0.02), 'sample 1')[1]
        return milliseconds(lambda: list(client.endpoint_responses(('n', 'kubelet', '/%d' % i) for i in range(12))), 3)
    serial_ms, parallel_ms = scrape(1), scrape(3)

    client = Client(args('--max-metric-series', '100', '--max-history-points', '1000', '--prometheus-max-samples', '10'))
    tracemalloc.start()
    def churn(start):
        for i in range(start, start + 10000):
            client.add_history_sample(('pod', 'ns', 'p%d' % (i // 5), 'cpu'), float(i), float(i))
        gc.collect()
        return tracemalloc.get_traced_memory()[0]
    warm_bytes, stable_bytes = churn(0), churn(10000)
    tracemalloc.stop()
    items = [{'metadata': {'name': 'pod-%d' % i, 'namespace': 'ns-%d' % (i % 50), 'labels': {'app': 'api' if i % 10 == 0 else 'worker'}}, 'spec': {'nodeName': 'n1'}} for i in range(2000)]
    full_bytes = len(json.dumps({'items': items}).encode())
    filtered = [item for item in items if item['metadata']['namespace'] == 'ns-0' and item['metadata']['labels']['app'] == 'api']
    filtered_bytes = len(json.dumps({'items': filtered}).encode())
    return dict(terminal='160x45', pods=2000, namespaces=50, namespace_uncached_ms=cold_ms,
                namespace_cached_ms=cached_ms, full_draw_ms=draw_ms, clock_tick_ms=clock_ms,
                key_p95_ms=sorted(keys)[189], endpoint_serial_ms=serial_ms, endpoint_parallel3_ms=parallel_ms,
                history_warm_bytes=warm_bytes, history_stable_bytes=stable_bytes, series=len(client.metric_history),
                points=client.history_points, fixture_unfiltered_bytes=full_bytes, fixture_filtered_bytes=filtered_bytes)


if __name__ == '__main__':
    print(json.dumps(benchmark(), indent=2))
