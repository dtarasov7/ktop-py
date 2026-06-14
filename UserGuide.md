# ktop-py.py User Guide

## Purpose

`ktop-py.py` is a read-only terminal dashboard for Kubernetes. It is meant for operators who need a lightweight tool that can be copied to a server and run with the `kubectl` access already available there.

The interface follows the practical flow of `ktop`:

1. Start with the cluster overview.
2. Check nodes, namespaces, and pods.
3. Drill down into node, namespace, pod, owner, and container logs.
4. Open read-only `describe` or YAML when the table view is not enough.
5. Use health, resource risk, diagnostics, and JSON dump modes for deeper checks.

`ktop-py.py` does not modify cluster objects. There are no delete, restart, scale, exec, edit, or apply actions.

## Installation

Copy `ktop-py.py` to the target machine and make it executable:

```bash
chmod +x ./ktop-py.py
```

Check Python:

```bash
python3 --version
```

Check Kubernetes access:

```bash
kubectl version
kubectl get nodes
```

For real clusters, `ktop-py.py` shells out to `kubectl`; it does not include a Python Kubernetes client.

## Startup Modes

Start against the current kubeconfig context:

```bash
./ktop-py.py
```

Start with a specific context:

```bash
./ktop-py.py --context staging
```

Start with a specific kubeconfig:

```bash
./ktop-py.py --kubeconfig /path/to/kubeconfig
```

Show all namespaces, which is the default:

```bash
./ktop-py.py
```

Limit the display scope to one namespace:

```bash
./ktop-py.py --namespace production
```

Use synthetic demo data:

```bash
./ktop-py.py --demo
```

Run without live metrics:

```bash
./ktop-py.py --metrics-source none
```

Run offline self-tests:

```bash
./ktop-py.py --self-test
```

## Overview Screen

The overview screen has these areas:

- Header
- Cluster Summary
- Primary table: nodes or namespaces
- Pods table
- Footer with context-specific hotkeys

The header shows the current Kubernetes context, server version, kubeconfig user, namespace display scope, metrics status, refresh state, and `ktop-py.py` version.

Cluster Summary shows cluster age, ready nodes, namespace count, deployment readiness, pod readiness, volume counts, PV/PVC capacity, and CPU/MEM/Net/Disk charts when history is available.

The primary table starts in nodes mode. Press `g` to toggle it between:

- Nodes
- Namespaces

The pods table follows the selected namespace filter. If no namespace filter is set, it shows pods from all namespaces.

## Navigation Basics

| Key | Action |
| --- | ------ |
| `Tab` / `Shift+Tab` | Move focus between the primary overview table and pods |
| `Up` / `Down` | Move the selected row |
| `PageUp` / `PageDown` | Scroll faster |
| `Home` / `End` | Jump to the first or last row |
| `Left` / `Right` | Horizontally scroll the focused table |
| `Enter` | Open the selected row |
| `j` | Open CronJob diagnostics |
| `h` / `!` | Open Problems / Health |
| `z` | Open Resource Risk |
| `x` | Open Metrics / RBAC diagnostics |
| `Esc` | Go back, clear active filter, or confirm quit from overview |
| `q` | Quit |
| `?` | Open the help page |

Hotkeys are normalized:

- `c` and `C` are equivalent.
- Russian ЙЦУКЕН letters on the same physical keys are accepted.
- The physical `/` key is accepted as `/`, `.`, or `,` depending on the active layout.

Functional keys are intentionally avoided because some terminals send them as ESC sequences.

## Namespace Handling

`ktop-py.py` starts in all-namespaces mode unless `--namespace` is provided.

Press `2` to open the namespace picker. The picker always lists all loaded namespaces, not only the current namespace filter. Use `/` inside the picker to filter the list, then press `Enter` to apply the selected namespace. Choose `(all)` to clear the namespace filter.

The `g` overview toggle is different from namespace filtering:

- `g` changes the primary overview table between nodes and namespaces.
- `2` changes the namespace display scope for the pods table and details.

## Sorting and Table Filters

Press `/` while a table is focused to edit that table's row filter. Press `Enter` to apply it. Press `Esc` while editing to cancel.

Column hotkeys sort the focused table. Press the same key again to reverse the order.

Node sort keys:

| Key | Column |
| --- | ------ |
| `n` | NAME |
| `a` | STATUS |
| `r` | RST |
| `i` | IP |
| `p` | PODS |
| `t` | TAINTS |
| `s` | PRESSURE |
| `v` | VOLS |
| `k` | DISK |
| `c` | CPU |
| `m` | MEM |
| `e` | NET RX |
| `o` | DISK R |
| `w` | DISK W |

Namespace sort keys:

| Key | Column |
| --- | ------ |
| `n` | NAMESPACE |
| `s` | STATUS |
| `p` | PODS |
| `a` | READY |
| `r` | RST |
| `f` | FAIL |
| `c` | CPU |
| `m` | MEMORY |
| `e` | NET RX |
| `o` | DISK R |
| `w` | DISK W |

Pod sort keys:

| Key | Column |
| --- | ------ |
| `n` | NAMESPACE |
| `p` | POD |
| `r` | READY |
| `s` | STATUS |
| `t` | RST |
| `a` | AGE |
| `v` | VOLS |
| `i` | IP |
| `o` | NODE |
| `c` | CPU |
| `m` | MEMORY |

CronJob sort keys:

| Key | Column |
| --- | ------ |
| `n` | NAMESPACE |
| `j` | NAME |
| `s` | STATUS |
| `l` | LAST |
| `x` | NEXT |
| `a` | ACTIVE |
| `o` | OK |
| `f` | FAIL |
| `p` | P95 |

`d` is reserved for describe, so node Disk sorting uses `k`.

## Detail Screens

### Node Detail

Open a node from the overview nodes table with `Enter`.

Node Detail shows:

- node status, roles, age, IP, hostname,
- CPU, memory, network, and disk charts,
- machine/system fields,
- conditions, labels, annotations, taints, pressures, and event count,
- pods running on the node.

From Node Detail:

- select a pod and press `Enter` to open Pod Detail,
- press `d` or `y` to open describe/YAML,
- press `Esc` to go back.

### Namespace Detail

Switch the overview primary table to namespaces with `g`, select a namespace, then press `Enter`.

Namespace Detail shows namespace status, pod readiness, restarts, failures, CPU/MEM/Net/IO summaries, and pods in that namespace.

### Pod Detail

Open a pod from the overview, node detail, or namespace detail.

Pod Detail shows:

- status, node, namespace, IP, age, restarts,
- CPU, memory, network, and disk charts,
- pod info, conditions, resource requests and limits,
- labels and annotations,
- containers table.

From Pod Detail:

| Key | Action |
| --- | ------ |
| `Enter` / `l` | Open logs for selected container |
| `n` | Open the node running this pod |
| `o` | Open Workload / Owner view |
| `d` / `y` | Open describe/YAML |
| `Esc` | Go back |

### Workload / Owner View

Press `o` from Pod Detail.

The owner view follows ownerReferences such as:

- Pod -> ReplicaSet -> Deployment
- Pod -> StatefulSet
- Pod -> DaemonSet
- Pod -> Job
- Pod -> CronJob through Job ownership when loaded

It shows desired/ready/updated/available counts, strategy or schedule, selectors, parent owner, controlled pods, and related events.

## CronJob Diagnostics

Press `j` from any page to open the CronJob diagnostics list.

This page is a read-only operational view built from the Kubernetes objects already loaded by `ktop-py.py`: `CronJob`, `Job`, related `Pod`, and `Event` objects. It does not install a controller, CRD, webhook, database, or alert channel.

The table columns are:

| Column | Meaning |
| ------ | ------- |
| NAMESPACE / NAME | CronJob identity |
| SCHEDULE / TZ | `spec.schedule` and `spec.timeZone`; non-UTC time zones are approximated as local time on Python 3.8 |
| SUSP | Whether `spec.suspend` is true |
| LAST | Age of `status.lastScheduleTime` |
| NEXT | Next expected schedule, or how late it is |
| LATE | Dead-man delay beyond the expected next schedule |
| ACTIVE | Count of active Jobs reported by the CronJob status |
| OK / FAIL | Completed and failed Job counts visible in the current snapshot |
| P50 / P95 / P99 | Duration percentiles calculated from visible completed Jobs |
| STATUS | `OK`, `Active`, `Suspended`, `Missed`, `Failed`, `LongRunning`, `Slow`, or `Unknown` |
| HINT | Short reason or next check |

Dead-man logic uses `status.lastScheduleTime` when available; otherwise it uses the CronJob creation time. `ktop-py.py` calculates the next schedule after that reference. If that next expected time is in the past by more than `startingDeadlineSeconds`, or by more than 300 seconds when no deadline is set, the CronJob is marked `Missed`.

SLA duration logic is intentionally local to the loaded snapshot. P50/P95/P99 are calculated from Jobs that still exist under the CronJob history limits. If successful Job history is small, percentiles are useful as a quick hint, not as long-term SLO evidence.

Status rules:

| Status | Trigger |
| ------ | ------- |
| `Suspended` | `spec.suspend` is true |
| `Unknown` | Schedule cannot be parsed with standard five-field cron syntax |
| `Missed` | Expected next run is late past the deadline/grace window |
| `Failed` | Latest visible Job failed |
| `LongRunning` | Latest active Job is much longer than historical P95 |
| `Slow` | Latest completed Job is much longer than historical P95 |
| `Active` | CronJob has active Jobs and no warning condition was found |
| `OK` | No warning condition was found |

Press `Enter` on a CronJob row to open its detail page. The detail page shows:

- Info: status, schedule, timezone, suspension state, last/next schedule, last success, and hint.
- SLA: active/succeeded/failed counts, late time, P50/P95/P99, latest Job name and status.
- Context: suggestions, recent Jobs, and related events.
- Related Pods: pods owned by visible Jobs of the CronJob; press `Enter` on a pod to open Pod Detail and then logs.

CronJob findings also appear on Problems / Health under the Workloads / Events panel. JSON dump output contains a top-level `cronjobs` array with the same status, timing, percentile, latest Job, severity, and suggestion fields.

## Describe and YAML Viewer

Press:

- `d` for `kubectl describe`,
- `y` for `kubectl get ... -o yaml`.

The viewer supports selected nodes, namespaces, pods, pods from detail tables, current log context, and workload owners.

Viewer controls:

| Key | Action |
| --- | ------ |
| `d` / `y` | Switch between describe and YAML for the same object |
| `r` | Reload the object |
| `w` | Toggle wrapping |
| `f` | Toggle plain copy mode without frames/header/footer |
| `/` | Start live regex search and highlight |
| `n` / `p` | Next / previous match |
| `g` / `b` | Top / bottom |
| `Esc` | Back |

Search behavior is intentionally search-and-highlight, not line filtering. While typing, matches are highlighted immediately. If the first match is outside the viewport, the viewer scrolls to it. After `Enter`, the full describe/YAML output remains visible and matching text stays highlighted. Invalid regex falls back to case-insensitive substring search.

## Container Logs

Open logs from Pod Detail with `Enter` or `l`.

Logs are loaded through `kubectl logs` and refreshed by polling when stream mode is enabled. This is not native Kubernetes streaming.

| Key | Action |
| --- | ------ |
| `s` | Toggle periodic refresh |
| `p` | Toggle `kubectl logs --previous` when no search query is active |
| `c` / `[` / `]` | Switch container |
| `t` | Toggle timestamps |
| `w` | Toggle wrapping |
| `f` | Toggle plain copy mode |
| `m` | Load 100 more tail lines |
| `/` | Start live regex search and highlight |
| `n` / `p` | Next / previous match while search is active |
| `g` / `b` | Top / bottom |
| `r` | Reload logs |
| `Esc` | Back |

If you manually scroll up, follow mode is locked so refreshes do not force you back to the bottom. Press `b` or `End` to return to the bottom and resume follow.

Plain copy mode removes frames, headers, footers, and control lines so the terminal selection contains only the log text.

## Problems / Health

Press `h` or `!`.

### Panel layout

The Health page is a panel-based operational view. Use `Tab` / `Shift+Tab` to move focus between panels. Use `Up` / `Down`, `PageUp` / `PageDown`, `Home` / `End` to scroll the focused panel, and `Left` / `Right` to scroll wide rows horizontally.

The panels are:

| Panel | Contents |
| ----- | -------- |
| Runtime | NotReady, pressured, cordoned, or tainted nodes; unhealthy pods; pods with readiness problems or high restart counts |
| Workloads / Events | Workloads that are not ready, CronJob findings, and Kubernetes Warning events |
| Resource Pressure / Collection | resource pressure signals, ResourceQuota usage, LimitRange policies, scheduler-fit findings, and collection warnings |

The summary cards above the panels show counts of currently visible findings: runtime problems, workload/event problems, resource pressure rows, scheduler-fit rows, and collection warnings. Green means none, yellow means warning-level findings exist, and red means critical findings exist or the count is high enough to deserve immediate attention.

The page is read-only and uses the loaded cluster snapshot.

### Resource Pressure row types

The `Resource Pressure / Collection` panel mixes several related signals. The row prefix tells you what kind of signal you are looking at:

| Prefix | Meaning |
| ------ | ------- |
| `NODE` | Node-level pressure. `cap` is node allocatable, `use` is current usage, `req` is the sum of scheduled pod requests on that node, and `lim` is the sum of scheduled pod limits on that node. |
| `NS` | Namespace share of total cluster allocatable resources. This is not the same thing as a Kubernetes `ResourceQuota`; it is a cluster-share view computed from loaded pods. |
| `QUOTA` | Kubernetes `ResourceQuota` status. Values come from `status.used` and `status.hard`. |
| `LRNG` | Kubernetes `LimitRange` policy. These rows describe defaults, min/max values, and max limit/request ratios. |
| `SCHED` | Scheduler-fit result: whether a pod can fit on the currently loaded nodes under the supported hard scheduling rules. |
| `WARN` | Collection warning, usually caused by missing RBAC or an optional command failing. |

`NODE` and `NS` rows are shown only when they cross a warning or critical threshold. `QUOTA` and `LRNG` rows are informational even when they are healthy, because they explain namespace policy. `SCHED` rows are shown for Pending or unscheduled pods, and for running pods whose current node no longer satisfies hard placement constraints.

### Resource Pressure logic

Resource pressure intentionally separates runtime pressure, scheduling reservations, and limit overcommit. These are different questions:

| Question | Field | Interpretation |
| -------- | ----- | -------------- |
| "Is the cluster or node busy right now?" | `use` | Current live usage from the selected metrics source. |
| "How much has the scheduler reserved?" | `req` | Sum of CPU or memory requests. Requests drive scheduling decisions. |
| "How much could containers be allowed to consume?" | `lim` | Sum of CPU or memory limits. Limits can exceed allocatable capacity in many clusters. |
| "What is the comparison base?" | `cap` | Node allocatable for `NODE`; total cluster allocatable for `NS`. |

When live metrics are available, `use` is live usage. If no history exists yet, the UI may use request values as a fallback in summary-style calculations so the screen is not empty, but pressure findings should be read as strongest when live metrics are present.

The thresholds are:

| Signal | Warning | Critical |
| ------ | ------- | -------- |
| Memory usage / allocatable | `>= 75%` | `>= 90%` |
| CPU usage / allocatable | `>= 90%`; `>= 100%` is shown as saturated | not critical by itself |
| Memory requests / allocatable | `>= 80%` | `>= 100%` |
| CPU requests / allocatable | `>= 90%` | not critical by itself |
| Limits / allocatable | `> 100%` overcommit warning | not critical by itself |
| ResourceQuota used / hard | `>= 80%` | `>= 98%` |

Important consequences:

- `usage > request` is not a health failure by itself. Requests are reservations, not a ceiling.
- Memory requests at or above allocatable are critical because memory is not safely compressible and pods may become impossible to place.
- CPU requests near allocatable are a planning warning. CPU is compressible, so the warning means "scheduling headroom is low", not "the node is broken".
- Limits above allocatable are overcommit indicators. They are useful for capacity review, but are not critical by themselves because not all containers usually consume their limits at the same time.
- `NS` rows compare a namespace to total cluster allocatable. They show cluster-share pressure, not quota enforcement.
- `NODE` rows include the node taint count as context. Taints matter because available capacity on a tainted node may be unusable for many pods.

### ResourceQuota and LimitRange

`ktop-py.py` loads `resourcequotas` and `limitranges` as optional objects. If RBAC denies access, Health still works and adds a collection warning.

ResourceQuota rows use Kubernetes `status.used` and `status.hard`. The common resources displayed are `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, `cpu`, `memory`, and `pods`. Quota severity uses `used / hard`: `>= 80%` is warning, `>= 98%` is critical. This is stricter than limit overcommit because ResourceQuota is an admission control boundary: once the hard value is reached, new matching objects can be rejected.

LimitRange rows describe namespace defaults and constraints. They can include:

- `defaultReq`: default request applied to containers that omit a request,
- `default`: default limit applied to containers that omit a limit,
- `min` and `max`: allowed per-container bounds,
- `maxRatio`: maximum limit/request ratio.

A normal LimitRange row is green because it is policy information, not pressure. A LimitRange with no limit items is shown as a warning because it exists but does not define enforceable limit entries.

### Scheduler-fit logic

Scheduler-fit answers a practical question: "With the objects loaded in this snapshot, which nodes could accept this pod?" It is an approximation of Kubernetes scheduling, not a scheduler replacement.

For each non-terminal pod, `ktop-py.py` checks candidate nodes using these hard rules:

- node must be `Ready`,
- node must not be cordoned (`spec.unschedulable`),
- `nodeSelector` keys must match node labels exactly,
- required node affinity must match: `requiredDuringSchedulingIgnoredDuringExecution` with `matchExpressions` and `matchFields`,
- supported affinity operators are `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, and `Lt`,
- blocking `NoSchedule` and `NoExecute` taints must be tolerated by pod tolerations,
- requested CPU and memory must fit into remaining node allocatable resources.

For a pod already running on a node, its own request is added back before checking that same node. This avoids marking the current node as full only because the pod itself is already consuming scheduled request capacity.

Scheduler-fit row format:

```text
SCHED <namespace/pod> <status> feasible=<matching>/<all> nodes=<first-candidates> req=<cpu>/<mem> blocked=<reason-counts>
```

Severity:

- `critical`: a Pending, Unknown, or unscheduled pod has zero feasible nodes,
- `warning`: a Pending, Unknown, or unscheduled pod has exactly one feasible node,
- `ok`: a Pending, Unknown, or unscheduled pod has two or more feasible nodes,
- `warning`: a running pod's current node violates hard placement rules such as selector, affinity, taints, Ready state, or cordon state.

`blocked=` summarizes why nodes were rejected. Common reason keys are `not-ready`, `cordoned`, `selector`, `affinity`, `taints`, `cpu`, and `memory`.

Current limitations: scheduler-fit does not evaluate pod affinity or anti-affinity, preferred node affinity, topology spread constraints, storage topology, PVC zone binding, host ports, extended resources, image locality, PodDisruptionBudgets, priority/preemption, admission webhooks, custom scheduler plugins, or other scheduler extender behavior. Treat it as an operator-facing diagnostic for the most common hard placement blockers.

## Resource Risk

Press `z`.

Resource Risk focuses on resource configuration and usage pressure. It reports:

- containers without CPU or memory requests, counted separately as `cpu:` and `mem:`,
- containers without CPU or memory limits, counted separately as `cpu:` and `mem:`,
- high usage/request ratios,
- high usage/limit ratios,
- top CPU and memory consumers by namespace,
- top CPU and memory consumers by workload owner.

### Missing requests and limits

Missing requests and limits are counted per container and per resource. A container that has neither CPU nor memory request increments both `cpu:` and `mem:` request counters. The same rule is used for limits. In the table, the `MISSING` column shows `cpu`, `mem`, or `cpu,mem`, and the `OWNER` column shows the workload owner chain when it can be resolved.

Missing limits are reported as policy risk signals. Some teams intentionally avoid limits, so treat this section according to your cluster policy.

### Usage ratio logic

Usage ratios are evaluated only when live metrics are available. If live metrics are unavailable, `High Usage Ratios` shows a message instead of pretending that request fallback is live usage.

The ratio thresholds are:

| Ratio | Threshold | Meaning |
| ----- | --------- | ------- |
| `usage / request` | `>= 80%` | The container is approaching or exceeding the amount it asked the scheduler to reserve. This is a right-sizing signal, not an automatic health failure. |
| `usage / limit` | `>= 90%` | The container is close to the configured limit and may be throttled or killed depending on the resource. |

Rows with ratio `>= 100%` are highlighted more strongly. For CPU, `usage > request` can be perfectly normal; for memory it is still common, but it is useful for right-sizing and capacity planning. Health treats cluster-level pressure separately from these container-level sizing signals.

### Top consumers

Top consumer panels rank namespaces and workload owners by CPU and memory. When live metrics are available, the ranking uses live usage. When live metrics are not available, it falls back to requests so the page still gives a capacity planning view. This fallback means "reserved by configuration", not "currently consumed".

Resource Risk is also panel-based. Use `Tab` / `Shift+Tab` to move between `Missing Requests / Limits`, `High Usage Ratios`, and `Top Consumers`. Use vertical scrolling for long row lists and horizontal scrolling for wide owner or pod/container names.

## Metrics / RBAC Diagnostics

Press `x` in the TUI or run:

```bash
./ktop-py.py --diagnostics
```

Diagnostics check:

- `auth can-i` for `nodes.metrics.k8s.io`,
- `auth can-i` for `pods.metrics.k8s.io`,
- `auth can-i get nodes/proxy`,
- raw Metrics API endpoints,
- kubelet `/metrics`,
- cAdvisor `/metrics/cadvisor`.

The goal is to explain why Prometheus mode or Metrics Server mode is not providing data.

## Loaded Kubernetes Objects and RBAC

Each refresh loads a read-only snapshot through `kubectl`. For the richest view, the kubeconfig user should be able to list:

- `nodes`, `pods`, `namespaces`, `events`,
- `deployments`, `replicasets`, `statefulsets`, `daemonsets`, `jobs`, `cronjobs`,
- `persistentvolumes`, `persistentvolumeclaims`,
- `resourcequotas`, `limitranges`.

If access to optional objects is denied, `ktop-py.py` keeps running and records a collection warning. The affected panels may be incomplete. For example, without `resourcequotas` access, Health cannot show real namespace quota `used/hard` values; without `limitranges` access, it cannot show namespace default request/limit policies; without `jobs` or `cronjobs` access, CronJob diagnostics cannot connect schedules to visible runs and pods.

Prometheus mode additionally needs `get nodes/proxy` for kubelet and cAdvisor endpoints. Metrics Server mode needs read access to `nodes.metrics.k8s.io` and `pods.metrics.k8s.io`.

## Metrics Sources

### Prometheus Mode

```bash
./ktop-py.py --metrics-source prometheus
```

Prometheus mode directly scrapes Prometheus-format endpoints already exposed by Kubernetes components through the API server node proxy:

- `/api/v1/nodes/<node>/proxy/metrics`
- `/api/v1/nodes/<node>/proxy/metrics/cadvisor`

No external Prometheus server is required.

Prometheus mode can provide:

- node CPU/MEM,
- pod CPU/MEM,
- container CPU/MEM,
- network receive/transmit rates,
- filesystem read/write rates,
- retained history for charts and trends.

Rate metrics need at least two samples. On first startup, `ktop-py.py` may show `prometheus (warming)`.

Useful options:

```bash
./ktop-py.py --metrics-source prometheus --prometheus-components kubelet,cadvisor
./ktop-py.py --metrics-source prometheus --prometheus-scrape-interval 10s
./ktop-py.py --metrics-source prometheus --prometheus-retention 1h
./ktop-py.py --metrics-source prometheus --prometheus-max-samples 10000
```

### Metrics Server Mode

```bash
./ktop-py.py --metrics-source metrics-server
```

Metrics Server mode reads:

- `/apis/metrics.k8s.io/v1beta1/nodes`
- `/apis/metrics.k8s.io/v1beta1/pods`

It provides node, pod, and container CPU/MEM. Metrics Server does not provide network or disk I/O, so those panels remain unavailable or zero in this mode.

### No Metrics Mode

```bash
./ktop-py.py --metrics-source none
```

No metrics mode disables live usage collection. Tables and summaries fall back to requests and allocatable values where available.

## Graphs and Retention

Prometheus mode keeps metric samples in memory inside the running process. The retention settings affect only the current `ktop-py.py` process:

- no disk persistence,
- no PromQL engine,
- no external time-series database.

Charts and sparklines use Unicode block glyphs by default:

```bash
./ktop-py.py --graph-style unicode
```

Use ASCII fallback only when the terminal font cannot display block glyphs:

```bash
./ktop-py.py --graph-style ascii
KTOP_PY_GRAPH_STYLE=ascii ./ktop-py.py
```

## JSON Dump

Dump mode prints one snapshot and exits:

```bash
./ktop-py.py --dump
./ktop-py.py --dump --output json
```

JSON includes cluster metadata, nodes, pods, containers, CronJob diagnostics, metrics status, warnings, and loaded timestamp.

Pod selection options:

```bash
./ktop-py.py --dump --output json --dump-pods all
./ktop-py.py --dump --output json --dump-pods none
./ktop-py.py --dump --output json --dump-pods problems
./ktop-py.py --dump --output json --dump-pods top-cpu
./ktop-py.py --dump --output json --dump-pods top-mem
./ktop-py.py --dump --output json --dump-pod-filter api
./ktop-py.py --dump --output json --dump-pod-namespaces kube-system,default
./ktop-py.py --dump --output json --dump-pod-limit 20
```

Max values are calculated over the graph-width sample window by default. To collect a short interval before dumping:

```bash
./ktop-py.py --dump --output json --dump-max-interval 30s --refresh-interval 5
```

Add raw Kubernetes objects only when needed:

```bash
./ktop-py.py --dump --output json --include-raw
```

## Column Selection

Show only specific node columns:

```bash
./ktop-py.py --node-columns 'NAME,STATUS,CPU,MEM,DISK R,DISK W,NET TX,NET RX'
```

Show only specific pod columns:

```bash
./ktop-py.py --pod-columns NAMESPACE,POD,STATUS,CPU,MEMORY
```

Unknown column names are ignored.

## Architecture Diagrams

PlantUML architecture diagrams are stored in `diagramms/`. Each English diagram has a Russian copy with the `-ru` suffix.

## Troubleshooting

### kubectl is not found

Install `kubectl` or pass a custom path:

```bash
./ktop-py.py --kubectl /path/to/kubectl
```

### Prometheus mode has no data

Check node proxy RBAC and cAdvisor access:

```bash
kubectl auth can-i get nodes/proxy
kubectl get nodes
kubectl get --raw /api/v1/nodes/<node-name>/proxy/metrics
kubectl get --raw /api/v1/nodes/<node-name>/proxy/metrics/cadvisor
```

Run built-in diagnostics:

```bash
./ktop-py.py --diagnostics
```

### Metrics Server mode has no data

Check Metrics API access:

```bash
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods
```

If Metrics Server is not installed, use Prometheus mode or no metrics mode.

### Frames or graphs look wrong

Use a UTF-8 locale and a font with box-drawing and block glyphs. If only graph glyphs are broken, use:

```bash
./ktop-py.py --graph-style ascii
```

### The TUI feels stuck during refresh

Snapshot refresh runs in a background worker. The UI keeps rendering the last successful snapshot. The header shows loading, stale, or error state.

If kubectl commands are slow, reduce scope with `--namespace`, check API server latency, or increase command timeout:

```bash
./ktop-py.py --command-timeout 30
```

## Verification Commands

Use these checks after modifying the script:

```bash
python3 -m py_compile ktop-py.py
python3 -m tabnanny ktop-py.py
./ktop-py.py --self-test
./ktop-py.py --demo --dump
./ktop-py.py --demo --dump --output json
./ktop-py.py --help
```
