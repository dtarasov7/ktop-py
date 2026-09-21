# Changelog

All notable changes to `ktop-py.py` are documented in this file.

## [1.3.0] - 2026-09-17

### Added

- Added read-only incident diagnostics for Service → EndpointSlice → Pod relationships, degradation causes, incident timelines, and workload security contexts. The network view also links related Ingress and NetworkPolicy objects and clearly separates static configuration analysis from connectivity testing.
- Added CPU CFS throttling rates, OOMKilled details, init-container failures, probe failures, eviction/ephemeral-storage findings, and node pressure to Problems / Health.
- Added versioned JSON snapshots with `schema_version: 1`, UID-aware `--diff`, and offline `--replay` with `F5`/`F6` frame navigation.
- Added scoped support bundles with namespace/object selectors, atomic mode-0600 writes, source age/completeness metadata, explicit `--include-raw`, and best-effort sensitive-data redaction.
- Added command palette, Literal/Regex mode, source-status view, saved column/filter presets, breadcrumbs, compact terminal layout, and Unicode display-width handling.
- Added `--namespace-only`, server-side pod label/field selectors, bounded scrape parallelism/deadlines, and extended refresh profiling.

### Changed

- Logs, describe, YAML, and diagnostics now run in cancelable background jobs; stale results are rejected when the selected object changes.
- Metrics and secondary-source state now distinguish missing, zero, stale, forbidden, unavailable, and not-yet-loaded data without substituting requests for live usage.
- Refresh work now uses bounded concurrency, TTL caches, pod indexes, ring buffers, cached rendering/search results, and early Prometheus metric filtering.
- Resource calculations now account for init containers, restartable sidecars, ephemeral containers, pod overhead, metric timestamps, and gaps in aggregate history.

### Security

- Regex search is literal by default; explicit regex evaluation has a hard time budget in a separate process.
- Subprocess output, logs, JSON input, metric histories, and Prometheus counter state now have explicit size or retention limits.
- Terminal-bound external text and invalid UTF-8 are rendered safely, and kubeconfig inspection no longer reads unnecessary raw credential data.
- Metrics/RBAC guidance now describes the elevated reach of `nodes/proxy` and recommends the lower-privilege Metrics Server path where suitable.

### Fixed

- Preserved the explicitly selected Kubernetes context and persistent secondary-source errors until a successful refresh.
- Corrected namespace-scoped Metrics Server requests and namespace-only operation without mandatory cluster-wide node/PV access.
- Corrected CronJob timezone handling and stopped reporting confident missed schedules when timezone data is unsupported or unknown.
- Kept selection by UID across refresh/sort and now reports when the selected object disappears.

## [1.2.0] - 2026-07-24

### Added

- Added progressive overview updates: nodes and pods are published before detail resources finish loading.
- Added `--secondary-refresh-interval`, `--kubectl-parallelism`, and `--profile-refresh` performance controls.

### Changed

- Nodes and pods now load concurrently; workloads, policies, volumes, and events use bounded parallel collection with TTL caching.
- Kubernetes context, user, and server version are cached for the process lifetime.
- `--namespace` now scopes namespaced `kubectl get` requests instead of first loading all namespaces.

### Fixed

- Removed repeated full container-metrics scans for every pod when building a snapshot.

## [1.1.0] - 2026-06-14

### Added

- Added read-only CronJob diagnostics page opened with `j`.
- Added dead-man schedule checks for missed CronJob runs using `lastScheduleTime`, creation time fallback, and `startingDeadlineSeconds` grace.
- Added visible Job success/failure counts and P50/P95/P99 duration percentiles for CronJobs.
- Added CronJob detail page with suggestions, recent Jobs, related events, and related pods drill-down.
- Added CronJob findings to Problems / Health and `cronjobs` data to JSON/text dumps.

## [1.0.1] - 2026-06-14

### Fixed

- Escaped terminal control characters before TUI rendering so logs, metadata, describe, and YAML text cannot inject inert-looking control bytes into curses output.
- Added guarded regex search fallback for overly long or potentially expensive live search patterns to reduce local TUI freeze risk.

## [1.0.0] - 2026-06-13

First public GitHub release.

### Added

- Single-file Python 3.8 Kubernetes TUI with no third-party Python dependencies.
- Read-only overview with cluster summary, nodes, namespaces, pods, charts, tables, and horizontal column scrolling.
- Node, namespace, pod, container logs, workload owner, describe, and YAML detail views.
- Direct Prometheus-format scrape mode for kubelet/cAdvisor metrics without requiring a deployed Prometheus server.
- Metrics Server mode and no-metrics fallback mode.
- In-memory metric retention, sparklines, trend arrows, and max-value reporting.
- Split network and disk charts for receive/transmit and read/write rates.
- Problems / Health page with runtime findings, resource pressure, ResourceQuota/LimitRange policy display, and scheduler-fit diagnostics.
- Resource Risk page for missing requests/limits, high usage ratios, and top consumers.
- Metrics/RBAC diagnostics from the TUI and CLI.
- JSON/text dump mode for automation and offline troubleshooting.
- Container logs with current/previous selection, container switching, timestamps, wrapping, live search/highlight, and plain copy mode.
- Hotkey normalization for CapsLock and Russian ЙЦУКЕН physical-key layout.
- Demo and self-test modes that do not require Kubernetes or `kubectl`.
