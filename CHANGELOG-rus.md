# Журнал изменений

В этом файле фиксируются заметные изменения `ktop-py.py`.

## [1.1.0] - 2026-06-14

### Добавлено

- Read-only CronJob diagnostics page, открывается клавишей `j`.
- Dead-man schedule checks для пропущенных запусков CronJob на основе `lastScheduleTime`, fallback на creation time и grace из `startingDeadlineSeconds`.
- Success/failure counts видимых Job и P50/P95/P99 percentiles длительности для CronJob.
- CronJob detail page с suggestions, recent Jobs, related events и drill-down в related pods.
- CronJob findings в Problems / Health и секция `cronjobs` в JSON/text dump.

## [1.0.1] - 2026-06-14

### Исправлено

- Control characters теперь экранируются перед выводом в TUI, чтобы logs, metadata, describe и YAML не могли вносить управляющие байты в curses output.
- Для live search добавлен безопасный fallback на substring при слишком длинных или потенциально дорогих regex, чтобы снизить риск локального зависания TUI.

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
