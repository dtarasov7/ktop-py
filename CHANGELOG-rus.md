# Журнал изменений

В этом файле фиксируются заметные изменения `ktop-py.py`.

## [1.3.0] - 2026-09-17

### Добавлено

- Read-only диагностика инцидентов для связей Service → EndpointSlice → Pod, причин деградации, таймлайна инцидента и security context workload. Сетевой экран также связывает Ingress и NetworkPolicy и явно отделяет статический анализ конфигурации от проверки connectivity.
- CPU CFS throttling, детали OOMKilled, ошибки init-контейнеров, probe failures, eviction/ephemeral-storage findings и node pressure в Problems / Health.
- Версионированные JSON snapshots с `schema_version: 1`, UID-aware `--diff` и offline `--replay` с переключением кадров через `F5`/`F6`.
- Support bundle с выбором namespaces/objects, атомарной записью с mode 0600, метаданными возраста/полноты источников, явным `--include-raw` и best-effort маскированием чувствительных данных.
- Command palette, режим Literal/Regex, просмотр состояния источников, сохраняемые presets колонок/фильтров, breadcrumbs, compact layout и корректный расчёт ширины Unicode.
- `--namespace-only`, server-side label/field selectors для pods, ограниченный параллелизм/deadline scrape и расширенное профилирование refresh.

### Изменено

- Logs, describe, YAML и diagnostics выполняются в отменяемых фоновых заданиях; результат отбрасывается, если выбранный объект успел измениться.
- Состояния метрик и secondary-источников теперь различают missing, zero, stale, forbidden, unavailable и not-yet-loaded без подстановки requests вместо live usage.
- Refresh использует ограниченный параллелизм, TTL-кеши, индексы pods, кольцевые буферы, кеширование render/search и ранний отбор Prometheus metrics.
- Расчёт ресурсов учитывает init containers, restartable sidecars, ephemeral containers, pod overhead, timestamps метрик и разрывы aggregate history.

### Безопасность

- Поиск по умолчанию буквальный; явный regex выполняется в отдельном процессе с жёстким бюджетом времени.
- Для subprocess output, logs, входных JSON, metric history и состояния Prometheus counters введены явные ограничения размера или retention.
- Внешний текст и невалидный UTF-8 безопасно отображаются в терминале; чтение kubeconfig больше не загружает ненужные raw credentials.
- Metrics/RBAC guidance теперь объясняет расширенные возможности права `nodes/proxy` и рекомендует менее привилегированный путь через Metrics Server, когда он подходит.

### Исправлено

- Явно выбранный Kubernetes context сохраняется, а ошибки secondary-источников не исчезают до успешного refresh.
- Исправлены namespace-scoped запросы Metrics Server и namespace-only работа без обязательного cluster-wide доступа к nodes/PV.
- Исправлена обработка timezone CronJob; при неподдерживаемой или неизвестной зоне больше не выводится уверенный вывод о пропущенном запуске.
- Выбор объекта сохраняется по UID после refresh/sort; исчезновение выбранного объекта теперь отображается явно.

## [1.2.0] - 2026-07-24

### Добавлено

- Прогрессивное обновление overview: nodes и pods публикуются до завершения загрузки detail-ресурсов.
- Параметры производительности `--secondary-refresh-interval`, `--kubectl-parallelism` и `--profile-refresh`.

### Изменено

- Nodes и pods теперь загружаются параллельно; workloads, policies, volumes и events собираются с ограниченным параллелизмом и TTL-кешем.
- Kubernetes context, user и server version кешируются до завершения процесса.
- `--namespace` теперь ограничивает namespaced-запросы `kubectl get`, а не загружает сначала все namespaces.

### Исправлено

- Убрано повторное полное сканирование container metrics для каждого pod при построении snapshot.

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
