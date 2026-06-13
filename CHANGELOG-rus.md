# Журнал изменений

В этом файле фиксируются заметные изменения `ktop-py.py`.

## [1.0.0] - 2026-06-13

Первый публичный релиз для GitHub.

### Добавлено

- Single-file Kubernetes TUI на Python 3.8 без сторонних Python-зависимостей.
- Read-only overview со сводкой кластера, nodes, namespaces, pods, графиками, таблицами и горизонтальной прокруткой колонок.
- Detail-экраны для node, namespace, pod, container logs, workload owner, describe и YAML.
- Direct Prometheus-format scrape mode для kubelet/cAdvisor metrics без необходимости устанавливать Prometheus server.
- Metrics Server mode и no-metrics fallback mode.
- In-memory retention метрик, sparklines, trend arrows и max-value reporting.
- Раздельные network и disk графики для receive/transmit и read/write rates.
- Problems / Health экран с runtime findings, resource pressure, ResourceQuota/LimitRange policies и scheduler-fit diagnostics.
- Resource Risk экран для missing requests/limits, high usage ratios и top consumers.
- Metrics/RBAC diagnostics из TUI и CLI.
- JSON/text dump mode для автоматизации и offline troubleshooting.
- Container logs с current/previous selection, переключением containers, timestamps, wrapping, live search/highlight и plain copy mode.
- Нормализация hotkeys для CapsLock и русской раскладки ЙЦУКЕН на тех же физических клавишах.
- Demo и self-test modes, которые не требуют Kubernetes или `kubectl`.
