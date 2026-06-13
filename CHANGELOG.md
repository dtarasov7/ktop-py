# Changelog

All notable changes to `ktop-py.py` are documented in this file.

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
