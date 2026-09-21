# ktop-py.py

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](CHANGELOG-rus.md)

`ktop-py.py` - это single-file TUI на Python 3.8 для мониторинга Kubernetes-кластера. Проект вдохновлен Go-утилитой `ktop`, но рассчитан на copy-and-run сценарии: скопировать один файл и запустить без установки сторонних Python-пакетов.

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
| `none` | Отключает live metrics; usage — N/A, requests/allocatable показаны отдельно |

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

## Производительность refresh через kubectl

Overview параллельно загружает nodes и pods и публикует их до завершения более медленных detail-запросов. Запрошенные workloads, policies, volumes и events загружаются с ограниченным параллелизмом и по умолчанию кешируются на 30 секунд; context, user и server version кешируются до завершения процесса.

При запуске с `--metrics-source none` настраивать нужно путь Kubernetes-объектов, а не Prometheus:

```bash
./ktop-py.py --metrics-source none --secondary-refresh-interval 60s --kubectl-parallelism 6
./ktop-py.py --dump --metrics-source none --profile-refresh
```

`--namespace` теперь ограничивает namespaced-запросы `kubectl get`, уменьшая объем передаваемых и разбираемых данных. `--profile-refresh` добавляет wall time и время каждой команды в warnings snapshot.


### Отзывчивость, поиск и пресеты

Logs, describe/YAML и diagnostics загружаются в фоне. Прежнее содержимое сохраняется при повторной
загрузке того же объекта; footer показывает ожидание. `Ctrl-G` отменяет задание и приостанавливает
log streaming; уход со страницы также отменяет задание. Запоздавшие результаты и ответы для
заменённого UID не применяются. Начальный переход к другому объекту очищает его старый буфер.

`F1` или `:` открывает палитру команд. В logs/viewer `F2` переключает Literal/Regex, включая
редактируемый запрос. Русская раскладка для буквенных hotkeys сохраняется; на странице CronJobs
`x` сортирует NEXT, диагностика доступна через палитру. Contextual hotkeys и путь навигации видны
в footer. На терминалах меньше 80×30 показывается одна активная таблица; Tab меняет фокус,
стрелки влево/вправо прокручивают колонки. Минимум — 24×6.

Header показывает cluster/context/namespace, состояния запрошенных источников и время последнего
успеха в UTC. Полные timestamps, ошибки и не запрошенные источники доступны через F1 → Sources.
Если строки не помещаются, header явно указывает на продолжение в Sources. Usage CPU/MEM помечены
USE; pod/container requests, limits и METRIC AGE доступны отдельными колонками. N/A означает
отсутствие измерения; нулевой declared limit означает, что лимит не задан. Большие графики с
историей имеют временную шкалу; пропущенные measurements оставляют разрывы.

Палитра: `Columns compact` / `Columns full`, `save NAME` / `load NAME`. По умолчанию пресеты
колонок и фильтров сохраняются в `.ktop-presets.json` текущего каталога; путь задаёт `--preset-file`.
Запись выполняется только по команде Save, атомарно, с правами 0600. Namespace-only scope нельзя
расширить через preset. Количество строк индекса wrap ограничено 100 000; достижение бюджета
помечается отдельной строкой. CJK и combining symbols учитываются в экранных ячейках; bidi/format
controls выводятся экранированными.

```bash
./ktop-py.py -n production --label-selector app=api --field-selector status.phase=Running
./ktop-py.py --kubectl-parallelism 3 --scrape-deadline 20s --profile-refresh
python3 -B -m unittest -q test_ktop_security test_ktop_ui
python3 -B benchmark_ktop.py
```

`--kubectl-parallelism` теперь ограничивает все одновременные kubectl-запросы, включая UI и
метрики. Scrape и диагностика endpoints используют общий deadline на batch, ограниченное число
ожидающих ответов и backoff ошибок до 60 секунд. `--label-selector`/`--field-selector` применяются
к списку pods; фильтр не сокращает node proxy exposition. Prometheus samples разбираются
итератором с отбором нужных имён до labels. Истории используют bounded deque.

В TUI overview запрашивает namespaces/deployments/PV/PVC; остальные detail-ресурсы — при первом
открытии соответствующего экрана, затем обновляет их по TTL. Dump по-прежнему собирает полный
набор. `--namespace-only` исключает cluster-scoped запросы. Не загруженные счётчики показывают N/A.
Кеши aggregates/sort/Health/Resource Risk/CronJobs привязаны к snapshot; временные состояния
обновляются отдельно. В простое header/footer обновляются раз в секунду, тело — раз в 5 секунд,
при вводе или новом snapshot — сразу.

`--profile-refresh` добавляет parse/build, command timings, stdout bytes, peak RSS, series/points;
в TUI footer — draw time и размер терминала. Peak RSS — максимум процесса за всё время работы.
[Синтетические замеры и ограничения](KTOP_PERFORMANCE_REPORT.md). List/watch и постраничная
обработка List остаются DEFER; превышение byte limit сохраняет последний успешный snapshot.

### Диагностика инцидентов и offline-анализ

Через палитру `F1` доступны четыре read-only экрана:

- `Network Service/EndpointSlice/Pod` связывает Service с EndpointSlice и Pod, показывает пустые endpoints, несовпадение selector, `ready`/`serving`/`terminating`, а также связанные Ingress и NetworkPolicy. Это статический анализ конфигурации; сетевая доступность не проверяется.
- `Degradation evidence` показывает OOMKilled с exit code, состояния init-контейнеров, неуспешные Ready/Initialized conditions, probe failures из Events, признаки ephemeral-storage pressure и измеренную долю CFS throttling periods. У каждого источника показана доступность; отсутствие данных не считается здоровым состоянием.
- `Incident timeline` объединяет Events и замеченные между refresh изменения status, Ready, restarts, generation/revision и rollout. История ограничена 1000 строками; polling может пропустить краткие переходы.
- `Workload securityContext` показывает объявленные `privileged`, host namespaces, hostPath, capabilities, `runAsNonRoot`, seccomp и `automountServiceAccountToken` для Pods и workload templates. Это инвентаризация конфигурации, а не вывод о компрометации.

Network-ресурсы и расширенные workload-данные загружаются по требованию после открытия экрана. Для полного результата нужны права list на `services`, `endpointslices.discovery.k8s.io`, `ingresses.networking.k8s.io` и `networkpolicies.networking.k8s.io`. EndpointSlice readiness выводится вместе с `serving`, `terminating` и `publishNotReadyAddresses`.

JSON dump версии 1 содержит `schema_version`, нормализованный replay snapshot, diagnostics и timeline. Offline-команды не запускают kubectl:

```bash
./ktop-py.py --dump --output json > before.json
./ktop-py.py --dump --output json > after.json
./ktop-py.py --diff before.json after.json --output json
./ktop-py.py --replay before.json after.json
```

В TUI replay клавиши `F5`/`F6` переключают файлы. Diff проверяет cluster/context и порядок времени, связывает объекты по UID и помечает name-only identity. При неполном scope исчезновение считается `no-longer-visible`, а не удалением.

Support bundle создаётся атомарно с правами 0600:

```bash
./ktop-py.py --support-bundle support.json --bundle-namespace production
./ktop-py.py --support-bundle pod.json --bundle-object Pod/production/api --include-raw
./ktop-py.py --replay before.json --support-bundle offline-support.json
```

Без `--include-raw` Kubernetes raw objects не включаются. При включении маскируются env/envFrom, annotations, data/stringData, command/args, credential-подобные ключи и свободный текст событий, статусов и предупреждений; результаты инвентаризации сети и security context сохраняются. Это уменьшает риск утечки, но не гарантирует нахождение секретов в произвольных строках. Bundle содержит возраст snapshot, выбранный scope и состояние источников; для меньшего файла используйте namespace/object selectors.

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

JSON output включает секции `cronjobs`, `diagnostics`, `timeline`, `schema_version` и `snapshot`, пригодный для offline replay. Из-за replay-секции файл больше прежнего формата.

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

## Ограничения, качество данных и namespace-only

Режим без cluster-wide доступа:

```bash
./ktop-py.py --namespace-only -n team-a --context production
./ktop-py.py --namespace-only -n team-a --diagnostics
```

`--namespace-only` требует `-n`, использует Metrics Server по умолчанию и не запрашивает nodes, PV, список namespaces или node-метрики. Допустим также `--metrics-source none`. Недоступные cluster aggregates показываются как `N/A`/`null`. Диагностика проверяет права выбранного источника и namespace. Для direct kubelet/cAdvisor scrape нужен другой профиль: даже `get nodes/proxy` открывает мощные kubelet API, включая выполнение команд в контейнерах; это не исключительно read-only право.

В logs/describe/YAML поиск `/` теперь буквальный. Запрос `re:pattern` явно включает regex в отдельном процессе с общим таймаутом 100 мс на буфер. `lit:re:text` ищет буквальный текст `re:text`. При ошибке или превышении бюджета regex отключается для этого запроса и используется буквальный поиск с сообщением причины.

Значения usage больше не заменяются requests. Отсутствующие метрики — `N/A` в TUI и `null` в JSON; измеренный ноль остаётся нулём. Поля `metric_quality` и CPU/MEM `usage` содержат `state` (`fresh`, `zero`, `missing`, `stale`), `observed_at` и `age_seconds`. Для stale может сохраняться старое значение либо `null` с временем последнего успешного sample. `source_status` описывает состояние secondary-источников; ошибки сохраняются вместе с последним успешным ответом. Истории содержат timestamps и пропуски, агрегируются по времени. Потребителям JSON необходимо учитывать nullable-значения.

Лимиты по умолчанию:

- `--max-output-bytes 33554432`: суммарный stdout/stderr одного kubectl, 32 MiB; превышение завершает запрос ошибкой.
- `--log-limit-bytes 1048576`: до 1 MiB логов вместе с ограничением `--log-tail`.
- `--max-metric-series 20000`: число серий в каждом кеше; counter labels ограничены 4096 символами.
- `--max-history-points 250000`: общий бюджет timestamp/value пар, дополнительно к retention и лимиту samples на серию. Вытеснение серий обозначается предупреждением.

Истории изолированы по context/источнику kubeconfig и UID, очищаются при исчезновении объектов и по TTL. Выбранный context фиксируется при запуске запросов; kubeconfig читается только для необходимых полей без `--raw`. Повреждённая UTF-8 в текстовом ответе отображается безопасно, структурированный JSON проверяется строго.

В просмотре контейнеров поддерживаются app, init, restartable sidecar и ephemeral. Effective requests и limits из Pod spec учитывают стадии init, работающие sidecars, Pod-level resources и overhead. Это заявленные ресурсы; фактическое резервирование scheduler во время in-place resize не вычисляется. Расчёт соответствует [Kubernetes resource helper](https://github.com/kubernetes/component-helpers/blob/master/resource/helpers.go). Ephemeral containers не включаются в проверку отсутствующих requests/limits.

CronJob с неизвестной зоной controller-manager или неподдерживаемой `.spec.timeZone` получает `Unknown`. На Python 3.8 без зависимостей поддерживается UTC; на Python 3.9+ используются доступные IANA-зоны через `zoneinfo`. Для неизвестной зоны расчёт `Missed` не выполняется.

Регрессионные проверки без подключения к кластеру:

```bash
python3 -B -m unittest -v test_ktop_security
python3 -B ktop-py.py --self-test
```

## Автор

**Tarasov Dmitry**
- Email: dtarasov7@gmail.com

## Атрибуция

Части этого кода были сгенерированы с помощью ассистента.
