# ktop-py.py

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](CHANGELOG.md)

`ktop-py.py` is a single-file Python 3.8 terminal UI for Kubernetes cluster monitoring. It is inspired by the Go `ktop` project , but it is designed for copy-and-run use on machines where installing extra Python packages or copying a compiled binary is inconvenient.

The program is read-only: it inspects Kubernetes objects, metrics, logs, describe output, YAML, health findings, and resource risk signals through `kubectl`.

## Highlights

- One executable file: `ktop-py.py`.
- Python 3.8 compatible, no third-party Python packages.
- Uses existing `kubectl` configuration for real cluster access.
- All namespaces are shown by default; `--namespace` scopes the display.
- Curses TUI with ktop-like overview, framed panels, charts, tables, and detail pages.
- Overview can show either nodes or namespaces above the pod table.
- Direct drill-down: overview -> node/namespace -> pod -> container logs.
- Read-only `describe` and YAML viewer for selected nodes, namespaces, pods, and owners.
- Container logs with current/previous toggle, container switching, timestamps, wrapping, live search/highlight, and plain copy mode.
- Problems / Health page for runtime issues, resource pressure, ResourceQuota/LimitRange policies, and scheduler-fit checks.
- CronJob diagnostics with dead-man schedule checks, recent Job success/failure counts, duration percentiles, related pods, events, and suggestions.
- Resource Risk page for missing requests/limits, usage ratios, and top consumers.
- Workload / Owner view for pod owner chains and controlled pods.
- Metrics / RBAC diagnostics from TUI or CLI.
- Metrics modes: direct Prometheus-format scrape, Metrics Server API, or no metrics.
- In-memory retention for charts, sparklines, trends, and max values.
- JSON dump mode for automation and offline diagnostics.
- Hotkeys are normalized for CapsLock and Russian ЙЦУКЕН physical-key layout.
- Demo and self-test modes do not require Kubernetes or `kubectl`.

## Requirements

- Python 3.8 or newer.
- A terminal with curses support.
- UTF-8 locale for Unicode frames and graphs.
- `kubectl` in `PATH` for real cluster mode.
- A kubeconfig with access to the target cluster.

`kubectl` is not required for `--demo`, `--demo --dump`, or `--self-test`.

## Quick Start

```bash
chmod +x ./ktop-py.py
./ktop-py.py
```

Run with a specific context:

```bash
./ktop-py.py --context production
```

Run in one namespace:

```bash
./ktop-py.py --namespace kube-system
```

Preview the UI without Kubernetes:

```bash
./ktop-py.py --demo
```

Print a non-interactive demo snapshot:

```bash
./ktop-py.py --demo --dump
```

Print JSON:

```bash
./ktop-py.py --dump --output json
```

Run diagnostics:

```bash
./ktop-py.py --diagnostics
```

Run built-in offline checks:

```bash
./ktop-py.py --self-test
```

## Main Controls

| Key | Action |
| --- | ------ |
| `Tab` / `Shift+Tab` | Cycle focus between overview tables, or between panels on Health / Resource Risk |
| `Left` / `Right` | Scroll the focused table horizontally |
| `g` | Toggle the overview primary table between nodes and namespaces |
| `j` | Open CronJob diagnostics |
| `2` | Open namespace picker |
| `/` | Edit table filter, or live search in logs/describe/YAML |
| `Enter` | Open selected node, namespace, pod, or container logs |
| `d` / `y` | Open `kubectl describe` / YAML for the selected object |
| `h` / `!` | Open Problems / Health |
| `z` | Open Resource Risk |
| `x` | Open Metrics / RBAC diagnostics |
| `o` | From Pod Detail, open Workload / Owner view |
| `n` | From Pod Detail, open the pod's node |
| `Esc` | Go back, clear active filter, or confirm quit from overview |
| `q` | Quit |
| `?` | Show help |

Column hotkeys sort the focused table. For example, `c` sorts by CPU, `m` by memory, and `r` by restarts. Node Disk sorting uses `k` because `d` opens describe.

Problems / Health uses the same panel navigation as Resource Risk: `Tab` / `Shift+Tab` changes the focused panel, `Up` / `Down` scrolls rows, and `Left` / `Right` scrolls wide rows horizontally.

CronJob diagnostics are read-only and use loaded `cronjobs`, `jobs`, `pods`, and `events`. The `j` page highlights missed schedules, failed latest Jobs, long-running Jobs, and duration regressions. `Enter` opens a CronJob detail page with SLA percentiles, related pods, recent Jobs, events, and suggested next checks.

Health resource pressure separates different signals: memory usage and memory requests are treated as stronger capacity risks, CPU requests are a softer planning signal, and limits above allocatable are shown as overcommit warnings rather than critical failures. ResourceQuota is evaluated against `status.used/status.hard`; LimitRange rows show namespace resource policy defaults and bounds.

For complete Health and CronJob output, the kubeconfig user should be able to list `resourcequotas`, `limitranges`, `jobs`, and `cronjobs` in addition to the usual nodes, pods, workloads, events, PVs, and PVCs. Missing optional permissions are reported as collection warnings.

## Metrics

`ktop-py.py` keeps dependencies small and does not embed Kubernetes client libraries. It collects metrics through `kubectl get --raw`:

- `/api/v1/nodes/<node>/proxy/metrics`
- `/api/v1/nodes/<node>/proxy/metrics/cadvisor`
- `/apis/metrics.k8s.io/v1beta1/nodes`
- `/apis/metrics.k8s.io/v1beta1/pods`

Supported modes:

| Mode | Behavior |
| ---- | -------- |
| `prometheus` / `prom` | Scrapes kubelet/cAdvisor Prometheus-format endpoints through the Kubernetes API proxy |
| `metrics-server` | Reads Metrics Server API directly and displays node, pod, and container CPU/MEM |
| `none` | Disables live metrics; usage is N/A, requests/allocatable remain separate |

Default startup tries Prometheus mode first and falls back to Metrics Server API if direct scrape is unavailable. An explicit `--metrics-source prometheus` is strict and reports scrape errors instead of silently falling back.

Prometheus mode does not require a deployed Prometheus server. It uses Kubernetes components that already expose Prometheus-format metrics. cAdvisor rates need two scrapes, so the first refresh may show `prometheus (warming)`.

Tune retention and scrape cadence:

```bash
./ktop-py.py --metrics-source prometheus --prometheus-scrape-interval 30s --prometheus-retention 1h --prometheus-max-samples 10000
```

Graphs use Unicode block/sparkline glyphs by default. To verify that your terminal font can draw the block "staircase", run this in bash:

```bash
echo "▁▂▃▄▅▆▇█"
```

When connecting from Windows through PuTTY, choose a font that includes these glyphs; `Cascadia Mono` or `Cascadia Code` is a known good example. Use `--graph-style ascii` or `KTOP_PY_GRAPH_STYLE=ascii` only as a fallback for terminals without those glyphs.

## kubectl Refresh Performance

The overview loads nodes and pods in parallel and publishes them before slower detail resources finish. Requested workloads, policies, volumes, and events are fetched with bounded parallelism and cached for 30 seconds by default; context, user, and server version are cached for the process lifetime.

When running with `--metrics-source none`, tune the Kubernetes object path rather than Prometheus settings:

```bash
./ktop-py.py --metrics-source none --secondary-refresh-interval 60s --kubectl-parallelism 6
./ktop-py.py --dump --metrics-source none --profile-refresh
```

`--namespace` now scopes namespaced `kubectl get` requests, reducing transferred and parsed data. `--profile-refresh` adds wall time and per-command timings to snapshot warnings.


### Responsive actions, search and presets

Logs, describe/YAML and diagnostics run in background jobs. Reloading the same object retains
previous content and shows progress. `Ctrl-G` cancels the action and pauses log streaming;
leaving the page also cancels its job. Late replies and results for replaced UIDs are discarded.
Opening a different object clears the previous object's buffer.

`F1` or `:` opens the command palette. `F2` switches Literal/Regex search in logs/viewer, including
an active search edit. Russian letter hotkeys remain supported. On CronJobs, `x` sorts NEXT;
diagnostics remain available through the palette. The footer shows contextual hints and breadcrumbs.
Below 80×30, a single focused table is shown; Tab switches focus and left/right scroll columns.
The minimum usable size is 24×6.

The header shows cluster/context/namespace and requested source states with last-success UTC times.
F1 → Sources provides full timestamps, errors and sources not requested yet. If the header cannot
fit all source rows, it explicitly points to Sources. CPU/MEM usage is labelled USE; pod/container
requests, limits and METRIC AGE have separate columns. N/A means no measurement; zero declared
limit means no limit specified. Larger charts with history include time axes and missing-value gaps.

Palette commands include `Columns compact`, `Columns full`, `save NAME` and `load NAME`.
Column/filter presets default to `.ktop-presets.json` in the working directory; use `--preset-file`
to choose another path. Save is explicit, atomic and uses mode 0600. Presets cannot widen
namespace-only scope. Wrap indices have a 100,000-row budget with an explicit truncation marker.
Rendering accounts for CJK/combining terminal cells and escapes bidi/format controls.

```bash
./ktop-py.py -n production --label-selector app=api --field-selector status.phase=Running
./ktop-py.py --kubectl-parallelism 3 --scrape-deadline 20s --profile-refresh
python3 -B -m unittest -q test_ktop_security test_ktop_ui
python3 -B benchmark_ktop.py
```

`--kubectl-parallelism` now limits all concurrent kubectl requests, including UI actions and metrics.
Scrape and endpoint diagnostics use a shared batch deadline, bounded pending responses and error
backoff capped at 60 seconds. Label/field selectors apply to pod lists, not node proxy exposition.
Prometheus collection consumes a sample iterator and filters names before labels; histories use
bounded deques.

TUI overview requests namespaces/deployments/PV/PVC. Other detail groups are requested on their
first page visit, then maintained by TTL. Dump still collects the complete resource set;
namespace-only excludes cluster-scoped requests. Unloaded counters display N/A. Aggregates,
sorted rows, Health, Resource Risk and CronJobs are cached by snapshot, with separate timed
invalidation. Idle header/footer ticks once per second, the body every 5 seconds; input and
new snapshots trigger immediate redraws.

`--profile-refresh` reports parse/build, command times, stdout bytes, peak RSS and series/points;
the TUI footer adds draw duration and terminal dimensions. Peak RSS is the process lifetime maximum.
See [synthetic measurements and limitations](KTOP_PERFORMANCE_REPORT.md). List/watch and paginated
List processing remain deferred; exceeding the byte limit preserves the last successful snapshot.

### Incident diagnostics and offline analysis

The `F1` palette exposes four read-only views:

- `Network Service/EndpointSlice/Pod` connects Services to EndpointSlices and Pods, reports empty endpoints, selector mismatches, `ready`/`serving`/`terminating`, and related Ingresses and NetworkPolicies. This is static configuration analysis; it does not test connectivity.
- `Degradation evidence` reports OOMKilled with exit codes, init-container states, failed Ready/Initialized conditions, probe failures from Events, ephemeral-storage pressure evidence, and measured CFS throttled-period ratios. Source availability is explicit; missing evidence is not treated as healthy.
- `Incident timeline` combines Events with status, Ready, restart, generation/revision, and rollout changes observed between refreshes. It is bounded to 1,000 entries, and polling can miss short transitions.
- `Workload securityContext` inventories declared `privileged`, host namespaces, hostPath, capabilities, `runAsNonRoot`, seccomp, and `automountServiceAccountToken` settings for Pods and workload templates. It does not claim that a workload is compromised.

Network resources and extended workload data are loaded after their page is first opened. Complete results require list access to `services`, `endpointslices.discovery.k8s.io`, `ingresses.networking.k8s.io`, and `networkpolicies.networking.k8s.io`. EndpointSlice readiness is shown with `serving`, `terminating`, and `publishNotReadyAddresses`.

Schema version 1 JSON dumps include a normalized replay snapshot, diagnostics, and timeline. Offline commands never invoke kubectl:

```bash
./ktop-py.py --dump --output json > before.json
./ktop-py.py --dump --output json > after.json
./ktop-py.py --diff before.json after.json --output json
./ktop-py.py --replay before.json after.json
```

In replay TUI, `F5`/`F6` switches files. Diff validates cluster/context and chronological order, correlates objects by UID, and marks name-only identities. Under incomplete scopes, a missing object is `no-longer-visible`, not assumed deleted.

Support bundles are written atomically with mode 0600:

```bash
./ktop-py.py --support-bundle support.json --bundle-namespace production
./ktop-py.py --support-bundle pod.json --bundle-object Pod/production/api --include-raw
./ktop-py.py --replay before.json --support-bundle offline-support.json
```

Kubernetes raw objects require `--include-raw`. When enabled, env/envFrom, annotations, data/stringData, command/args, credential-like keys, and event/status/warning free text are removed; network and security inventory findings remain available. This reduces exposure but cannot guarantee finding secrets in arbitrary strings. A bundle records snapshot age, selected scope, and source states; namespace/object selectors reduce its size.

## JSON Dump

`--dump` prints one snapshot and exits. Use it for CI, support bundles, or comparing cluster state outside the TUI.

```bash
./ktop-py.py --dump --output json
./ktop-py.py --dump --output json --dump-pods problems
./ktop-py.py --dump --output json --dump-pods top-cpu --dump-pod-limit 10
./ktop-py.py --dump --output json --dump-pod-namespaces kube-system,default
./ktop-py.py --dump --output json --dump-max-interval 30s --refresh-interval 5
```

By default, raw Kubernetes objects are omitted. Add `--include-raw` only when you really need them.

JSON output includes `cronjobs`, `diagnostics`, `timeline`, `schema_version`, and a normalized `snapshot` for offline replay. The replay record makes the file larger than the previous format.

## Documentation

- [UserGuide.md](UserGuide.md) - detailed English user guide.
- [UserGuide-ru.md](UserGuide-ru.md) - detailed Russian user guide.
- [KTOP_PY_COMPARISON.md](KTOP_PY_COMPARISON.md) - ktop vs ktop-py.py comparison.
- [diagramms/](diagramms/) - PlantUML architecture diagrams in English and Russian.

## Verification

Offline checks:

```bash
python3 -m py_compile ktop-py.py
python3 -m tabnanny ktop-py.py
./ktop-py.py --self-test
./ktop-py.py --demo --dump
./ktop-py.py --help
```

Prometheus retention/charts smoke test used against a two-node kind cluster:

```bash
./ktop-py.py --metrics-source prometheus --prometheus-scrape-interval 1s
```

## Limits, data quality, and namespace-only access

```bash
./ktop-py.py --namespace-only -n team-a --context production
./ktop-py.py --namespace-only -n team-a --diagnostics
```

`--namespace-only` requires `-n`, defaults to Metrics Server, and skips nodes, PVs, the namespace list, and node metrics. `--metrics-source none` is also supported. Unavailable cluster aggregates are `N/A`/`null`. Diagnostics check the selected source and namespace permissions. Direct kubelet/cAdvisor scraping needs a different access profile: even `get nodes/proxy` grants powerful kubelet APIs, including container execution, and is not an exclusively read-only permission.

Search in logs/describe/YAML is literal by default. Enter `re:pattern` to run regex in a separate process with a 100 ms budget for the whole buffer. `lit:re:text` searches for the literal text `re:text`. Errors and exhausted budgets disable regex for that query and show a reason before falling back to literal search.

Usage never falls back to requests. Missing measurements display as `N/A` and JSON `null`; a measured zero remains zero. Per-object `metric_quality` and CPU/MEM `usage` include `state` (`fresh`, `zero`, `missing`, `stale`), `observed_at`, and `age_seconds`. Stale fields may retain an old value or expose `null` with the last good sample time. `source_status` describes secondary collection state; errors persist alongside the last good response. Histories preserve timestamps and gaps and aggregate by time. JSON consumers must handle nullable measurements.

Default limits:

- `--max-output-bytes 33554432`: 32 MiB combined stdout/stderr per kubectl command; excess output fails the request.
- `--log-limit-bytes 1048576`: request up to 1 MiB of logs, in addition to `--log-tail`.
- `--max-metric-series 20000`: series per cache; retained counter labels are limited to 4096 characters.
- `--max-history-points 250000`: total timestamp/value pairs, in addition to retention and the per-series sample cap. Budget eviction produces a warning.

Histories are isolated by context/kubeconfig source and object UID, with TTL and disappeared-object cleanup. Context is pinned before requests; kubeconfig reads select only necessary fields without `--raw`. Invalid UTF-8 in text is displayed safely; structured JSON decoding is strict.

Container views include app, init, restartable sidecar, and ephemeral containers. Effective requests and limits from Pod spec account for init stages, running sidecars, Pod-level resources, and overhead. This reports declared resources; scheduler allocations during in-place resizing are not inferred. The calculation follows the [Kubernetes resource helper](https://github.com/kubernetes/component-helpers/blob/master/resource/helpers.go). Ephemeral containers are excluded from missing-request/limit findings.

CronJobs with an unknown controller timezone or unsupported `.spec.timeZone` show `Unknown`. Dependency-free Python 3.8 supports UTC; Python 3.9+ uses available IANA zones through `zoneinfo`. Unknown timezones do not produce a calculated `Missed` status.

Regression checks without a cluster connection:

```bash
python3 -B -m unittest -v test_ktop_security
python3 -B ktop-py.py --self-test
```

## Author

**Tarasov Dmitry**
- Email: dtarasov7@gmail.com

## Attribution

Parts of this code were generated with assistant support.
