# ktop-py.py

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](CHANGELOG-rus.md)

`ktop-py.py` - это single-file TUI на Python 3.8 для мониторинга Kubernetes-кластера. Проект вдохновлен Go-утилитой `ktop`, которая лежит в подкаталоге `ktop/`, но рассчитан на copy-and-run сценарии: скопировать один файл и запустить без установки сторонних Python-пакетов.

Программа работает в read-only режиме: она показывает Kubernetes-объекты, метрики, логи, `describe`, YAML, health findings и resource risk signals через `kubectl`.

## Главное

- Один исполняемый файл: `ktop-py.py`.
- Совместимость с Python 3.8.
- Нет сторонних Python-зависимостей.
- Для реального кластера используется существующая конфигурация `kubectl`.
- По умолчанию показываются все namespaces; `--namespace` ограничивает отображение.
- Curses TUI с ktop-like overview, рамками, графиками, таблицами и detail-страницами.
- На overview верхняя таблица переключается между nodes и namespaces.
- Drill-down навигация: overview -> node/namespace -> pod -> container logs.
- Read-only viewer для `kubectl describe` и YAML выбранных nodes, namespaces, pods и owners.
- Логи контейнера: current/previous, переключение контейнеров, timestamps, wrap, live search/highlight и plain copy mode.
- Problems / Health экран для runtime-проблем, resource pressure, ResourceQuota/LimitRange policies и scheduler-fit checks.
- Диагностика CronJob: dead-man проверка расписания, success/failure counts последних Job, percentiles длительности, связанные pod-ы, events и подсказки.
- Resource Risk экран для missing requests/limits, usage ratios и top consumers.
- Workload / Owner view для owner chain и controlled pods.
- Metrics / RBAC diagnostics из TUI или CLI.
- Режимы метрик: direct Prometheus-format scrape, Metrics Server API или no metrics.
- In-memory retention для charts, sparklines, trends и max values.
- JSON dump для автоматизации и диагностики.
- Hotkeys работают при CapsLock и русской раскладке ЙЦУКЕН на тех же физических клавишах.
- Demo и self-test режимы не требуют Kubernetes и `kubectl`.

## Требования

- Python 3.8 или новее.
- Терминал с поддержкой curses.
- UTF-8 locale для Unicode-рамок и графиков.
- `kubectl` в `PATH` для работы с реальным кластером.
- kubeconfig с доступом к целевому кластеру.

`kubectl` не нужен для `--demo`, `--demo --dump` и `--self-test`.

## Быстрый старт

```bash
chmod +x ./ktop-py.py
./ktop-py.py
```

Запуск с конкретным context:

```bash
./ktop-py.py --context production
```

Запуск в одном namespace:

```bash
./ktop-py.py --namespace kube-system
```

Предпросмотр UI без Kubernetes:

```bash
./ktop-py.py --demo
```

Печать неинтерактивного demo-снимка:

```bash
./ktop-py.py --demo --dump
```

Печать JSON:

```bash
./ktop-py.py --dump --output json
```

Запуск diagnostics:

```bash
./ktop-py.py --diagnostics
```

Запуск встроенных offline-проверок:

```bash
./ktop-py.py --self-test
```

## Основные клавиши

| Клавиша | Действие |
| ------- | -------- |
| `Tab` / `Shift+Tab` | Переключить фокус между overview-таблицами или между панелями на Health / Resource Risk |
| `Left` / `Right` | Горизонтально прокрутить таблицу в фокусе |
| `g` | Переключить верхнюю overview-таблицу между nodes и namespaces |
| `j` | Открыть диагностику CronJob |
| `2` | Открыть namespace picker |
| `/` | Редактировать фильтр таблицы или live search в logs/describe/YAML |
| `Enter` | Открыть выбранный node, namespace, pod или container logs |
| `d` / `y` | Открыть `kubectl describe` / YAML выбранного объекта |
| `h` / `!` | Открыть Problems / Health |
| `z` | Открыть Resource Risk |
| `x` | Открыть Metrics / RBAC diagnostics |
| `o` | Из Pod Detail открыть Workload / Owner view |
| `n` | Из Pod Detail открыть node, где запущен pod |
| `Esc` | Вернуться назад, очистить активный фильтр или подтвердить выход из overview |
| `q` | Выйти |
| `?` | Показать help |

Горячие клавиши колонок сортируют таблицу в фокусе. Например, `c` сортирует по CPU, `m` по memory, `r` по restarts. Для сортировки node Disk используется `k`, потому что `d` открывает describe.

Problems / Health использует такую же навигацию по панелям, как Resource Risk: `Tab` / `Shift+Tab` переключает панель в фокусе, `Up` / `Down` прокручивает строки, `Left` / `Right` прокручивает широкие строки по горизонтали.

Диагностика CronJob работает в read-only режиме и использует загруженные `cronjobs`, `jobs`, `pods` и `events`. Страница `j` подсвечивает пропущенные расписания, failed latest Jobs, долгие active Jobs и регрессии длительности. `Enter` открывает detail-страницу CronJob с SLA percentiles, связанными pod-ами, recent Jobs, events и подсказками для проверки.

Health resource pressure разделяет разные сигналы: memory usage и memory requests считаются более сильными capacity risks, CPU requests - более мягкий planning signal, а limits выше allocatable показываются как overcommit warning, а не как critical failure. ResourceQuota проверяется по `status.used/status.hard`; LimitRange показывает namespace resource policy defaults и bounds.

Для полного вывода Health и CronJob kubeconfig user должен уметь list `resourcequotas`, `limitranges`, `jobs` и `cronjobs` в дополнение к обычным nodes, pods, workloads, events, PV и PVC. Недостающие optional permissions показываются как collection warnings.

## Метрики

`ktop-py.py` оставляет зависимости минимальными и не встраивает Kubernetes client libraries. Метрики собираются через `kubectl get --raw`:

- `/api/v1/nodes/<node>/proxy/metrics`
- `/api/v1/nodes/<node>/proxy/metrics/cadvisor`
- `/apis/metrics.k8s.io/v1beta1/nodes`
- `/apis/metrics.k8s.io/v1beta1/pods`

Поддерживаемые режимы:

| Режим | Поведение |
| ----- | --------- |
| `prometheus` / `prom` | Scrape Prometheus-format endpoints kubelet/cAdvisor через Kubernetes API proxy |
| `metrics-server` | Читает Metrics Server API напрямую и показывает CPU/MEM nodes, pods и containers |
| `none` | Отключает live metrics и показывает fallback по requests/allocatable |

Запуск по умолчанию сначала пробует Prometheus mode и откатывается на Metrics Server API, если direct scrape недоступен. Явный `--metrics-source prometheus` работает строго и показывает ошибки scrape вместо тихого fallback.

Prometheus mode не требует установленного Prometheus-сервера. Он использует Kubernetes-компоненты, которые уже отдают метрики в Prometheus format. Для cAdvisor rates нужны два scrape, поэтому первый refresh может показать `prometheus (warming)`.

Настройка retention и scrape cadence:

```bash
./ktop-py.py --metrics-source prometheus --prometheus-scrape-interval 30s --prometheus-retention 1h --prometheus-max-samples 10000
```

По умолчанию графики используют Unicode block/sparkline glyphs. Чтобы проверить, что шрифт терминала отображает "лесенку", выполните в bash:

```bash
echo "▁▂▃▄▅▆▇█"
```

При подключении с Windows через PuTTY выберите шрифт, который содержит эти символы; например, подходит `Cascadia Mono` или Cascadia Code. `--graph-style ascii` или `KTOP_PY_GRAPH_STYLE=ascii` нужны только как fallback для терминалов без таких символов.

## JSON Dump

`--dump` печатает один snapshot и завершает процесс. Это удобно для CI, support bundles и анализа состояния кластера вне TUI.

```bash
./ktop-py.py --dump --output json
./ktop-py.py --dump --output json --dump-pods problems
./ktop-py.py --dump --output json --dump-pods top-cpu --dump-pod-limit 10
./ktop-py.py --dump --output json --dump-pod-namespaces kube-system,default
./ktop-py.py --dump --output json --dump-max-interval 30s --refresh-interval 5
```

По умолчанию raw Kubernetes objects не включаются. Добавляйте `--include-raw` только когда они действительно нужны.

JSON output включает секцию `cronjobs`: schedule status, last/next schedule, late seconds, success/failure counts, P50/P95/P99 длительности, latest Job status, severity и suggestions.

## Документация

- [UserGuide-ru.md](UserGuide-ru.md) - подробное руководство пользователя на русском.
- [UserGuide.md](UserGuide.md) - подробное руководство пользователя на английском.
- [KTOP_PY_COMPARISON.md](KTOP_PY_COMPARISON.md) - сравнение ktop и ktop-py.py.
- [diagramms/](diagramms/) - архитектурные диаграммы PlantUML на английском и русском.

## Проверка

Offline-проверки:

```bash
python3 -m py_compile ktop-py.py
python3 -m tabnanny ktop-py.py
./ktop-py.py --self-test
./ktop-py.py --demo --dump
./ktop-py.py --help
```

Smoke-test Prometheus retention/charts запускался на двухузловом kind-кластере:

```bash
./ktop-py.py --metrics-source prometheus --prometheus-scrape-interval 1s
```

## Автор

**Tarasov Dmitry**
- Email: dtarasov7@gmail.com

## Атрибуция

Части этого кода были сгенерированы с помощью ассистента.
