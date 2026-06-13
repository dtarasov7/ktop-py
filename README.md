# ktop-py.py

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)

`ktop-py.py` is a single-file Python 3.8 terminal UI for Kubernetes cluster monitoring. It is inspired by the Go `ktop` project included in the `ktop/` subdirectory, but it is designed for copy-and-run use on machines where installing extra Python packages or copying a compiled binary is inconvenient.

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

Health resource pressure separates different signals: memory usage and memory requests are treated as stronger capacity risks, CPU requests are a softer planning signal, and limits above allocatable are shown as overcommit warnings rather than critical failures. ResourceQuota is evaluated against `status.used/status.hard`; LimitRange rows show namespace resource policy defaults and bounds.

For complete Health output, the kubeconfig user should be able to list `resourcequotas` and `limitranges` in addition to the usual nodes, pods, workloads, events, PVs, and PVCs. Missing optional permissions are reported as collection warnings.

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
| `none` | Disables live metrics and shows request/allocation fallback |

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

## Author

**Tarasov Dmitry**
- Email: dtarasov7@gmail.com

## Attribution

Parts of this code were generated with assistant support.
