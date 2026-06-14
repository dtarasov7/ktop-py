# Руководство пользователя ktop-py.py

## Назначение

`ktop-py.py` - это read-only терминальная панель мониторинга Kubernetes. Она рассчитана на ситуации, когда нужно скопировать один файл на сервер и использовать уже настроенный доступ через `kubectl`.

Типичный поток работы похож на `ktop`:

1. Открыть общий экран кластера.
2. Проверить nodes, namespaces и pods.
3. Провалиться в node, namespace, pod, owner или container logs.
4. Открыть read-only `describe` или YAML, если таблиц недостаточно.
5. Использовать health, resource risk, diagnostics и JSON dump для более глубокой диагностики.

`ktop-py.py` не изменяет объекты кластера. В программе нет delete, restart, scale, exec, edit и apply actions.

## Установка

Скопируйте `ktop-py.py` на целевую машину и сделайте файл исполняемым:

```bash
chmod +x ./ktop-py.py
```

Проверьте Python:

```bash
python3 --version
```

Проверьте доступ к Kubernetes:

```bash
kubectl version
kubectl get nodes
```

Для реальных кластеров `ktop-py.py` вызывает `kubectl`; Python Kubernetes client внутрь не встроен.

## Режимы запуска

Запуск с текущим kubeconfig context:

```bash
./ktop-py.py
```

Запуск с конкретным context:

```bash
./ktop-py.py --context staging
```

Запуск с конкретным kubeconfig:

```bash
./ktop-py.py --kubeconfig /path/to/kubeconfig
```

Показать все namespaces, это режим по умолчанию:

```bash
./ktop-py.py
```

Ограничить отображение одним namespace:

```bash
./ktop-py.py --namespace production
```

Запустить на синтетических demo-данных:

```bash
./ktop-py.py --demo
```

Запустить без live metrics:

```bash
./ktop-py.py --metrics-source none
```

Запустить offline self-tests:

```bash
./ktop-py.py --self-test
```

## Overview Screen

На overview-экране есть такие зоны:

- Header
- Cluster Summary
- Верхняя таблица: nodes или namespaces
- Таблица Pods
- Footer с контекстными hotkeys

Header показывает Kubernetes context, версию server, пользователя kubeconfig, namespace scope, metrics status, refresh state и версию `ktop-py.py`.

Cluster Summary показывает возраст кластера, ready nodes, количество namespaces, readiness deployments, readiness pods, volumes, PV/PVC capacity и графики CPU/MEM/Net/Disk, когда есть история.

Верхняя таблица стартует в режиме nodes. Нажмите `g`, чтобы переключить её между:

- Nodes
- Namespaces

Таблица pods следует namespace-фильтру. Если фильтр namespace не установлен, показываются pods из всех namespaces.

## Основы навигации

| Клавиша | Действие |
| ------- | -------- |
| `Tab` / `Shift+Tab` | Переместить фокус между верхней overview-таблицей и pods |
| `Up` / `Down` | Переместить выделенную строку |
| `PageUp` / `PageDown` | Быстрая прокрутка |
| `Home` / `End` | Перейти к первой или последней строке |
| `Left` / `Right` | Горизонтально прокрутить таблицу в фокусе |
| `Enter` | Открыть выбранную строку |
| `j` | Открыть диагностику CronJob |
| `h` / `!` | Открыть Problems / Health |
| `z` | Открыть Resource Risk |
| `x` | Открыть Metrics / RBAC diagnostics |
| `Esc` | Вернуться назад, очистить активный фильтр или подтвердить выход из overview |
| `q` | Выйти |
| `?` | Открыть help |

Hotkeys нормализуются:

- `c` и `C` считаются одинаковыми.
- Принимаются буквы русской раскладки ЙЦУКЕН на тех же физических клавишах.
- Физическая клавиша `/` принимается как `/`, `.` или `,` в зависимости от раскладки.

Функциональные клавиши намеренно не используются, потому что часть терминалов отправляет их как ESC-последовательности.

## Работа с namespaces

`ktop-py.py` запускается в режиме всех namespaces, если не передан `--namespace`.

Нажмите `2`, чтобы открыть namespace picker. Picker всегда показывает все загруженные namespaces, а не только текущий namespace-фильтр. Используйте `/` внутри picker для фильтрации списка, затем нажмите `Enter`, чтобы применить выбранный namespace. Выберите `(all)`, чтобы очистить namespace-фильтр.

Переключатель `g` на overview и namespace filter - разные вещи:

- `g` меняет верхнюю overview-таблицу между nodes и namespaces.
- `2` меняет namespace scope для таблицы pods и detail-экранов.

## Сортировка и фильтры таблиц

Нажмите `/`, когда таблица в фокусе, чтобы редактировать row filter этой таблицы. Нажмите `Enter`, чтобы применить фильтр. Нажмите `Esc` во время ввода, чтобы отменить редактирование.

Hotkeys колонок сортируют таблицу в фокусе. Повторное нажатие той же клавиши меняет направление сортировки.

Клавиши сортировки Nodes:

| Клавиша | Колонка |
| ------- | ------- |
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

Клавиши сортировки Namespaces:

| Клавиша | Колонка |
| ------- | ------- |
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

Клавиши сортировки Pods:

| Клавиша | Колонка |
| ------- | ------- |
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

Клавиши сортировки CronJob:

| Клавиша | Колонка |
| ------- | ------- |
| `n` | NAMESPACE |
| `j` | NAME |
| `s` | STATUS |
| `l` | LAST |
| `x` | NEXT |
| `a` | ACTIVE |
| `o` | OK |
| `f` | FAIL |
| `p` | P95 |

`d` зарезервирована под describe, поэтому сортировка node Disk назначена на `k`.

## Detail Screens

### Node Detail

Откройте node из overview-таблицы Nodes клавишей `Enter`.

Node Detail показывает:

- node status, roles, age, IP, hostname,
- графики CPU, memory, network и disk,
- machine/system поля,
- conditions, labels, annotations, taints, pressures и event count,
- pods, запущенные на node.

Из Node Detail:

- выберите pod и нажмите `Enter`, чтобы открыть Pod Detail,
- нажмите `d` или `y`, чтобы открыть describe/YAML,
- нажмите `Esc`, чтобы вернуться.

### Namespace Detail

Переключите верхнюю overview-таблицу в namespaces клавишей `g`, выберите namespace и нажмите `Enter`.

Namespace Detail показывает status namespace, pod readiness, restarts, failures, CPU/MEM/Net/IO summaries и pods в этом namespace.

### Pod Detail

Откройте pod из overview, node detail или namespace detail.

Pod Detail показывает:

- status, node, namespace, IP, age, restarts,
- графики CPU, memory, network и disk,
- pod info, conditions, resource requests и limits,
- labels и annotations,
- таблицу containers.

Из Pod Detail:

| Клавиша | Действие |
| ------- | -------- |
| `Enter` / `l` | Открыть logs выбранного container |
| `n` | Открыть node, на котором запущен pod |
| `o` | Открыть Workload / Owner view |
| `d` / `y` | Открыть describe/YAML |
| `Esc` | Вернуться назад |

### Workload / Owner View

Нажмите `o` из Pod Detail.

Owner view проходит по ownerReferences, например:

- Pod -> ReplicaSet -> Deployment
- Pod -> StatefulSet
- Pod -> DaemonSet
- Pod -> Job
- Pod -> CronJob через Job ownership, если объект загружен

Экран показывает desired/ready/updated/available, strategy или schedule, selectors, parent owner, controlled pods и related events.

## Диагностика CronJob

Нажмите `j` с любой страницы, чтобы открыть список CronJob diagnostics.

Это read-only operational view, построенный из Kubernetes-объектов, которые уже загружает `ktop-py.py`: `CronJob`, `Job`, связанные `Pod` и `Event`. Программа не устанавливает controller, CRD, webhook, database или alert channel.

Колонки таблицы:

| Колонка | Значение |
| ------- | -------- |
| NAMESPACE / NAME | Идентификатор CronJob |
| SCHEDULE / TZ | `spec.schedule` и `spec.timeZone`; non-UTC time zones в Python 3.8 approximated as local time |
| SUSP | `spec.suspend` |
| LAST | Возраст `status.lastScheduleTime` |
| NEXT | Следующее ожидаемое срабатывание или насколько оно опоздало |
| LATE | Dead-man задержка сверх ожидаемого next schedule |
| ACTIVE | Количество active Jobs из CronJob status |
| OK / FAIL | Количество видимых completed и failed Jobs |
| P50 / P95 / P99 | Percentiles длительности по видимым completed Jobs |
| STATUS | `OK`, `Active`, `Suspended`, `Missed`, `Failed`, `LongRunning`, `Slow` или `Unknown` |
| HINT | Короткая причина или следующая проверка |

Dead-man логика использует `status.lastScheduleTime`, если он есть; иначе берется creation time CronJob. `ktop-py.py` вычисляет следующее расписание после этой reference time. Если ожидаемое next time уже в прошлом больше чем на `startingDeadlineSeconds`, либо больше чем на 300 секунд при отсутствии deadline, CronJob получает статус `Missed`.

SLA duration логика локальна для текущего snapshot. P50/P95/P99 считаются только по Jobs, которые еще существуют в пределах CronJob history limits. Если successful Job history маленькая, percentiles полезны как быстрый hint, но не как долгосрочное SLO-доказательство.

Правила статусов:

| Статус | Условие |
| ------ | ------- |
| `Suspended` | `spec.suspend` равно true |
| `Unknown` | Расписание не удалось разобрать как стандартный five-field cron |
| `Missed` | Ожидаемый запуск опоздал за deadline/grace window |
| `Failed` | Последний видимый Job завершился ошибкой |
| `LongRunning` | Последний active Job намного дольше исторического P95 |
| `Slow` | Последний completed Job намного дольше исторического P95 |
| `Active` | Есть active Jobs и warning condition не найден |
| `OK` | Warning condition не найден |

Нажмите `Enter` на строке CronJob, чтобы открыть detail page. Detail page показывает:

- Info: status, schedule, timezone, suspend state, last/next schedule, last success и hint.
- SLA: active/succeeded/failed counts, late time, P50/P95/P99, latest Job name и status.
- Context: suggestions, recent Jobs и related events.
- Related Pods: pod-ы, принадлежащие видимым Jobs этого CronJob; нажмите `Enter` на pod, чтобы открыть Pod Detail и дальше logs.

CronJob findings также появляются в Problems / Health на панели Workloads / Events. JSON dump содержит top-level массив `cronjobs` с теми же status, timing, percentile, latest Job, severity и suggestion fields.

## Describe и YAML Viewer

Нажмите:

- `d` для `kubectl describe`,
- `y` для `kubectl get ... -o yaml`.

Viewer поддерживает выбранные nodes, namespaces, pods, pods из detail-таблиц, текущий logs context и workload owners.

Клавиши viewer:

| Клавиша | Действие |
| ------- | -------- |
| `d` / `y` | Переключиться между describe и YAML для того же объекта |
| `r` | Перезагрузить объект |
| `w` | Включить или выключить перенос строк |
| `f` | Включить plain copy mode без рамок/header/footer |
| `/` | Начать live regex search и highlight |
| `n` / `p` | Следующее / предыдущее совпадение |
| `g` / `b` | В начало / в конец |
| `Esc` | Назад |

Поиск работает как search-and-highlight, а не как фильтрация строк. Пока вы набираете текст, совпадения подсвечиваются сразу. Если первое совпадение вне текущего viewport, viewer прокручивается к нему. После `Enter` полный describe/YAML остается на экране, а совпадения продолжают подсвечиваться. Невалидный regex переключается на case-insensitive substring search.

## Логи контейнера

Откройте logs из Pod Detail клавишей `Enter` или `l`.

Логи загружаются через `kubectl logs` и обновляются polling-ом, когда включен stream mode. Это не native Kubernetes streaming.

| Клавиша | Действие |
| ------- | -------- |
| `s` | Включить или выключить периодическое обновление |
| `p` | Переключить `kubectl logs --previous`, если нет активного search query |
| `c` / `[` / `]` | Переключить container |
| `t` | Включить или выключить timestamps |
| `w` | Включить или выключить перенос строк |
| `f` | Включить plain copy mode |
| `m` | Загрузить на 100 tail-строк больше |
| `/` | Начать live regex search и highlight |
| `n` / `p` | Следующее / предыдущее совпадение, когда search активен |
| `g` / `b` | В начало / в конец |
| `r` | Перечитать logs |
| `Esc` | Назад |

Если вы вручную прокрутили логи вверх, follow mode блокируется, и refresh не возвращает вас в конец. Нажмите `b` или `End`, чтобы вернуться вниз и продолжить follow.

Plain copy mode убирает рамки, header, footer и control lines, чтобы выделение в терминале содержало только текст логов.

## Problems / Health

Нажмите `h` или `!`.

### Структура экрана

Health page - это панельный operational view. `Tab` / `Shift+Tab` переключает фокус между панелями. `Up` / `Down`, `PageUp` / `PageDown`, `Home` / `End` прокручивают панель в фокусе, а `Left` / `Right` прокручивают широкие строки по горизонтали.

Панели:

| Панель | Содержимое |
| ------ | ---------- |
| Runtime | NotReady, pressured, cordoned или tainted nodes; unhealthy pods; pods с readiness problems или высоким restart count |
| Workloads / Events | workloads, которые не ready, CronJob findings и Kubernetes Warning events |
| Resource Pressure / Collection | resource pressure signals, ResourceQuota usage, LimitRange policies, scheduler-fit findings и collection warnings |

Верхние summary cards показывают количество текущих findings: runtime problems, workload/event problems, resource pressure rows, scheduler-fit rows и collection warnings. Зеленый означает, что проблем нет, желтый - что есть warning-level findings, красный - что есть critical findings или счетчик достаточно велик, чтобы требовать внимания.

Страница read-only и использует уже загруженный snapshot кластера.

### Типы строк Resource Pressure

Панель `Resource Pressure / Collection` объединяет несколько связанных сигналов. Префикс строки показывает, что именно отображается:

| Префикс | Значение |
| ------- | -------- |
| `NODE` | Давление на уровне node. `cap` - allocatable узла, `use` - текущее потребление, `req` - сумма requests запланированных на узел pod-ов, `lim` - сумма limits этих pod-ов. |
| `NS` | Доля namespace от общей allocatable capacity кластера. Это не Kubernetes `ResourceQuota`, а расчетная cluster-share картина по загруженным pod-ам. |
| `QUOTA` | Состояние Kubernetes `ResourceQuota`. Значения берутся из `status.used` и `status.hard`. |
| `LRNG` | Политика Kubernetes `LimitRange`: defaults, min/max и max limit/request ratios. |
| `SCHED` | Результат scheduler-fit: может ли pod попасть на загруженные nodes с учетом поддержанных hard scheduling rules. |
| `WARN` | Collection warning, обычно из-за отсутствующего RBAC или ошибки optional-команды. |

`NODE` и `NS` строки показываются только при достижении warning или critical порога. `QUOTA` и `LRNG` строки остаются информационными даже в здоровом состоянии, потому что объясняют namespace policy. `SCHED` строки показываются для Pending или unscheduled pod-ов, а также для running pod-ов, если их текущий node больше не соответствует hard placement constraints.

### Логика Resource Pressure

Resource pressure намеренно разделяет runtime pressure, scheduler reservations и overcommit limits. Это разные вопросы:

| Вопрос | Поле | Как читать |
| ------ | ---- | ---------- |
| "Кластер или узел загружен прямо сейчас?" | `use` | Текущее live usage из выбранного metrics source. |
| "Сколько ресурсов зарезервировал scheduler?" | `req` | Сумма CPU или memory requests. Requests участвуют в планировании pod-ов. |
| "Сколько контейнерам потенциально разрешено потребить?" | `lim` | Сумма CPU или memory limits. Limits во многих кластерах могут быть больше allocatable capacity. |
| "Относительно чего сравниваем?" | `cap` | Node allocatable для `NODE`; total cluster allocatable для `NS`. |

Если live metrics доступны, `use` означает реальное текущее потребление. Если history еще нет, UI может использовать request values как fallback в summary-like расчетах, чтобы экран не был пустым. Но pressure findings стоит считать наиболее точными, когда live metrics уже доступны.

Пороги:

| Сигнал | Warning | Critical |
| ------ | ------- | -------- |
| Memory usage / allocatable | `>= 75%` | `>= 90%` |
| CPU usage / allocatable | `>= 90%`; `>= 100%` показывается как saturated | сам по себе не critical |
| Memory requests / allocatable | `>= 80%` | `>= 100%` |
| CPU requests / allocatable | `>= 90%` | сам по себе не critical |
| Limits / allocatable | `> 100%` overcommit warning | сам по себе не critical |
| ResourceQuota used / hard | `>= 80%` | `>= 98%` |

Важные следствия:

- `usage > request` сам по себе не является health failure. Request - это reservation для scheduler, а не верхний предел потребления.
- Memory requests на уровне allocatable или выше являются critical, потому что память нельзя безопасно "сжать", и новые pod-ы могут перестать помещаться.
- CPU requests около allocatable - это planning warning. CPU является compressible resource, поэтому предупреждение означает "мало scheduling headroom", а не "узел сломан".
- Limits выше allocatable - это overcommit indicator. Он полезен для capacity review, но сам по себе не critical: обычно не все containers одновременно потребляют свои limits.
- `NS` строки сравнивают namespace с total cluster allocatable. Это показывает pressure по доле кластера, а не enforcement quota.
- `NODE` строки добавляют количество taints как контекст. Capacity на tainted node может быть недоступна большинству pod-ов.

### ResourceQuota и LimitRange

`ktop-py.py` загружает `resourcequotas` и `limitranges` как optional objects. Если RBAC запрещает доступ, Health продолжает работать и добавляет collection warning.

ResourceQuota строки используют Kubernetes `status.used` и `status.hard`. Обычно показываются ресурсы `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, `cpu`, `memory` и `pods`. Severity считается как `used / hard`: `>= 80%` - warning, `>= 98%` - critical. Это строже, чем limit overcommit, потому что ResourceQuota является admission control boundary: при достижении hard value новые подходящие объекты могут быть отклонены.

LimitRange строки описывают namespace defaults и constraints. В них могут быть:

- `defaultReq`: request по умолчанию для containers без явно заданного request,
- `default`: limit по умолчанию для containers без явно заданного limit,
- `min` и `max`: допустимые границы на container,
- `maxRatio`: максимальное отношение limit/request.

Обычная LimitRange строка зеленая, потому что это policy information, а не pressure. LimitRange без limit items показывается как warning: объект существует, но не содержит enforceable limit entries.

### Логика Scheduler-fit

Scheduler-fit отвечает на практический вопрос: "С учетом текущего snapshot, на какие nodes может попасть этот pod?" Это приближение Kubernetes scheduling, а не замена scheduler.

Для каждого non-terminal pod-а `ktop-py.py` проверяет candidate nodes по следующим hard rules:

- node должен быть `Ready`,
- node не должен быть cordoned (`spec.unschedulable`),
- `nodeSelector` должен точно совпадать с labels node,
- required node affinity должна совпадать: `requiredDuringSchedulingIgnoredDuringExecution` с `matchExpressions` и `matchFields`,
- поддержанные affinity operators: `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt` и `Lt`,
- блокирующие taints `NoSchedule` и `NoExecute` должны покрываться tolerations pod-а,
- requested CPU и memory должны помещаться в оставшиеся allocatable resources node.

Для pod-а, который уже работает на node, его собственный request добавляется обратно при проверке этого же node. Это нужно, чтобы текущий node не считался заполненным только из-за того, что этот pod уже занимает scheduled request capacity.

Формат строки Scheduler-fit:

```text
SCHED <namespace/pod> <status> feasible=<matching>/<all> nodes=<first-candidates> req=<cpu>/<mem> blocked=<reason-counts>
```

Severity:

- `critical`: Pending, Unknown или unscheduled pod имеет ноль feasible nodes,
- `warning`: Pending, Unknown или unscheduled pod имеет ровно один feasible node,
- `ok`: Pending, Unknown или unscheduled pod имеет два или больше feasible nodes,
- `warning`: running pod находится на node, который нарушает hard placement rules: selector, affinity, taints, Ready state или cordon state.

`blocked=` агрегирует причины, по которым nodes были отклонены. Частые ключи: `not-ready`, `cordoned`, `selector`, `affinity`, `taints`, `cpu` и `memory`.

Текущие ограничения: scheduler-fit не учитывает pod affinity/anti-affinity, preferred node affinity, topology spread constraints, storage topology, PVC zone binding, host ports, extended resources, image locality, PodDisruptionBudgets, priority/preemption, admission webhooks, custom scheduler plugins и поведение scheduler extenders. Используйте его как operator-facing diagnostic для самых частых hard placement blockers.

## Resource Risk

Нажмите `z`.

Resource Risk фокусируется на ресурсной конфигурации и pressure. Он показывает:

- containers без CPU или memory requests, с отдельными счетчиками `cpu:` и `mem:`,
- containers без CPU или memory limits, с отдельными счетчиками `cpu:` и `mem:`,
- высокие usage/request ratios,
- высокие usage/limit ratios,
- top CPU и memory consumers по namespace,
- top CPU и memory consumers по workload owner.

### Missing requests и limits

Missing requests и limits считаются по containers и отдельно по каждому resource. Container без CPU request и без memory request увеличивает оба счетчика: `cpu:` и `mem:`. Для limits применяется та же логика. В таблице колонка `MISSING` показывает `cpu`, `mem` или `cpu,mem`, а колонка `OWNER` показывает workload owner chain, если его удалось определить.

Missing limits показываются как policy risk signals. Некоторые команды намеренно не используют limits, поэтому оценивайте этот раздел согласно политике вашего кластера.

### Логика usage ratios

Usage ratios оцениваются только если доступны live metrics. Если live metrics недоступны, `High Usage Ratios` показывает сообщение, а не выдает request fallback за текущее потребление.

Пороги ratios:

| Ratio | Порог | Значение |
| ----- | ----- | -------- |
| `usage / request` | `>= 80%` | Container приближается к тому объему, который попросил зарезервировать у scheduler, или уже превысил его. Это right-sizing signal, а не автоматический health failure. |
| `usage / limit` | `>= 90%` | Container близок к configured limit; в зависимости от resource возможны throttling или kill. |

Строки с ratio `>= 100%` подсвечиваются сильнее. Для CPU `usage > request` может быть совершенно нормальным; для memory это тоже встречается, но полезно для right-sizing и capacity planning. Health оценивает cluster-level pressure отдельно от этих container-level sizing signals.

### Top consumers

Top consumer панели ранжируют namespaces и workload owners по CPU и memory. Если live metrics доступны, используется live usage. Если live metrics недоступны, используется fallback на requests, чтобы страница всё равно показывала capacity planning view. Такой fallback означает "зарезервировано конфигурацией", а не "потребляется прямо сейчас".

Resource Risk тоже является панельным экраном. `Tab` / `Shift+Tab` переключает `Missing Requests / Limits`, `High Usage Ratios` и `Top Consumers`. Вертикальная прокрутка работает для длинных списков, горизонтальная - для широких owner или pod/container имен.

## Metrics / RBAC Diagnostics

Нажмите `x` в TUI или выполните:

```bash
./ktop-py.py --diagnostics
```

Diagnostics проверяет:

- `auth can-i` для `nodes.metrics.k8s.io`,
- `auth can-i` для `pods.metrics.k8s.io`,
- `auth can-i get nodes/proxy`,
- raw Metrics API endpoints,
- kubelet `/metrics`,
- cAdvisor `/metrics/cadvisor`.

Цель - быстро объяснить, почему Prometheus mode или Metrics Server mode не отдают данные.

## Загружаемые Kubernetes-объекты и RBAC

Каждый refresh загружает read-only snapshot через `kubectl`. Для максимально полного отображения kubeconfig user должен уметь list:

- `nodes`, `pods`, `namespaces`, `events`,
- `deployments`, `replicasets`, `statefulsets`, `daemonsets`, `jobs`, `cronjobs`,
- `persistentvolumes`, `persistentvolumeclaims`,
- `resourcequotas`, `limitranges`.

Если доступ к optional objects запрещен, `ktop-py.py` продолжает работать и записывает collection warning. Соответствующие панели могут быть неполными. Например, без доступа к `resourcequotas` Health не сможет показать реальные namespace quota `used/hard`; без доступа к `limitranges` он не покажет namespace default request/limit policies; без доступа к `jobs` или `cronjobs` CronJob diagnostics не сможет связать расписания с видимыми runs и pods.

Prometheus mode дополнительно требует `get nodes/proxy` для kubelet и cAdvisor endpoints. Metrics Server mode требует read access к `nodes.metrics.k8s.io` и `pods.metrics.k8s.io`.

## Источники метрик

### Prometheus Mode

```bash
./ktop-py.py --metrics-source prometheus
```

Prometheus mode напрямую читает Prometheus-format endpoints, которые уже отдают Kubernetes-компоненты через API server node proxy:

- `/api/v1/nodes/<node>/proxy/metrics`
- `/api/v1/nodes/<node>/proxy/metrics/cadvisor`

Внешний Prometheus-сервер не нужен.

Prometheus mode может дать:

- CPU/MEM nodes,
- CPU/MEM pods,
- CPU/MEM containers,
- network receive/transmit rates,
- filesystem read/write rates,
- retained history для charts и trends.

Rate metrics требуют минимум два samples. При первом запуске `ktop-py.py` может показывать `prometheus (warming)`.

Полезные параметры:

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

Metrics Server mode читает:

- `/apis/metrics.k8s.io/v1beta1/nodes`
- `/apis/metrics.k8s.io/v1beta1/pods`

Он предоставляет CPU/MEM для nodes, pods и containers. Metrics Server не предоставляет network или disk I/O, поэтому эти панели в этом режиме недоступны или нулевые.

### No Metrics Mode

```bash
./ktop-py.py --metrics-source none
```

No metrics mode отключает live usage collection. Таблицы и summary используют fallback по requests и allocatable, где это возможно.

## Графики и retention

Prometheus mode хранит samples в памяти внутри текущего процесса. Retention относится только к запущенному процессу `ktop-py.py`:

- без записи на диск,
- без PromQL engine,
- без внешней time-series database.

Charts и sparklines по умолчанию используют Unicode block glyphs:

```bash
./ktop-py.py --graph-style unicode
```

ASCII fallback нужен только если terminal font не показывает block glyphs:

```bash
./ktop-py.py --graph-style ascii
KTOP_PY_GRAPH_STYLE=ascii ./ktop-py.py
```

## JSON Dump

Dump mode печатает один snapshot и завершает процесс:

```bash
./ktop-py.py --dump
./ktop-py.py --dump --output json
```

JSON включает cluster metadata, nodes, pods, containers, CronJob diagnostics, metrics status, warnings и loaded timestamp.

Опции выбора pods:

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

Max values по умолчанию считаются по окну ширины графика. Чтобы собрать короткий интервал перед dump:

```bash
./ktop-py.py --dump --output json --dump-max-interval 30s --refresh-interval 5
```

Добавляйте raw Kubernetes objects только когда они нужны:

```bash
./ktop-py.py --dump --output json --include-raw
```

## Выбор колонок

Показать только конкретные node columns:

```bash
./ktop-py.py --node-columns 'NAME,STATUS,CPU,MEM,DISK R,DISK W,NET TX,NET RX'
```

Показать только конкретные pod columns:

```bash
./ktop-py.py --pod-columns NAMESPACE,POD,STATUS,CPU,MEMORY
```

Неизвестные имена колонок игнорируются.

## Архитектурные диаграммы

PlantUML-диаграммы архитектуры лежат в `diagramms/`. У каждой английской диаграммы есть русская копия с суффиксом `-ru`.

## Troubleshooting

### kubectl не найден

Установите `kubectl` или передайте путь явно:

```bash
./ktop-py.py --kubectl /path/to/kubectl
```

### Prometheus mode не показывает данные

Проверьте RBAC на node proxy и доступ к cAdvisor:

```bash
kubectl auth can-i get nodes/proxy
kubectl get nodes
kubectl get --raw /api/v1/nodes/<node-name>/proxy/metrics
kubectl get --raw /api/v1/nodes/<node-name>/proxy/metrics/cadvisor
```

Запустите встроенную диагностику:

```bash
./ktop-py.py --diagnostics
```

### Metrics Server mode не показывает данные

Проверьте доступ к Metrics API:

```bash
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods
```

Если Metrics Server не установлен, используйте Prometheus mode или no metrics mode.

### Рамки или графики отображаются неправильно

Используйте UTF-8 locale и шрифт с box-drawing и block glyphs. Если ломаются только символы графиков, используйте:

```bash
./ktop-py.py --graph-style ascii
```

### TUI кажется зависшим во время refresh

Snapshot refresh выполняется в background worker. UI продолжает рисовать последний успешный snapshot. Header показывает loading, stale или error state.

Если kubectl commands медленные, сузьте scope через `--namespace`, проверьте latency API server или увеличьте command timeout:

```bash
./ktop-py.py --command-timeout 30
```

## Команды проверки

Используйте эти проверки после изменения скрипта:

```bash
python3 -m py_compile ktop-py.py
python3 -m tabnanny ktop-py.py
./ktop-py.py --self-test
./ktop-py.py --demo --dump
./ktop-py.py --demo --dump --output json
./ktop-py.py --help
```
