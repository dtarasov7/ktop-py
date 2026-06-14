#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ktop-py.py: a single-file, low-dependency Kubernetes TUI inspired by ktop.

ktop-py.py: однфайловый Kubernetes TUI с минимальными зависимостями,
ориентированный на запуск в ограниченных окружениях.

Runtime dependencies:
  - Python 3.8+
  - stdlib curses
  - kubectl in PATH for real clusters

The program is intentionally contained in this one file so it can be copied
into restricted environments where the original ktop binary is unavailable.
"""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import json
import locale
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import textwrap
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


VERSION = "1.1.0"
__VERSION__ = "1.1.0"
__AUTHOR__ = "Tarasov Dmitry"

MIN_ROWS = 22
DEFAULT_REFRESH_SECONDS = 5.0
DEFAULT_PROMETHEUS_SCRAPE_SECONDS = 5.0
DEFAULT_PROMETHEUS_RETENTION_SECONDS = 3600.0
DEFAULT_PROMETHEUS_MAX_SAMPLES = 10000
RATE_CHART_MIN_BYTES_PER_SECOND = 512.0 * 1024.0
METRIC_PANEL_INNER_HEIGHT = 5
METRIC_PANEL_HEIGHT = METRIC_PANEL_INNER_HEIGHT + 2
DEFAULT_DUMP_GRAPH_WIDTH = 10
MAX_SEARCH_REGEX_LENGTH = 128
DEFAULT_GRAPH_STYLE = os.environ.get("KTOP_PY_GRAPH_STYLE", "unicode").lower()
if DEFAULT_GRAPH_STYLE not in ("ascii", "unicode"):
    DEFAULT_GRAPH_STYLE = "unicode"

RATE_DETAIL_COLUMNS = ["DISK R", "DISK W", "NET TX", "NET RX"]
NODE_DEFAULT_COLUMNS = ["NAME", "STATUS", "RST", "PODS", "TAINTS", "PRESSURE", "IP", "VOLS", "DISK", "CPU", "MEM"] + RATE_DETAIL_COLUMNS
NODE_COLUMNS = NODE_DEFAULT_COLUMNS + ["NET", "IO"]
NAMESPACE_COLUMNS = ["NAMESPACE", "STATUS", "PODS", "READY", "RST", "FAIL", "CPU", "MEMORY"] + RATE_DETAIL_COLUMNS
POD_COLUMNS = ["NAMESPACE", "POD", "READY", "STATUS", "RST", "AGE", "VOLS", "IP", "NODE", "CPU", "MEMORY"]
CRONJOB_COLUMNS = ["NAMESPACE", "NAME", "SCHEDULE", "TZ", "SUSP", "LAST", "NEXT", "LATE", "ACTIVE", "OK", "FAIL", "P50", "P95", "P99", "STATUS", "HINT"]
RESOURCE_PANEL_KEYS = ["resource_missing", "resource_ratios", "resource_top"]
HEALTH_PANEL_KEYS = ["health_runtime", "health_workloads", "health_resources"]

NODE_SORT_KEYS = {
    "n": "NAME",
    "a": "STATUS",
    "r": "RST",
    "i": "IP",
    "p": "PODS",
    "t": "TAINTS",
    "s": "PRESSURE",
    "v": "VOLS",
    "k": "DISK",
    "c": "CPU",
    "m": "MEM",
    "e": "NET RX",
    "o": "DISK R",
    "w": "DISK W",
}

POD_SORT_KEYS = {
    "n": "NAMESPACE",
    "p": "POD",
    "r": "READY",
    "s": "STATUS",
    "t": "RST",
    "a": "AGE",
    "v": "VOLS",
    "i": "IP",
    "o": "NODE",
    "c": "CPU",
    "m": "MEMORY",
}

NAMESPACE_SORT_KEYS = {
    "n": "NAMESPACE",
    "s": "STATUS",
    "p": "PODS",
    "a": "READY",
    "r": "RST",
    "f": "FAIL",
    "c": "CPU",
    "m": "MEMORY",
    "e": "NET RX",
    "o": "DISK R",
    "w": "DISK W",
}

CRONJOB_SORT_KEYS = {
    "n": "NAMESPACE",
    "j": "NAME",
    "s": "STATUS",
    "l": "LAST",
    "x": "NEXT",
    "a": "ACTIVE",
    "o": "OK",
    "f": "FAIL",
    "p": "P95",
}

# Keyboard input is normalized before command handling.
# Ввод клавиш нормализуется до обработки команд.
RUSSIAN_QWERTY_KEYS = {
    "й": "q",
    "ц": "w",
    "у": "e",
    "к": "r",
    "е": "t",
    "н": "y",
    "г": "u",
    "ш": "i",
    "щ": "o",
    "з": "p",
    "х": "[",
    "ъ": "]",
    "ф": "a",
    "ы": "s",
    "в": "d",
    "а": "f",
    "п": "g",
    "р": "h",
    "о": "j",
    "л": "k",
    "д": "l",
    "ж": ";",
    "э": "'",
    "я": "z",
    "ч": "x",
    "с": "c",
    "м": "v",
    "и": "b",
    "т": "n",
    "ь": "m",
    "б": ",",
    "ю": ".",
}

RUSSIAN_PUNCTUATION_KEYS = {
    ".": "/",
    ",": "/",
}


def key_char(key: Any) -> str:
    """Return a printable character for a curses key. / Возвращает символ для curses-клавиши.

    Args:
        key: curses key value, either int or str.
    Returns:
        A single-character string, or empty string for non-character keys.
    """
    if isinstance(key, str):
        return key
    if isinstance(key, int) and 0 <= key <= 255:
        return chr(key)
    return ""


def hotkey(key: Any) -> str:
    """Normalize hotkeys across case and Russian layout. / Нормализует hotkey для регистра и русской раскладки.

    Args:
        key: Raw curses key value.
    Returns:
        Lowercase command key used by the TUI, or empty string.
    """
    char = key_char(key)
    if not char:
        return ""
    lower = char.lower()
    mapped = RUSSIAN_QWERTY_KEYS.get(lower, lower)
    return RUSSIAN_PUNCTUATION_KEYS.get(mapped, mapped)


def is_upper_key(key: Any) -> bool:
    char = key_char(key)
    return bool(char and char.upper() == char and char.lower() != char)


def is_ctrl_c(key: Any) -> bool:
    return key == 3 or key_char(key) == "\x03"


def is_escape_key(key: Any) -> bool:
    return key == 27 or key_char(key) == "\x1b"


def is_enter_key(key: Any) -> bool:
    return key in (10, 13, curses.KEY_ENTER) or key_char(key) in ("\n", "\r")


def is_backspace_key(key: Any) -> bool:
    return key in (curses.KEY_BACKSPACE, 127, 8) or key_char(key) in ("\x7f", "\b")


def is_tab_key(key: Any) -> bool:
    return key == 9 or key_char(key) == "\t"


class DataError(Exception):
    """User-facing data collection error. / Ошибка сбора данных, показываемая пользователю."""
    pass


@dataclass
class EventInfo:
    """Normalized Kubernetes event. / Нормализованное событие Kubernetes."""

    namespace: str
    kind: str
    name: str
    reason: str
    event_type: str
    message: str
    timestamp: Optional[dt.datetime]


@dataclass
class ContainerInfo:
    """Container row with resources and history. / Строка контейнера с ресурсами и историей."""

    name: str
    image: str
    ready: bool
    restarts: int
    status: str
    usage_cpu_m: float
    usage_mem_b: float
    cpu_request_m: float
    mem_request_b: float
    cpu_limit_m: float
    mem_limit_b: float
    ports: str
    mounts: int
    cpu_history: List[float] = field(default_factory=list)
    mem_history: List[float] = field(default_factory=list)


@dataclass
class NodeRow:
    """Node row used by tables, detail pages, and dumps. / Строка узла для таблиц, деталей и dump."""

    name: str
    roles: List[str]
    controller: bool
    hostname: str
    status: str
    pressures: List[str]
    creation_time: Optional[dt.datetime]
    internal_ip: str
    external_ip: str
    pods_count: int
    images_count: int
    volumes_in_use: int
    volumes_attached: int
    taints: int
    unschedulable: bool
    restarts: int
    kubelet: str
    os_image: str
    kernel: str
    runtime: str
    arch: str
    alloc_cpu_m: float
    alloc_mem_b: float
    alloc_storage_b: float
    requested_cpu_m: float
    requested_mem_b: float
    usage_cpu_m: float
    usage_mem_b: float
    net_rx_bps: float
    net_tx_bps: float
    fs_read_bps: float
    fs_write_bps: float
    cpu_history: List[float] = field(default_factory=list)
    mem_history: List[float] = field(default_factory=list)
    net_history: List[float] = field(default_factory=list)
    net_rx_history: List[float] = field(default_factory=list)
    net_tx_history: List[float] = field(default_factory=list)
    io_history: List[float] = field(default_factory=list)
    fs_read_history: List[float] = field(default_factory=list)
    fs_write_history: List[float] = field(default_factory=list)
    conditions: List[Tuple[str, str, str]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PodRow:
    """Pod row with ownership, resources, and metrics. / Строка pod с владельцами, ресурсами и метриками."""

    namespace: str
    name: str
    status: str
    node: str
    ip: str
    creation_time: Optional[dt.datetime]
    requested_cpu_m: float
    requested_mem_b: float
    usage_cpu_m: float
    usage_mem_b: float
    net_rx_bps: float
    net_tx_bps: float
    fs_read_bps: float
    fs_write_bps: float
    node_alloc_cpu_m: float
    node_alloc_mem_b: float
    ready: int
    total: int
    restarts: int
    volumes: int
    mounts: int
    containers: List[ContainerInfo]
    cpu_history: List[float] = field(default_factory=list)
    mem_history: List[float] = field(default_factory=list)
    net_history: List[float] = field(default_factory=list)
    net_rx_history: List[float] = field(default_factory=list)
    net_tx_history: List[float] = field(default_factory=list)
    io_history: List[float] = field(default_factory=list)
    fs_read_history: List[float] = field(default_factory=list)
    fs_write_history: List[float] = field(default_factory=list)
    conditions: List[Tuple[str, str, str]] = field(default_factory=list)
    owners: List[Tuple[str, str]] = field(default_factory=list)
    owner_chain: List[Tuple[str, str]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NamespaceRow:
    """Namespace aggregate row for overview and detail. / Агрегированная строка namespace для overview и detail."""

    name: str
    status: str
    pods_count: int
    running_pods: int
    ready: int
    total: int
    restarts: int
    failures: int
    requested_cpu_m: float
    requested_mem_b: float
    usage_cpu_m: float
    usage_mem_b: float
    net_rx_bps: float
    net_tx_bps: float
    fs_read_bps: float
    fs_write_bps: float
    cpu_total_m: float
    mem_total_b: float
    cpu_history: List[float] = field(default_factory=list)
    mem_history: List[float] = field(default_factory=list)
    net_history: List[float] = field(default_factory=list)
    net_rx_history: List[float] = field(default_factory=list)
    net_tx_history: List[float] = field(default_factory=list)
    io_history: List[float] = field(default_factory=list)
    fs_read_history: List[float] = field(default_factory=list)
    fs_write_history: List[float] = field(default_factory=list)


@dataclass
class WorkloadRow:
    """Workload owner row for drill-down views. / Строка workload-владельца для detail-переходов."""

    kind: str
    namespace: str
    name: str
    desired: int
    ready: int
    updated: int
    available: int
    status: str
    strategy: str
    selector: str
    owner_kind: str
    owner_name: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CronJobRunRow:
    """One Job execution owned by a CronJob. / Один запуск Job, принадлежащий CronJob."""

    namespace: str
    name: str
    cronjob: str
    status: str
    start_time: Optional[dt.datetime]
    completion_time: Optional[dt.datetime]
    duration_s: Optional[float]
    active: int
    succeeded: int
    failed: int
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CronScheduleSpec:
    """Parsed five-field Cron schedule. / Разобранное cron-расписание из пяти полей."""

    minutes: Set[int]
    hours: Set[int]
    days: Set[int]
    months: Set[int]
    weekdays: Set[int]
    day_any: bool
    weekday_any: bool


@dataclass
class CronJobRow:
    """CronJob SLA/dead-man diagnostics row. / Строка диагностики CronJob SLA/dead-man."""

    namespace: str
    name: str
    schedule: str
    timezone: str
    suspend: bool
    last_schedule: Optional[dt.datetime]
    last_success: Optional[dt.datetime]
    next_schedule: Optional[dt.datetime]
    late_seconds: float
    active: int
    succeeded: int
    failed: int
    p50_s: Optional[float]
    p95_s: Optional[float]
    p99_s: Optional[float]
    latest_job: str
    latest_status: str
    status: str
    severity: str
    hint: str
    suggestions: List[str] = field(default_factory=list)
    parse_error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticResult:
    """Single diagnostics check result. / Результат одной диагностической проверки."""

    name: str
    status: str
    detail: str
    hint: str = ""


@dataclass
class HealthData:
    """Problems / Health report model. / Модель отчета Problems / Health."""

    loaded_at: str
    metrics_status: str
    node_findings: List[Tuple[str, str]]
    pod_findings: List[Tuple[str, str]]
    workload_findings: List[Tuple[str, str]]
    cronjob_findings: List[Tuple[str, str]]
    event_findings: List[Tuple[str, str]]
    collection_warnings: List[Tuple[str, str]]
    resource_findings: List[Tuple[str, str]]
    scheduling_findings: List[Tuple[str, str]]


@dataclass
class ResourceRiskData:
    """Resource risk report model. / Модель отчета о ресурсных рисках."""

    loaded_at: str
    metrics_status: str
    metrics_available: bool
    pod_count: int
    container_count: int
    missing_requests: List[Tuple[PodRow, ContainerInfo, str, str]]
    missing_limits: List[Tuple[PodRow, ContainerInfo, str, str]]
    ratio_findings: List[Tuple[float, str, str, PodRow, ContainerInfo, str, str]]
    namespace_totals: List[Tuple[str, float, float]]
    workload_totals: List[Tuple[str, float, float]]


@dataclass
class ObjectTarget:
    """Kubernetes object selected for describe/YAML viewer. / Kubernetes object для describe/YAML viewer."""

    kind: str
    namespace: str
    name: str
    label: str
    container: str = ""


@dataclass
class ClusterSnapshot:
    """Immutable-ish snapshot rendered by UI and dump. / Снимок кластера для UI и dump."""

    context: str
    user: str
    k8s_version: str
    namespace: str
    metrics_status: str
    metrics_available: bool
    nodes: List[NodeRow]
    pods: List[PodRow]
    events: List[EventInfo]
    workloads: Dict[Tuple[str, str, str], WorkloadRow]
    namespaces_count: int
    deployments_ready: int
    deployments_total: int
    pv_count: int
    pv_capacity_b: float
    pvc_count: int
    pvc_capacity_b: float
    volumes_in_use: int
    uptime_start: Optional[dt.datetime]
    cluster_cpu_history: List[float] = field(default_factory=list)
    cluster_mem_history: List[float] = field(default_factory=list)
    cluster_net_history: List[float] = field(default_factory=list)
    cluster_net_rx_history: List[float] = field(default_factory=list)
    cluster_net_tx_history: List[float] = field(default_factory=list)
    cluster_io_history: List[float] = field(default_factory=list)
    cluster_fs_read_history: List[float] = field(default_factory=list)
    cluster_fs_write_history: List[float] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    loaded_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    namespaces: List[str] = field(default_factory=list)
    namespace_statuses: Dict[str, str] = field(default_factory=dict)
    resource_quotas: List[Dict[str, Any]] = field(default_factory=list)
    limit_ranges: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ResourceUsage:
    """CPU, memory, network, and IO usage values. / Значения CPU, памяти, сети и IO."""

    cpu_m: float = 0.0
    mem_b: float = 0.0
    net_rx_bps: float = 0.0
    net_tx_bps: float = 0.0
    fs_read_bps: float = 0.0
    fs_write_bps: float = 0.0


_QUANTITY_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)([a-zA-Z]*)\s*$")
_DURATION_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)(ms|s|m|h)?\s*$")
_REGEX_REPEAT_ATOM = r"(?:[+*]|\{\d+(?:,\d*)?\})"
_REGEX_NESTED_REPEAT_RE = re.compile(r"\((?:[^()\\]|\\.)*%s(?:[^()\\]|\\.)*\)\s*%s" % (_REGEX_REPEAT_ATOM, _REGEX_REPEAT_ATOM))
_REGEX_REPEATED_ALT_RE = re.compile(r"\((?:[^()\\]|\\.)+\|(?:[^()\\]|\\.)+\)\s*%s" % _REGEX_REPEAT_ATOM)


def parse_duration_seconds(value: Any) -> float:
    """Parse a CLI duration into seconds. / Разбирает CLI-интервал в секунды.

    Args:
        value: Number or string like ``1500ms``, ``15s``, ``5m``, or ``1h``.
    Returns:
        Non-negative duration in seconds.
    Raises:
        argparse.ArgumentTypeError: If the value is not a supported duration.
    """
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value or "").strip()
    match = _DURATION_RE.match(text)
    if not match:
        raise argparse.ArgumentTypeError("expected duration like 15s, 5m, 1h, or seconds")
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return max(0.0, amount * factors[unit])


def parse_nonnegative_int(value: Any) -> int:
    """Parse a non-negative integer CLI value. / Разбирает неотрицательное CLI-число.

    Args:
        value: String or number supplied by argparse.
    Returns:
        Integer greater than or equal to zero.
    Raises:
        argparse.ArgumentTypeError: If parsing fails or value is negative.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("expected a non-negative integer")
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a non-negative integer")
    return parsed


def parse_positive_int(value: Any) -> int:
    """Parse a positive integer CLI value. / Разбирает положительное CLI-число.

    Args:
        value: String or number supplied by argparse.
    Returns:
        Integer greater than zero.
    Raises:
        argparse.ArgumentTypeError: If parsing fails or value is not positive.
    """
    parsed = parse_nonnegative_int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def parse_cpu_millis(value: Any) -> float:
    """Parse Kubernetes CPU quantity into millicores. / Переводит CPU quantity Kubernetes в millicores.

    Args:
        value: Kubernetes CPU quantity such as ``250m``, ``500u``, or ``2``.
    Returns:
        CPU value in millicores, or 0.0 for unsupported input.
    """
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    match = _QUANTITY_RE.match(text)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "n":
        return number / 1000000.0
    if unit == "u":
        return number / 1000.0
    if unit == "m":
        return number
    if unit == "":
        return number * 1000.0
    if unit == "k":
        return number * 1000.0 * 1000.0
    if unit == "M":
        return number * 1000.0 * 1000.0 * 1000.0
    if unit == "G":
        return number * 1000.0 * 1000.0 * 1000.0 * 1000.0
    return 0.0


_BINARY_UNITS = {
    "Ki": 1024.0,
    "Mi": 1024.0 ** 2,
    "Gi": 1024.0 ** 3,
    "Ti": 1024.0 ** 4,
    "Pi": 1024.0 ** 5,
    "Ei": 1024.0 ** 6,
}

_DECIMAL_UNITS = {
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "": 1.0,
    "k": 1000.0,
    "K": 1000.0,
    "M": 1000.0 ** 2,
    "G": 1000.0 ** 3,
    "T": 1000.0 ** 4,
    "P": 1000.0 ** 5,
    "E": 1000.0 ** 6,
}


def parse_bytes(value: Any) -> float:
    """Parse Kubernetes byte quantity. / Переводит Kubernetes quantity памяти/размера в байты.

    Args:
        value: Quantity such as ``128Mi``, ``1Gi``, or decimal SI value.
    Returns:
        Size in bytes, or 0.0 for unsupported input.
    """
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    match = _QUANTITY_RE.match(text)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    if unit in _BINARY_UNITS:
        return number * _BINARY_UNITS[unit]
    if unit in _DECIMAL_UNITS:
        return number * _DECIMAL_UNITS[unit]
    return 0.0


def format_mcpu(value: float) -> str:
    """Format millicores for compact display. / Форматирует millicores для компактного вывода.

    Args:
        value: CPU value in millicores.
    Returns:
        Human-readable CPU string, e.g. ``250m`` or ``2c``.
    """
    value = max(0.0, float(value or 0.0))
    if value >= 1000.0:
        cores = value / 1000.0
        if abs(cores - round(cores)) < 0.05:
            return "%dc" % int(round(cores))
        return "%.1fc" % cores
    return "%dm" % int(round(value))


def format_bytes(value: float) -> str:
    """Format bytes with binary units. / Форматирует байты в binary units.

    Args:
        value: Byte count.
    Returns:
        Human-readable value like ``64Mi`` or ``1.5Gi``.
    """
    value = max(0.0, float(value or 0.0))
    units = [("Ti", 1024.0 ** 4), ("Gi", 1024.0 ** 3), ("Mi", 1024.0 ** 2), ("Ki", 1024.0)]
    for suffix, factor in units:
        if value >= factor:
            amount = value / factor
            if amount >= 10 or abs(amount - round(amount)) < 0.05:
                return "%d%s" % (int(round(amount)), suffix)
            return "%.1f%s" % (amount, suffix)
    return "%dB" % int(round(value))


def ratio(value: float, total: float) -> float:
    """Clamp value/total to a display ratio. / Ограничивает value/total для отображения.

    Args:
        value: Current amount.
        total: Capacity or limit.
    Returns:
        Ratio in the inclusive range 0.0..1.0.
    """
    if not total or total <= 0:
        return 0.0
    return max(0.0, min(1.0, float(value or 0.0) / float(total)))


def parse_rfc3339(value: Any) -> Optional[dt.datetime]:
    """Parse a Kubernetes RFC3339 timestamp. / Разбирает RFC3339 timestamp из Kubernetes.

    Args:
        value: Timestamp string, usually ending with ``Z``.
    Returns:
        Timezone-aware datetime, or None when parsing fails.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def isoformat_utc(value: Optional[dt.datetime]) -> Optional[str]:
    """Format datetime as UTC ISO string. / Форматирует datetime как UTC ISO-строку.

    Args:
        value: Optional datetime.
    Returns:
        ``YYYY-MM-DDTHH:MM:SSZ`` style string, or None.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def human_age(start: Optional[dt.datetime], now: Optional[dt.datetime] = None) -> str:
    """Return compact age text. / Возвращает компактный возраст объекта.

    Args:
        start: Start timestamp.
        now: Optional reference time.
    Returns:
        Text such as ``3d2h``, ``15m``, or ``-``.
    """
    if start is None:
        return "-"
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    delta = now - start
    seconds = max(0, int(delta.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return "%dd" % days if hours == 0 else "%dd%dh" % (days, hours)
    if hours:
        return "%dh" % hours if minutes == 0 else "%dh%dm" % (hours, minutes)
    if minutes:
        return "%dm" % minutes
    return "%ds" % seconds


def sanitize_terminal_text(text: Any) -> str:
    """Escape control characters before terminal rendering. / Экранирует control chars для TUI.

    Args:
        text: Value to render.
    Returns:
        Printable text where terminal control bytes are visible and inert.
    """
    result: List[str] = []
    for char in str(text):
        code = ord(char)
        if char == "\n":
            result.append(" ")
        elif char == "\t":
            result.append(" ")
        elif char == "\r":
            result.append("^M")
        elif code == 0x1B:
            result.append("^[")
        elif code < 32:
            result.append("^" + chr(code + 64))
        elif code == 127:
            result.append("^?")
        elif 0x80 <= code <= 0x9F:
            result.append("\\x%02X" % code)
        else:
            result.append(char)
    return "".join(result)


def truncate(text: Any, width: int) -> str:
    """Trim text to a terminal cell width. / Обрезает текст под ширину терминала.

    Args:
        text: Value to render.
        width: Maximum character count.
    Returns:
        Sanitized and possibly ``~``-truncated string.
    """
    if width <= 0:
        return ""
    value = sanitize_terminal_text(text)
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "~"


def normalize_columns(raw: str, allowed: Sequence[str], default: Optional[Sequence[str]] = None) -> List[str]:
    """Normalize a comma-separated column list. / Нормализует список колонок из CLI.

    Args:
        raw: Comma-separated user input.
        allowed: Supported column names.
        default: Default column names when input is empty or invalid.
    Returns:
        Valid uppercase column names.
    """
    if not raw:
        return list(default or allowed)
    requested = [part.strip().upper() for part in raw.split(",") if part.strip()]
    allowed_set = set(allowed)
    result = [col for col in requested if col in allowed_set]
    return result or list(default or allowed)


def safe_get(obj: Dict[str, Any], path: Sequence[Any], default: Any = None) -> Any:
    """Safely read a nested dict/list path. / Безопасно читает вложенный путь dict/list.

    Args:
        obj: Root object.
        path: Sequence of mapping keys or list indexes.
        default: Fallback value.
    Returns:
        Found value or default when any path segment is missing.
    """
    cur: Any = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


def list_items(obj: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return Kubernetes list items. / Возвращает ``items`` из Kubernetes list object.

    Args:
        obj: Kubernetes JSON list object or None.
    Returns:
        Item list; empty when object is missing or malformed.
    """
    if not isinstance(obj, dict):
        return []
    items = obj.get("items", [])
    return items if isinstance(items, list) else []


def container_resource(container: Dict[str, Any], bucket: str, resource: str) -> Any:
    return safe_get(container, ["resources", bucket, resource])


def container_ports(container: Dict[str, Any]) -> str:
    """Format exposed container ports. / Форматирует порты контейнера.

    Args:
        container: Raw Kubernetes container object.
    Returns:
        Comma-separated ``port/protocol`` list, or ``-``.
    """
    ports = []
    for port in container.get("ports", []) or []:
        container_port = port.get("containerPort")
        protocol = port.get("protocol", "TCP")
        if container_port:
            ports.append("%s/%s" % (container_port, protocol))
    return ",".join(ports) if ports else "-"


def node_roles(node: Dict[str, Any]) -> List[str]:
    """Extract Kubernetes node roles. / Извлекает роли Kubernetes node.

    Args:
        node: Raw Kubernetes node object.
    Returns:
        Role names, defaulting to ``worker`` when no role label exists.
    """
    labels = safe_get(node, ["metadata", "labels"], {}) or {}
    roles = []
    prefix = "node-role.kubernetes.io/"
    for key, value in labels.items():
        if key == "kubernetes.io/role" and value:
            roles.append(str(value))
        elif key.startswith(prefix):
            role = key[len(prefix) :] or "worker"
            roles.append(role)
    return sorted(set(roles)) or ["worker"]


def is_controller_node(roles: Sequence[str]) -> bool:
    return any(role in ("master", "control-plane") for role in roles)


def node_condition(node: Dict[str, Any], cond_type: str) -> Optional[Dict[str, Any]]:
    for condition in safe_get(node, ["status", "conditions"], []) or []:
        if condition.get("type") == cond_type:
            return condition
    return None


def node_status(node: Dict[str, Any]) -> str:
    ready = node_condition(node, "Ready")
    return "Ready" if ready and ready.get("status") == "True" else "NotReady"


def node_pressures(node: Dict[str, Any]) -> List[str]:
    result = []
    mapping = [("MemoryPressure", "mem"), ("DiskPressure", "disk"), ("PIDPressure", "pid")]
    for cond_type, label in mapping:
        condition = node_condition(node, cond_type)
        if condition and condition.get("status") == "True":
            result.append(label)
    return result


def node_ip(node: Dict[str, Any], addr_type: str) -> str:
    for address in safe_get(node, ["status", "addresses"], []) or []:
        if address.get("type") == addr_type:
            return address.get("address", "-")
    return "-"


def pod_ready_counts(pod: Dict[str, Any]) -> Tuple[int, int]:
    statuses = safe_get(pod, ["status", "containerStatuses"], []) or []
    total = len(safe_get(pod, ["spec", "containers"], []) or [])
    ready = sum(1 for status in statuses if status.get("ready"))
    return ready, total


def pod_restart_count(pod: Dict[str, Any]) -> int:
    statuses = safe_get(pod, ["status", "containerStatuses"], []) or []
    return sum(int(status.get("restartCount") or 0) for status in statuses)


def pod_status(pod: Dict[str, Any]) -> str:
    """Derive a user-facing pod status. / Вычисляет пользовательский статус pod.

    Args:
        pod: Raw Kubernetes pod object.
    Returns:
        Status string such as ``Running``, ``NotReady``, or waiting reason.
    """
    if safe_get(pod, ["metadata", "deletionTimestamp"]):
        return "Terminating"

    phase = safe_get(pod, ["status", "phase"], "Unknown") or "Unknown"
    waiting_reason = None
    terminated_reason = None
    for status in safe_get(pod, ["status", "containerStatuses"], []) or []:
        state = status.get("state", {}) or {}
        waiting = state.get("waiting")
        terminated = state.get("terminated")
        if waiting and waiting.get("reason"):
            waiting_reason = waiting.get("reason")
        if terminated and terminated.get("reason"):
            terminated_reason = terminated.get("reason")

    if waiting_reason and waiting_reason not in ("ContainerCreating", "PodInitializing"):
        return waiting_reason
    if phase == "Succeeded":
        return "Completed"
    if terminated_reason and phase in ("Failed", "Unknown"):
        return terminated_reason
    if phase == "Running":
        ready, total = pod_ready_counts(pod)
        if total and ready < total:
            return "NotReady"
        return "Running"
    if waiting_reason:
        return waiting_reason
    return phase


def pod_conditions(pod: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Extract pod conditions. / Извлекает conditions pod.

    Args:
        pod: Raw Kubernetes pod object.
    Returns:
        Tuples of condition type, status, and reason/message.
    """
    result = []
    for condition in safe_get(pod, ["status", "conditions"], []) or []:
        result.append(
            (
                str(condition.get("type", "-")),
                str(condition.get("status", "-")),
                str(condition.get("reason") or condition.get("message") or ""),
            )
        )
    return result


def node_conditions(node: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Extract node conditions. / Извлекает conditions node.

    Args:
        node: Raw Kubernetes node object.
    Returns:
        Tuples of condition type, status, and reason/message.
    """
    result = []
    for condition in safe_get(node, ["status", "conditions"], []) or []:
        result.append(
            (
                str(condition.get("type", "-")),
                str(condition.get("status", "-")),
                str(condition.get("reason") or condition.get("message") or ""),
            )
        )
    return result


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def owner_refs(obj: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return controller-first owner references. / Возвращает ownerReferences с controller первым.

    Args:
        obj: Raw Kubernetes object.
    Returns:
        Ordered ``(kind, name)`` pairs.
    """
    refs = []
    for ref in safe_get(obj, ["metadata", "ownerReferences"], []) or []:
        kind = str(ref.get("kind") or "")
        name = str(ref.get("name") or "")
        if kind and name:
            refs.append((kind, name, bool(ref.get("controller"))))
    refs.sort(key=lambda item: 0 if item[2] else 1)
    return [(kind, name) for kind, name, _ in refs]


def selector_text(obj: Dict[str, Any]) -> str:
    """Format a workload selector. / Форматирует selector workload.

    Args:
        obj: Raw Kubernetes workload object.
    Returns:
        Human-readable selector text, or ``-``.
    """
    selector = safe_get(obj, ["spec", "selector"], {}) or {}
    labels = selector.get("matchLabels") or {}
    parts = ["%s=%s" % (key, labels[key]) for key in sorted(labels)]
    expressions = selector.get("matchExpressions") or []
    for expr in expressions:
        key = expr.get("key")
        operator = expr.get("operator")
        values = ",".join(str(value) for value in expr.get("values", []) or [])
        if key and operator:
            parts.append("%s %s %s" % (key, operator, values))
    return ", ".join(parts) if parts else "-"


def workload_status(kind: str, desired: int, ready: int, raw: Dict[str, Any]) -> str:
    """Derive normalized workload status. / Вычисляет нормализованный статус workload.

    Args:
        kind: Kubernetes workload kind.
        desired: Desired replica/completion count.
        ready: Ready or completed count.
        raw: Raw workload object for kind-specific status fields.
    Returns:
        Compact status string used in health and owner views.
    """
    if kind == "CronJob":
        if safe_get(raw, ["spec", "suspend"], False):
            return "Suspended"
        active = len(safe_get(raw, ["status", "active"], []) or [])
        return "Active" if active else "Idle"
    if kind == "Job":
        for condition in safe_get(raw, ["status", "conditions"], []) or []:
            if condition.get("status") == "True" and condition.get("type") in ("Complete", "Failed"):
                return str(condition.get("type"))
        active = int_value(safe_get(raw, ["status", "active"], 0))
        succeeded = int_value(safe_get(raw, ["status", "succeeded"], 0))
        failed = int_value(safe_get(raw, ["status", "failed"], 0))
        if failed:
            return "Failed"
        if succeeded and desired and succeeded >= desired:
            return "Complete"
        return "Active" if active else "Pending"
    if desired <= 0:
        return "ScaledDown"
    if ready >= desired:
        return "Ready"
    if ready > 0:
        return "Progressing"
    return "NotReady"


def make_workload(kind: str, item: Dict[str, Any]) -> WorkloadRow:
    """Convert raw workload JSON to WorkloadRow. / Преобразует raw workload JSON в WorkloadRow.

    Args:
        kind: Kubernetes workload kind.
        item: Raw workload object.
    Returns:
        Normalized workload row.
    """
    namespace = safe_get(item, ["metadata", "namespace"], "") or ""
    name = safe_get(item, ["metadata", "name"], "") or "-"
    owner = owner_refs(item)
    owner_kind, owner_name = owner[0] if owner else ("", "")

    if kind == "DaemonSet":
        desired = int_value(safe_get(item, ["status", "desiredNumberScheduled"], 0))
        ready = int_value(safe_get(item, ["status", "numberReady"], 0))
        updated = int_value(safe_get(item, ["status", "updatedNumberScheduled"], 0))
        available = int_value(safe_get(item, ["status", "numberAvailable"], ready))
        strategy = safe_get(item, ["spec", "updateStrategy", "type"], "-") or "-"
    elif kind == "Job":
        desired = int_value(safe_get(item, ["spec", "completions"], safe_get(item, ["spec", "parallelism"], 1)), 1)
        ready = int_value(safe_get(item, ["status", "succeeded"], 0))
        updated = int_value(safe_get(item, ["status", "active"], 0))
        available = ready
        strategy = "completions=%s parallelism=%s" % (
            safe_get(item, ["spec", "completions"], "-") or "-",
            safe_get(item, ["spec", "parallelism"], "-") or "-",
        )
    elif kind == "CronJob":
        active = len(safe_get(item, ["status", "active"], []) or [])
        desired = 0 if safe_get(item, ["spec", "suspend"], False) else 1
        ready = active
        updated = active
        available = active
        strategy = safe_get(item, ["spec", "schedule"], "-") or "-"
    else:
        desired = int_value(safe_get(item, ["spec", "replicas"], 1), 1)
        ready = int_value(safe_get(item, ["status", "readyReplicas"], 0))
        updated = int_value(
            safe_get(item, ["status", "updatedReplicas"], safe_get(item, ["status", "fullyLabeledReplicas"], ready))
        )
        available = int_value(safe_get(item, ["status", "availableReplicas"], ready))
        if kind in ("StatefulSet", "DaemonSet"):
            strategy = safe_get(item, ["spec", "updateStrategy", "type"], "-") or "-"
        else:
            strategy = safe_get(item, ["spec", "strategy", "type"], "-") or "-"

    return WorkloadRow(
        kind=kind,
        namespace=namespace,
        name=name,
        desired=desired,
        ready=ready,
        updated=updated,
        available=available,
        status=workload_status(kind, desired, ready, item),
        strategy=strategy,
        selector=selector_text(item),
        owner_kind=owner_kind,
        owner_name=owner_name,
        raw=item,
    )


def make_workloads(
    deployments_json: Optional[Dict[str, Any]],
    replicasets_json: Optional[Dict[str, Any]],
    statefulsets_json: Optional[Dict[str, Any]],
    daemonsets_json: Optional[Dict[str, Any]],
    jobs_json: Optional[Dict[str, Any]],
    cronjobs_json: Optional[Dict[str, Any]],
) -> Dict[Tuple[str, str, str], WorkloadRow]:
    """Build workload lookup by kind/namespace/name. / Создает индекс workload по kind/namespace/name.

    Args:
        deployments_json: Deployment list JSON.
        replicasets_json: ReplicaSet list JSON.
        statefulsets_json: StatefulSet list JSON.
        daemonsets_json: DaemonSet list JSON.
        jobs_json: Job list JSON.
        cronjobs_json: CronJob list JSON.
    Returns:
        Mapping keyed by ``(kind, namespace, name)``.
    """
    workloads: Dict[Tuple[str, str, str], WorkloadRow] = {}
    sources = [
        ("Deployment", deployments_json),
        ("ReplicaSet", replicasets_json),
        ("StatefulSet", statefulsets_json),
        ("DaemonSet", daemonsets_json),
        ("Job", jobs_json),
        ("CronJob", cronjobs_json),
    ]
    for kind, obj in sources:
        for item in list_items(obj):
            workload = make_workload(kind, item)
            workloads[(workload.kind, workload.namespace, workload.name)] = workload
    return workloads


def pod_owner_chain(
    pod: Dict[str, Any],
    namespace: str,
    workloads: Dict[Tuple[str, str, str], WorkloadRow],
) -> List[Tuple[str, str]]:
    """Resolve pod owner chain through known workloads. / Разрешает цепочку владельцев pod.

    Args:
        pod: Raw Kubernetes pod object.
        namespace: Pod namespace.
        workloads: Workload lookup created by make_workloads.
    Returns:
        Ordered owner chain, guarded against cycles and excessive depth.
    """
    chain = owner_refs(pod)
    seen = set(chain)
    cursor = chain[0] if chain else None
    while cursor and len(chain) < 8:
        kind, name = cursor
        workload = workloads.get((kind, namespace, name))
        if not workload or not workload.owner_kind or not workload.owner_name:
            break
        parent = (workload.owner_kind, workload.owner_name)
        if parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        cursor = parent
    return chain


def owner_chain_text(chain: Sequence[Tuple[str, str]]) -> str:
    return " > ".join("%s/%s" % (kind, name) for kind, name in chain) if chain else "-"


def sum_pod_requests(pod: Dict[str, Any]) -> Tuple[float, float]:
    """Sum pod container requests. / Суммирует requests контейнеров pod.

    Args:
        pod: Raw Kubernetes pod object.
    Returns:
        Tuple of CPU millicores and memory bytes.
    """
    cpu = 0.0
    mem = 0.0
    for container in safe_get(pod, ["spec", "containers"], []) or []:
        cpu += parse_cpu_millis(container_resource(container, "requests", "cpu"))
        mem += parse_bytes(container_resource(container, "requests", "memory"))
    return cpu, mem


def make_container_infos(
    pod: Dict[str, Any],
    container_metrics: Optional[Dict[str, ResourceUsage]] = None,
    container_histories: Optional[Dict[str, Tuple[List[float], List[float]]]] = None,
) -> List[ContainerInfo]:
    """Build normalized container rows for a pod. / Строит нормализованные строки контейнеров pod.

    Args:
        pod: Raw Kubernetes pod object.
        container_metrics: Optional per-container usage mapping.
        container_histories: Optional per-container CPU/MEM history mapping.
    Returns:
        ContainerInfo rows with aggregate single-container fallback applied.
    """
    container_metrics = container_metrics or {}
    container_histories = container_histories or {}
    statuses = {status.get("name"): status for status in safe_get(pod, ["status", "containerStatuses"], []) or []}
    containers = safe_get(pod, ["spec", "containers"], []) or []
    # Some cAdvisor versions expose a pod-level aggregate with an empty container
    # name. For one-container pods it is the best available container value.
    # Некоторые версии cAdvisor отдают aggregate с пустым именем контейнера.
    aggregate_usage = container_metrics.get("") if len(containers) == 1 else None
    aggregate_history = container_histories.get("") if len(containers) == 1 else None
    result = []
    for container in containers:
        name = container.get("name", "-")
        status = statuses.get(name, {})
        state = status.get("state", {}) or {}
        state_name = "Waiting"
        if state.get("running"):
            state_name = "Running"
        elif state.get("terminated"):
            state_name = state["terminated"].get("reason", "Terminated")
        elif state.get("waiting"):
            state_name = state["waiting"].get("reason", "Waiting")
        usage = usage_with_fallback(container_metrics.get(name), aggregate_usage)
        history = container_histories.get(name) or aggregate_history or ([], [])
        result.append(
            ContainerInfo(
                name=name,
                image=container.get("image", "-"),
                ready=bool(status.get("ready")),
                restarts=int(status.get("restartCount") or 0),
                status=state_name,
                usage_cpu_m=usage.cpu_m,
                usage_mem_b=usage.mem_b,
                cpu_request_m=parse_cpu_millis(container_resource(container, "requests", "cpu")),
                mem_request_b=parse_bytes(container_resource(container, "requests", "memory")),
                cpu_limit_m=parse_cpu_millis(container_resource(container, "limits", "cpu")),
                mem_limit_b=parse_bytes(container_resource(container, "limits", "memory")),
                ports=container_ports(container),
                mounts=len(container.get("volumeMounts", []) or []),
                cpu_history=history[0],
                mem_history=history[1],
            )
        )
    return result


def parse_top_nodes(text: str) -> Dict[str, ResourceUsage]:
    """Parse ``kubectl top nodes`` text. / Разбирает текст ``kubectl top nodes``.

    Args:
        text: Command output.
    Returns:
        Node name to ResourceUsage mapping.
    """
    result: Dict[str, ResourceUsage] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("NAME "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[0]
        result[name] = ResourceUsage(cpu_m=parse_cpu_millis(parts[1]), mem_b=parse_bytes(parts[3]))
    return result


def parse_top_pods(text: str, default_namespace: str, all_namespaces: bool) -> Dict[Tuple[str, str], ResourceUsage]:
    """Parse ``kubectl top pods`` text. / Разбирает текст ``kubectl top pods``.

    Args:
        text: Command output.
        default_namespace: Namespace used when output lacks namespace column.
        all_namespaces: Whether output includes namespace column.
    Returns:
        ``(namespace, pod)`` to ResourceUsage mapping.
    """
    result: Dict[Tuple[str, str], ResourceUsage] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("NAMESPACE ") or line.upper().startswith("NAME "):
            continue
        parts = line.split()
        if all_namespaces:
            if len(parts) < 4:
                continue
            namespace, pod_name, cpu, mem = parts[0], parts[1], parts[2], parts[3]
        else:
            if len(parts) < 3:
                continue
            namespace, pod_name, cpu, mem = default_namespace, parts[0], parts[1], parts[2]
        result[(namespace, pod_name)] = ResourceUsage(cpu_m=parse_cpu_millis(cpu), mem_b=parse_bytes(mem))
    return result


def parse_metrics_server_nodes(obj: Dict[str, Any]) -> Dict[str, ResourceUsage]:
    """Parse metrics.k8s.io node JSON. / Разбирает JSON nodes из metrics.k8s.io.

    Args:
        obj: Metrics Server nodes response.
    Returns:
        Node name to CPU/MEM usage mapping.
    """
    result: Dict[str, ResourceUsage] = {}
    for item in list_items(obj):
        name = safe_get(item, ["metadata", "name"], "")
        usage = safe_get(item, ["usage"], {}) or {}
        if not name:
            continue
        result[name] = ResourceUsage(
            cpu_m=parse_cpu_millis(usage.get("cpu")),
            mem_b=parse_bytes(usage.get("memory")),
        )
    return result


def parse_metrics_server_pods(
    obj: Dict[str, Any],
) -> Tuple[Dict[Tuple[str, str], ResourceUsage], Dict[Tuple[str, str, str], ResourceUsage]]:
    """Parse metrics.k8s.io pod JSON. / Разбирает JSON pods из metrics.k8s.io.

    Args:
        obj: Metrics Server pods response.
    Returns:
        Pair of pod usage mapping and container usage mapping.
    """
    pod_metrics: Dict[Tuple[str, str], ResourceUsage] = {}
    container_metrics: Dict[Tuple[str, str, str], ResourceUsage] = {}
    for item in list_items(obj):
        namespace = safe_get(item, ["metadata", "namespace"], "")
        pod_name = safe_get(item, ["metadata", "name"], "")
        if not namespace or not pod_name:
            continue
        pod_usage = ResourceUsage()
        for container in item.get("containers", []) or []:
            container_name = container.get("name", "")
            usage = container.get("usage", {}) or {}
            container_usage = ResourceUsage(
                cpu_m=parse_cpu_millis(usage.get("cpu")),
                mem_b=parse_bytes(usage.get("memory")),
            )
            add_usage(pod_usage, container_usage)
            if container_name:
                container_metrics[(namespace, pod_name, container_name)] = container_usage
        pod_metrics[(namespace, pod_name)] = pod_usage
    return pod_metrics, container_metrics


_PROM_SAMPLE_RE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+-]?Inf|NaN)"
    r"(?:\s+\d+)?$"
)
_PROM_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


def prom_unescape(value: str) -> str:
    return value.replace(r"\n", "\n").replace(r"\"", '"').replace(r"\\", "\\")


def parse_prometheus_labels(raw: str) -> Dict[str, str]:
    """Parse Prometheus label set. / Разбирает набор labels Prometheus.

    Args:
        raw: Text inside ``{...}``.
    Returns:
        Label dictionary with Prometheus escapes decoded.
    """
    labels: Dict[str, str] = {}
    for match in _PROM_LABEL_RE.finditer(raw or ""):
        labels[match.group(1)] = prom_unescape(match.group(2))
    return labels


def parse_prometheus_samples(text: str) -> List[Tuple[str, Dict[str, str], float]]:
    """Parse Prometheus exposition samples. / Разбирает samples Prometheus exposition format.

    Args:
        text: Raw metrics endpoint response.
    Returns:
        Tuples of metric name, labels, and finite float value.
    """
    samples: List[Tuple[str, Dict[str, str], float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PROM_SAMPLE_RE.match(line)
        if not match:
            continue
        try:
            value = float(match.group(3))
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        samples.append((match.group(1), parse_prometheus_labels(match.group(2) or ""), value))
    return samples


def prom_label(labels: Dict[str, str], *names: str) -> str:
    for name in names:
        value = labels.get(name)
        if value:
            return value
    return ""


def prom_pod_key(labels: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """Extract pod identity from metric labels. / Извлекает pod identity из labels метрики.

    Args:
        labels: Prometheus label mapping.
    Returns:
        ``(namespace, pod)`` or None when labels do not identify a pod.
    """
    namespace = prom_label(labels, "namespace", "kubernetes_namespace")
    pod = prom_label(labels, "pod", "pod_name", "kubernetes_pod_name")
    if namespace and pod:
        return namespace, pod
    return None


def prom_container_name(labels: Dict[str, str]) -> str:
    return prom_label(labels, "container", "container_name")


def prom_cpu_is_total(labels: Dict[str, str]) -> bool:
    cpu = labels.get("cpu")
    return not cpu or cpu == "total"


def prom_is_pause_container(labels: Dict[str, str]) -> bool:
    image = labels.get("image", "")
    return prom_container_name(labels) == "POD" or "/pause:" in image or image.startswith("pause:")


def prom_is_real_container(labels: Dict[str, str]) -> bool:
    container = prom_container_name(labels)
    return bool(container and not prom_is_pause_container(labels))


def prom_is_pod_aggregate(labels: Dict[str, str]) -> bool:
    return bool(
        prom_pod_key(labels)
        and not prom_container_name(labels)
        and not labels.get("image")
        and not labels.get("name")
    )


def prom_is_root_container(labels: Dict[str, str]) -> bool:
    return labels.get("id") == "/" and not prom_pod_key(labels)


def prom_series_key(node_name: str, metric: str, labels: Dict[str, str]) -> Tuple[str, str, Tuple[Tuple[str, str], ...]]:
    """Build stable counter-series key. / Строит стабильный ключ counter series.

    Args:
        node_name: Node where the metric was scraped.
        metric: Metric name.
        labels: Prometheus labels.
    Returns:
        Hashable key used for counter delta/rate calculation.
    """
    return node_name, metric, tuple(sorted(labels.items()))


def usage_for(mapping: Dict[Any, ResourceUsage], key: Any) -> ResourceUsage:
    usage = mapping.get(key)
    if usage is None:
        usage = ResourceUsage()
        mapping[key] = usage
    return usage


def usage_has_values(usage: ResourceUsage) -> bool:
    return bool(
        usage.cpu_m
        or usage.mem_b
        or usage.net_rx_bps
        or usage.net_tx_bps
        or usage.fs_read_bps
        or usage.fs_write_bps
    )


def usage_with_fallback(primary: Optional[ResourceUsage], fallback: Optional[ResourceUsage]) -> ResourceUsage:
    """Merge usage with zero-as-missing fallback. / Объединяет usage, считая нули отсутствующими.

    Args:
        primary: Preferred usage values.
        fallback: Fallback usage values.
    Returns:
        ResourceUsage filled from primary first, fallback second.
    """
    primary = primary or ResourceUsage()
    fallback = fallback or ResourceUsage()
    return ResourceUsage(
        cpu_m=primary.cpu_m or fallback.cpu_m,
        mem_b=primary.mem_b or fallback.mem_b,
        net_rx_bps=primary.net_rx_bps or fallback.net_rx_bps,
        net_tx_bps=primary.net_tx_bps or fallback.net_tx_bps,
        fs_read_bps=primary.fs_read_bps or fallback.fs_read_bps,
        fs_write_bps=primary.fs_write_bps or fallback.fs_write_bps,
    )


def add_usage(target: ResourceUsage, source: ResourceUsage) -> None:
    target.cpu_m += source.cpu_m
    target.mem_b += source.mem_b
    target.net_rx_bps += source.net_rx_bps
    target.net_tx_bps += source.net_tx_bps
    target.fs_read_bps += source.fs_read_bps
    target.fs_write_bps += source.fs_write_bps


def format_bytes_per_sec(value: float) -> str:
    return "%s/s" % format_bytes(value)


def format_cpu_millis(value: float) -> str:
    return "%dm" % int(round(max(0.0, float(value or 0.0))))


def format_mib(value: float) -> str:
    return "%dMi" % int(round(max(0.0, float(value or 0.0)) / (1024.0 ** 2)))


def format_resource_cpu(value: float) -> str:
    return format_cpu_millis(value) if value and value > 0 else "n/a"


def format_resource_mem(value: float) -> str:
    return format_mib(value) if value and value > 0 else "n/a"


def history_key_cluster(metric: str) -> Tuple[str, str]:
    return "cluster", metric


def history_key_node(name: str, metric: str) -> Tuple[str, str, str]:
    return "node", name, metric


def history_key_namespace(namespace: str, metric: str) -> Tuple[str, str, str]:
    return "namespace", namespace, metric


def history_key_pod(namespace: str, pod_name: str, metric: str) -> Tuple[str, str, str, str]:
    return "pod", namespace, pod_name, metric


def history_key_container(namespace: str, pod_name: str, container: str, metric: str) -> Tuple[str, str, str, str, str]:
    return "container", namespace, pod_name, container, metric


def history_values(
    history: Optional[Dict[Tuple[Any, ...], List[Tuple[float, float]]]],
    key: Tuple[Any, ...],
) -> List[float]:
    """Return retained values for a history key. / Возвращает значения истории по ключу.

    Args:
        history: Mapping of keys to timestamp/value samples.
        key: Metric history key.
    Returns:
        Values without timestamps; empty when missing.
    """
    if not history:
        return []
    return [value for _, value in history.get(key, [])]


SPARKLINE_LEVELS = "▁▂▃▄▅▆▇█"


def render_sparkline(values: Sequence[float], width: int = 10) -> str:
    """Render one-line unicode sparkline. / Рисует однострочный unicode sparkline.

    Args:
        values: Numeric history values.
        width: Desired output width.
    Returns:
        Sparkline text, or empty string when values are missing.
    """
    width = max(1, int(width))
    clean = [float(value or 0.0) for value in values if math.isfinite(float(value or 0.0))]
    if not clean:
        return ""
    if len(clean) > width:
        step = float(len(clean)) / float(width)
        reduced = []
        for idx in range(width):
            start = int(idx * step)
            end = int((idx + 1) * step)
            chunk = clean[start : max(start + 1, end)]
            reduced.append(sum(chunk) / float(len(chunk)))
        clean = reduced
    if len(clean) < width:
        clean = [clean[0]] * (width - len(clean)) + clean
    low = min(clean)
    high = max(clean)
    if high <= low:
        return SPARKLINE_LEVELS[0] * len(clean)
    scale = float(len(SPARKLINE_LEVELS) - 1) / float(high - low)
    return "".join(SPARKLINE_LEVELS[int(round((value - low) * scale))] for value in clean)


_CRON_MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_CRON_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_CRON_WEEKDAY_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


def cron_token_value(token: str, names: Optional[Dict[str, int]], sunday_alias: bool) -> int:
    """Parse one cron token. / Разбирает один token cron-поля.

    Args:
        token: Numeric token or known month/weekday name.
        names: Optional name lookup.
        sunday_alias: Whether ``7`` should mean Sunday.
    Returns:
        Integer field value.
    Raises:
        ValueError: If the token is unsupported.
    """
    value = token.strip().lower()
    if names and value in names:
        return names[value]
    parsed = int(value)
    if sunday_alias and parsed == 7:
        return 0
    return parsed


def cron_field_values(
    field: str,
    minimum: int,
    maximum: int,
    names: Optional[Dict[str, int]] = None,
    allow_question: bool = False,
    sunday_alias: bool = False,
) -> Tuple[Set[int], bool]:
    """Parse one cron field. / Разбирает одно cron-поле.

    Args:
        field: Cron field text.
        minimum: Inclusive lower bound.
        maximum: Inclusive upper bound.
        names: Optional month or weekday names.
        allow_question: Whether ``?`` is accepted as wildcard.
        sunday_alias: Whether weekday ``7`` is treated as ``0``.
    Returns:
        Allowed values and wildcard flag.
    Raises:
        ValueError: If syntax or values are unsupported.
    """
    field = str(field or "").strip().lower()
    if field == "*" or (allow_question and field == "?"):
        return set(range(minimum, maximum + 1)), True
    if not field:
        raise ValueError("empty cron field")
    values: Set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field item")
        base = part
        step = 1
        has_step = False
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
            has_step = True
            if step <= 0:
                raise ValueError("invalid cron step %s" % step_text)
        if base == "*" or (allow_question and base == "?"):
            start, end = minimum, maximum
        elif "-" in base:
            left, right = base.split("-", 1)
            start = cron_token_value(left, names, sunday_alias)
            end = cron_token_value(right, names, sunday_alias)
        else:
            start = cron_token_value(base, names, sunday_alias)
            end = maximum if has_step else start
        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise ValueError("cron value out of range")
        if start > end:
            raise ValueError("reversed cron range")
        values.update(range(start, end + 1, step))
    return values, False


def parse_cron_schedule(schedule: str) -> CronScheduleSpec:
    """Parse a Kubernetes CronJob schedule. / Разбирает расписание Kubernetes CronJob.

    Args:
        schedule: Five-field cron string or supported macro.
    Returns:
        CronScheduleSpec with allowed values.
    Raises:
        ValueError: If the schedule is unsupported.
    """
    text = str(schedule or "").strip().lower()
    text = _CRON_MACROS.get(text, text)
    parts = text.split()
    if len(parts) != 5:
        raise ValueError("expected five cron fields")
    minutes, _minute_any = cron_field_values(parts[0], 0, 59)
    hours, _hour_any = cron_field_values(parts[1], 0, 23)
    days, day_any = cron_field_values(parts[2], 1, 31, allow_question=True)
    months, _month_any = cron_field_values(parts[3], 1, 12, names=_CRON_MONTH_NAMES)
    weekdays, weekday_any = cron_field_values(parts[4], 0, 6, names=_CRON_WEEKDAY_NAMES, allow_question=True, sunday_alias=True)
    return CronScheduleSpec(minutes, hours, days, months, weekdays, day_any, weekday_any)


def cron_day_matches(moment: dt.datetime, spec: CronScheduleSpec) -> bool:
    """Check cron day-of-month/week semantics. / Проверяет cron day-of-month/week semantics."""
    day_match = moment.day in spec.days
    weekday = (moment.weekday() + 1) % 7
    weekday_match = weekday in spec.weekdays
    if spec.day_any and spec.weekday_any:
        return True
    if spec.day_any:
        return weekday_match
    if spec.weekday_any:
        return day_match
    return day_match or weekday_match


def cron_schedule_reference(now: dt.datetime, timezone_name: str) -> Tuple[dt.datetime, str]:
    """Convert reference time to a CronJob timezone. / Переводит reference time в timezone CronJob.

    Args:
        now: UTC or timezone-aware reference time.
        timezone_name: ``spec.timeZone`` value.
    Returns:
        Localized time and warning text when named timezone support is unavailable.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    name = (timezone_name or "").strip()
    if not name:
        return now.astimezone(), ""
    if name.upper() in ("UTC", "ETC/UTC", "GMT", "ETC/GMT", "Z"):
        return now.astimezone(dt.timezone.utc), ""
    return now.astimezone(), "timezone %s approximated as local time" % name


def cron_next_after(schedule: str, after: dt.datetime, timezone_name: str = "", max_days: int = 366) -> Tuple[Optional[dt.datetime], str]:
    """Find the next matching cron time. / Находит следующее срабатывание cron.

    Args:
        schedule: Kubernetes CronJob schedule.
        after: Reference time; result is strictly after it.
        timezone_name: Optional CronJob timezone.
        max_days: Search horizon.
    Returns:
        Next UTC datetime and parse/search warning.
    """
    try:
        spec = parse_cron_schedule(schedule)
    except ValueError as exc:
        return None, str(exc)
    local_after, timezone_warning = cron_schedule_reference(after, timezone_name)
    cursor = local_after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    end = cursor + dt.timedelta(days=max(1, max_days))
    minutes = sorted(spec.minutes)
    hours = sorted(spec.hours)
    day = cursor.date()
    while day <= end.date():
        base = dt.datetime.combine(day, dt.time(0, 0), tzinfo=cursor.tzinfo)
        if base.month not in spec.months or not cron_day_matches(base, spec):
            day = day + dt.timedelta(days=1)
            continue
        for hour in hours:
            if day == cursor.date() and hour < cursor.hour:
                continue
            for minute in minutes:
                candidate = base.replace(hour=hour, minute=minute)
                if candidate <= local_after or candidate < cursor or candidate > end:
                    continue
                return candidate.astimezone(dt.timezone.utc), timezone_warning
        day = day + dt.timedelta(days=1)
    return None, "no matching cron time within %dd" % max_days


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Calculate a nearest-rank percentile. / Считает percentile методом nearest-rank.

    Args:
        values: Numeric sample values.
        pct: Percentile in 0..100.
    Returns:
        Percentile value or None for empty input.
    """
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    pct = max(0.0, min(100.0, pct))
    if len(clean) == 1:
        return clean[0]
    index = int(math.ceil((pct / 100.0) * len(clean))) - 1
    return clean[max(0, min(len(clean) - 1, index))]


def format_duration_compact(seconds: Optional[float]) -> str:
    """Format duration seconds for narrow tables. / Форматирует длительность для узких таблиц."""
    if seconds is None or not math.isfinite(float(seconds)):
        return "-"
    seconds_i = max(0, int(round(float(seconds))))
    if seconds_i >= 86400:
        days, rem = divmod(seconds_i, 86400)
        hours = rem // 3600
        return "%dd%dh" % (days, hours) if hours else "%dd" % days
    if seconds_i >= 3600:
        hours, rem = divmod(seconds_i, 3600)
        minutes = rem // 60
        return "%dh%dm" % (hours, minutes) if minutes else "%dh" % hours
    if seconds_i >= 60:
        minutes, seconds_i = divmod(seconds_i, 60)
        return "%dm%ds" % (minutes, seconds_i) if seconds_i else "%dm" % minutes
    return "%ds" % seconds_i


def job_completion_time(raw: Dict[str, Any]) -> Optional[dt.datetime]:
    """Return Job completion/failure timestamp. / Возвращает время завершения или ошибки Job."""
    value = parse_rfc3339(safe_get(raw, ["status", "completionTime"]))
    if value:
        return value
    for condition in safe_get(raw, ["status", "conditions"], []) or []:
        if condition.get("status") == "True" and condition.get("type") in ("Complete", "Failed"):
            value = parse_rfc3339(condition.get("lastTransitionTime"))
            if value:
                return value
    return None


def job_run_from_workload(workload: WorkloadRow, now: Optional[dt.datetime] = None) -> Optional[CronJobRunRow]:
    """Convert an owned Job workload to a CronJob run. / Преобразует Job workload в запуск CronJob.

    Args:
        workload: Job workload row.
        now: Reference time for active duration.
    Returns:
        CronJobRunRow, or None when Job is not owned by a CronJob.
    """
    if workload.kind != "Job" or workload.owner_kind != "CronJob" or not workload.owner_name:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    raw = workload.raw
    start = parse_rfc3339(safe_get(raw, ["status", "startTime"]))
    completion = job_completion_time(raw)
    duration = None
    if start and completion:
        duration = max(0.0, (completion - start).total_seconds())
    elif start and workload.status == "Active":
        duration = max(0.0, (now - start).total_seconds())
    return CronJobRunRow(
        namespace=workload.namespace,
        name=workload.name,
        cronjob=workload.owner_name,
        status=workload.status,
        start_time=start,
        completion_time=completion,
        duration_s=duration,
        active=int_value(safe_get(raw, ["status", "active"], 0)),
        succeeded=int_value(safe_get(raw, ["status", "succeeded"], 0)),
        failed=int_value(safe_get(raw, ["status", "failed"], 0)),
        raw=raw,
    )


def build_cronjob_rows(snapshot: ClusterSnapshot, now: Optional[dt.datetime] = None) -> List[CronJobRow]:
    """Build CronJob SLA/dead-man rows from a snapshot. / Строит строки CronJob SLA/dead-man из snapshot.

    Args:
        snapshot: Current cluster snapshot.
        now: Optional reference time for deterministic tests.
    Returns:
        Sorted CronJob diagnostic rows.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    runs_by_key: Dict[Tuple[str, str], List[CronJobRunRow]] = {}
    for workload in snapshot.workloads.values():
        run = job_run_from_workload(workload, now)
        if run:
            runs_by_key.setdefault((run.namespace, run.cronjob), []).append(run)
    for runs in runs_by_key.values():
        runs.sort(key=lambda item: item.start_time or item.completion_time or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)

    rows: List[CronJobRow] = []
    for workload in sorted(snapshot.workloads.values(), key=lambda item: (item.namespace, item.name)):
        if workload.kind != "CronJob":
            continue
        raw = workload.raw
        key = (workload.namespace, workload.name)
        runs = runs_by_key.get(key, [])
        schedule = safe_get(raw, ["spec", "schedule"], "-") or "-"
        timezone_name = safe_get(raw, ["spec", "timeZone"], "") or ""
        suspend = bool(safe_get(raw, ["spec", "suspend"], False))
        created_at = parse_rfc3339(safe_get(raw, ["metadata", "creationTimestamp"]))
        last_schedule = parse_rfc3339(safe_get(raw, ["status", "lastScheduleTime"]))
        last_success = parse_rfc3339(safe_get(raw, ["status", "lastSuccessfulTime"]))
        reference = last_schedule or created_at or now
        next_schedule, parse_error = cron_next_after(schedule, reference, timezone_name)
        active = len(safe_get(raw, ["status", "active"], []) or [])
        succeeded = sum(1 for run in runs if run.status in ("Complete", "Completed") or run.succeeded)
        failed = sum(1 for run in runs if run.status == "Failed" or run.failed)
        completed_durations = [run.duration_s for run in runs if run.duration_s is not None and run.status in ("Complete", "Completed")]
        p50 = percentile(completed_durations, 50.0)
        p95 = percentile(completed_durations, 95.0)
        p99 = percentile(completed_durations, 99.0)
        latest = runs[0] if runs else None
        latest_job = latest.name if latest else "-"
        latest_status = latest.status if latest else "-"
        starting_deadline = int_value(safe_get(raw, ["spec", "startingDeadlineSeconds"], 0), 0)
        late_seconds = 0.0
        if next_schedule and next_schedule < now:
            late_seconds = max(0.0, (now - next_schedule).total_seconds())
        grace = float(max(60, starting_deadline or 300))
        suggestions: List[str] = []
        status = "OK"
        severity = "ok"
        hint = parse_error or "on schedule"

        if suspend:
            status = "Suspended"
            severity = "warning"
            hint = "suspended"
            suggestions.append("Unsuspend the CronJob when scheduled runs should resume.")
        elif parse_error and not next_schedule:
            status = "Unknown"
            severity = "warning"
            hint = parse_error
            suggestions.append("Check spec.schedule/spec.timeZone; ktop-py.py supports standard five-field cron syntax.")
        elif late_seconds > grace:
            status = "Missed"
            severity = "critical"
            hint = "late %s" % format_duration_compact(late_seconds)
            suggestions.append("Check kube-controller-manager, CronJob suspend flag, startingDeadlineSeconds, and recent events.")
        elif latest and (latest.status == "Failed" or latest.failed):
            status = "Failed"
            severity = "critical"
            hint = "latest job failed"
            suggestions.append("Open the CronJob detail, inspect related pod events, then use Enter/l for logs.")
        elif latest and latest.status == "Active" and latest.duration_s is not None and p95 and latest.duration_s > max(p95 * 2.0, p95 + 300.0):
            status = "LongRunning"
            severity = "warning"
            hint = "active %s > p95 %s" % (format_duration_compact(latest.duration_s), format_duration_compact(p95))
            suggestions.append("Compare this active run with previous durations and check pod logs/events.")
        elif latest and latest.duration_s is not None and p95 and len(completed_durations) >= 4 and latest.duration_s > max(p95 * 1.5, p95 + 120.0):
            status = "Slow"
            severity = "warning"
            hint = "duration regression"
            suggestions.append("Review recent logs and external dependencies; latest duration is above historical p95.")
        elif active:
            status = "Active"
            severity = "ok"
            hint = "running"

        rows.append(
            CronJobRow(
                namespace=workload.namespace,
                name=workload.name,
                schedule=schedule,
                timezone=timezone_name or "-",
                suspend=suspend,
                last_schedule=last_schedule,
                last_success=last_success,
                next_schedule=next_schedule,
                late_seconds=late_seconds,
                active=active,
                succeeded=succeeded,
                failed=failed,
                p50_s=p50,
                p95_s=p95,
                p99_s=p99,
                latest_job=latest_job,
                latest_status=latest_status,
                status=status,
                severity=severity,
                hint=hint,
                suggestions=suggestions,
                parse_error=parse_error,
                raw=raw,
            )
        )
    return rows


def make_events(events_json: Optional[Dict[str, Any]]) -> List[EventInfo]:
    """Normalize Kubernetes events. / Нормализует Kubernetes events.

    Args:
        events_json: Raw events list JSON.
    Returns:
        Newest-first EventInfo rows.
    """
    events: List[EventInfo] = []
    for item in list_items(events_json):
        involved = item.get("involvedObject", {}) or {}
        timestamp = (
            parse_rfc3339(item.get("lastTimestamp"))
            or parse_rfc3339(item.get("eventTime"))
            or parse_rfc3339(item.get("firstTimestamp"))
            or parse_rfc3339(safe_get(item, ["metadata", "creationTimestamp"]))
        )
        events.append(
            EventInfo(
                namespace=item.get("namespace") or involved.get("namespace") or safe_get(item, ["metadata", "namespace"], ""),
                kind=involved.get("kind", ""),
                name=involved.get("name", ""),
                reason=item.get("reason", ""),
                event_type=item.get("type", ""),
                message=item.get("message", ""),
                timestamp=timestamp,
            )
        )
    events.sort(key=lambda event: event.timestamp or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return events


def build_snapshot(
    nodes_json: Dict[str, Any],
    pods_json: Dict[str, Any],
    deployments_json: Optional[Dict[str, Any]],
    replicasets_json: Optional[Dict[str, Any]],
    statefulsets_json: Optional[Dict[str, Any]],
    daemonsets_json: Optional[Dict[str, Any]],
    jobs_json: Optional[Dict[str, Any]],
    cronjobs_json: Optional[Dict[str, Any]],
    namespaces_json: Optional[Dict[str, Any]],
    resourcequotas_json: Optional[Dict[str, Any]],
    limitranges_json: Optional[Dict[str, Any]],
    pv_json: Optional[Dict[str, Any]],
    pvc_json: Optional[Dict[str, Any]],
    events_json: Optional[Dict[str, Any]],
    node_metrics: Dict[str, ResourceUsage],
    pod_metrics: Dict[Tuple[str, str], ResourceUsage],
    container_metrics: Optional[Dict[Tuple[str, str, str], ResourceUsage]],
    metric_history: Optional[Dict[Tuple[Any, ...], List[Tuple[float, float]]]],
    context: str,
    user: str,
    k8s_version: str,
    namespace: str,
    metrics_status: str,
    metrics_available: bool,
    warnings: Optional[List[str]] = None,
) -> ClusterSnapshot:
    """Build a normalized cluster snapshot. / Строит нормализованный снимок кластера.

    Args:
        nodes_json: Raw node list JSON.
        pods_json: Raw pod list JSON.
        deployments_json: Raw Deployment list JSON.
        replicasets_json: Raw ReplicaSet list JSON.
        statefulsets_json: Raw StatefulSet list JSON.
        daemonsets_json: Raw DaemonSet list JSON.
        jobs_json: Raw Job list JSON.
        cronjobs_json: Raw CronJob list JSON.
        namespaces_json: Raw Namespace list JSON.
        resourcequotas_json: Raw ResourceQuota list JSON.
        limitranges_json: Raw LimitRange list JSON.
        pv_json: Raw PersistentVolume list JSON.
        pvc_json: Raw PersistentVolumeClaim list JSON.
        events_json: Raw Event list JSON.
        node_metrics: Node usage metrics.
        pod_metrics: Pod usage metrics.
        container_metrics: Optional container usage metrics.
        metric_history: Retained metric samples.
        context: Kubernetes context name.
        user: Kubernetes user name.
        k8s_version: Kubernetes version string.
        namespace: Display namespace scope.
        metrics_status: Human-readable metrics source state.
        metrics_available: Whether live metrics are available.
        warnings: Collection warnings.
    Returns:
        ClusterSnapshot consumed by TUI, dumps, and diagnostics.
    """
    warnings = warnings or []
    container_metrics = container_metrics or {}
    metric_history = metric_history or {}
    pod_items = list_items(pods_json)
    node_items = list_items(nodes_json)
    node_by_name = {safe_get(node, ["metadata", "name"], ""): node for node in node_items}
    workloads = make_workloads(
        deployments_json,
        replicasets_json,
        statefulsets_json,
        daemonsets_json,
        jobs_json,
        cronjobs_json,
    )

    # Index pods by node once; requested resources and restart counts are
    # node aggregates derived from pods, not fields on the Node object.
    # Индексируем pod по node один раз: requests/restarts узла считаются из pod.
    pods_by_node: Dict[str, List[Dict[str, Any]]] = {}
    for pod in pod_items:
        pods_by_node.setdefault(safe_get(pod, ["spec", "nodeName"], ""), []).append(pod)

    nodes: List[NodeRow] = []
    for node in node_items:
        name = safe_get(node, ["metadata", "name"], "-")
        alloc = safe_get(node, ["status", "allocatable"], {}) or {}
        node_pods = pods_by_node.get(name, [])
        requested_cpu = 0.0
        requested_mem = 0.0
        restarts = 0
        for pod in node_pods:
            cpu, mem = sum_pod_requests(pod)
            requested_cpu += cpu
            requested_mem += mem
            restarts += pod_restart_count(pod)
        usage = node_metrics.get(name, ResourceUsage())
        roles = node_roles(node)
        nodes.append(
            NodeRow(
                name=name,
                roles=roles,
                controller=is_controller_node(roles),
                hostname=node_ip(node, "Hostname"),
                status=node_status(node),
                pressures=node_pressures(node),
                creation_time=parse_rfc3339(safe_get(node, ["metadata", "creationTimestamp"])),
                internal_ip=node_ip(node, "InternalIP"),
                external_ip=node_ip(node, "ExternalIP"),
                pods_count=len(node_pods),
                images_count=len(safe_get(node, ["status", "images"], []) or []),
                volumes_in_use=len(safe_get(node, ["status", "volumesInUse"], []) or []),
                volumes_attached=len(safe_get(node, ["status", "volumesAttached"], []) or []),
                taints=len(safe_get(node, ["spec", "taints"], []) or []),
                unschedulable=bool(safe_get(node, ["spec", "unschedulable"], False)),
                restarts=restarts,
                kubelet=safe_get(node, ["status", "nodeInfo", "kubeletVersion"], "-"),
                os_image=safe_get(node, ["status", "nodeInfo", "osImage"], "-"),
                kernel=safe_get(node, ["status", "nodeInfo", "kernelVersion"], "-"),
                runtime=safe_get(node, ["status", "nodeInfo", "containerRuntimeVersion"], "-"),
                arch=safe_get(node, ["status", "nodeInfo", "architecture"], "-"),
                alloc_cpu_m=parse_cpu_millis(alloc.get("cpu")),
                alloc_mem_b=parse_bytes(alloc.get("memory")),
                alloc_storage_b=parse_bytes(alloc.get("ephemeral-storage")),
                requested_cpu_m=requested_cpu,
                requested_mem_b=requested_mem,
                usage_cpu_m=usage.cpu_m,
                usage_mem_b=usage.mem_b,
                net_rx_bps=usage.net_rx_bps,
                net_tx_bps=usage.net_tx_bps,
                fs_read_bps=usage.fs_read_bps,
                fs_write_bps=usage.fs_write_bps,
                cpu_history=history_values(metric_history, history_key_node(name, "cpu")),
                mem_history=history_values(metric_history, history_key_node(name, "mem")),
                net_history=history_values(metric_history, history_key_node(name, "net")),
                net_rx_history=history_values(metric_history, history_key_node(name, "net_rx")),
                net_tx_history=history_values(metric_history, history_key_node(name, "net_tx")),
                io_history=history_values(metric_history, history_key_node(name, "io")),
                fs_read_history=history_values(metric_history, history_key_node(name, "io_read")),
                fs_write_history=history_values(metric_history, history_key_node(name, "io_write")),
                conditions=node_conditions(node),
                raw=node,
            )
        )

    pods: List[PodRow] = []
    for pod in pod_items:
        namespace_name = safe_get(pod, ["metadata", "namespace"], "default")
        pod_name = safe_get(pod, ["metadata", "name"], "-")
        node_name = safe_get(pod, ["spec", "nodeName"], "")
        requested_cpu, requested_mem = sum_pod_requests(pod)
        usage = pod_metrics.get((namespace_name, pod_name), ResourceUsage())
        node = node_by_name.get(node_name, {})
        node_alloc = safe_get(node, ["status", "allocatable"], {}) or {}
        ready, total = pod_ready_counts(pod)
        container_usage_by_name = {
            key[2]: value
            for key, value in container_metrics.items()
            if key[0] == namespace_name and key[1] == pod_name
        }
        container_history_by_name = {
            key[2]: (
                history_values(metric_history, history_key_container(namespace_name, pod_name, key[2], "cpu")),
                history_values(metric_history, history_key_container(namespace_name, pod_name, key[2], "mem")),
            )
            for key in container_metrics
            if key[0] == namespace_name and key[1] == pod_name
        }
        containers = make_container_infos(pod, container_usage_by_name, container_history_by_name)
        pods.append(
            PodRow(
                namespace=namespace_name,
                name=pod_name,
                status=pod_status(pod),
                node=node_name or "-",
                ip=safe_get(pod, ["status", "podIP"], "-") or "-",
                creation_time=parse_rfc3339(safe_get(pod, ["metadata", "creationTimestamp"])),
                requested_cpu_m=requested_cpu,
                requested_mem_b=requested_mem,
                usage_cpu_m=usage.cpu_m,
                usage_mem_b=usage.mem_b,
                net_rx_bps=usage.net_rx_bps,
                net_tx_bps=usage.net_tx_bps,
                fs_read_bps=usage.fs_read_bps,
                fs_write_bps=usage.fs_write_bps,
                node_alloc_cpu_m=parse_cpu_millis(node_alloc.get("cpu")),
                node_alloc_mem_b=parse_bytes(node_alloc.get("memory")),
                ready=ready,
                total=total,
                restarts=pod_restart_count(pod),
                volumes=len(safe_get(pod, ["spec", "volumes"], []) or []),
                mounts=sum(len(c.get("volumeMounts", []) or []) for c in safe_get(pod, ["spec", "containers"], []) or []),
                containers=containers,
                cpu_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "cpu")),
                mem_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "mem")),
                net_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "net")),
                net_rx_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "net_rx")),
                net_tx_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "net_tx")),
                io_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "io")),
                fs_read_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "io_read")),
                fs_write_history=history_values(metric_history, history_key_pod(namespace_name, pod_name, "io_write")),
                conditions=pod_conditions(pod),
                owners=owner_refs(pod),
                owner_chain=pod_owner_chain(pod, namespace_name, workloads),
                raw=pod,
            )
        )

    deployments_ready = 0
    deployments_total = 0
    for item in list_items(deployments_json):
        desired = int(safe_get(item, ["spec", "replicas"], 1) or 0)
        ready = int(safe_get(item, ["status", "readyReplicas"], 0) or 0)
        deployments_total += desired
        deployments_ready += min(ready, desired)

    pv_capacity = 0.0
    for item in list_items(pv_json):
        pv_capacity += parse_bytes(safe_get(item, ["spec", "capacity", "storage"]))

    pvc_capacity = 0.0
    for item in list_items(pvc_json):
        pvc_capacity += parse_bytes(safe_get(item, ["status", "capacity", "storage"]) or safe_get(item, ["spec", "resources", "requests", "storage"]))

    creation_times = [node.creation_time for node in nodes if node.creation_time]
    uptime_start = min(creation_times) if creation_times else None
    namespace_names = sorted(
        set(
            [safe_get(item, ["metadata", "name"], "") for item in list_items(namespaces_json)]
            + [pod.namespace for pod in pods if pod.namespace]
        )
    )
    namespace_names = [name for name in namespace_names if name]
    namespace_statuses = {
        safe_get(item, ["metadata", "name"], ""): safe_get(item, ["status", "phase"], "Active") or "Active"
        for item in list_items(namespaces_json)
        if safe_get(item, ["metadata", "name"], "")
    }

    return ClusterSnapshot(
        context=context or "-",
        user=user or "-",
        k8s_version=k8s_version or "-",
        namespace=namespace,
        metrics_status=metrics_status,
        metrics_available=metrics_available,
        nodes=nodes,
        pods=pods,
        events=make_events(events_json),
        workloads=workloads,
        namespaces_count=len(namespace_names),
        deployments_ready=deployments_ready,
        deployments_total=deployments_total,
        pv_count=len(list_items(pv_json)),
        pv_capacity_b=pv_capacity,
        pvc_count=len(list_items(pvc_json)),
        pvc_capacity_b=pvc_capacity,
        volumes_in_use=sum(pod.volumes for pod in pods),
        uptime_start=uptime_start,
        cluster_cpu_history=history_values(metric_history, history_key_cluster("cpu")),
        cluster_mem_history=history_values(metric_history, history_key_cluster("mem")),
        cluster_net_history=history_values(metric_history, history_key_cluster("net")),
        cluster_net_rx_history=history_values(metric_history, history_key_cluster("net_rx")),
        cluster_net_tx_history=history_values(metric_history, history_key_cluster("net_tx")),
        cluster_io_history=history_values(metric_history, history_key_cluster("io")),
        cluster_fs_read_history=history_values(metric_history, history_key_cluster("io_read")),
        cluster_fs_write_history=history_values(metric_history, history_key_cluster("io_write")),
        warnings=warnings,
        namespaces=namespace_names,
        namespace_statuses=namespace_statuses,
        resource_quotas=list_items(resourcequotas_json),
        limit_ranges=list_items(limitranges_json),
    )


class KubectlClient:
    """kubectl-backed Kubernetes data client. / Клиент данных Kubernetes поверх kubectl."""

    def __init__(self, args: argparse.Namespace) -> None:
        """Initialize client state and metric caches. / Инициализирует состояние клиента и кэши метрик.

        Args:
            args: Parsed CLI arguments.
        """
        self.args = args
        self.kubectl = args.kubectl
        self.default_namespace = args.namespace or "default"
        self.all_namespaces = bool(getattr(args, "all_namespaces", not bool(args.namespace)))
        self.prom_counter_previous: Dict[Tuple[str, str, Tuple[Tuple[str, str], ...]], Tuple[float, float]] = {}
        self.metric_history: Dict[Tuple[Any, ...], List[Tuple[float, float]]] = {}
        self.metrics_fresh = False
        self.prom_cached_metrics: Optional[Tuple[Dict[str, ResourceUsage], Dict[Tuple[str, str], ResourceUsage], Dict[Tuple[str, str, str], ResourceUsage], str, bool]] = None
        self.prom_last_scrape_at = 0.0

    def ensure_available(self) -> None:
        if shutil.which(self.kubectl) is None:
            raise DataError("kubectl not found in PATH. Use --demo to preview ktop-py.py without a cluster.")

    def base_cmd(self) -> List[str]:
        cmd = [self.kubectl]
        if self.args.kubeconfig:
            cmd.extend(["--kubeconfig", self.args.kubeconfig])
        if self.args.context:
            cmd.extend(["--context", self.args.context])
        if self.args.request_timeout:
            cmd.extend(["--request-timeout", self.args.request_timeout])
        return cmd

    def scope_args(self, namespace: Optional[str] = None) -> List[str]:
        if self.all_namespaces:
            return ["-A"]
        namespace = namespace or self.default_namespace
        if namespace:
            return ["-n", namespace]
        return []

    def run(self, args: Sequence[str], timeout: Optional[float] = None) -> str:
        """Run kubectl and return stdout. / Запускает kubectl и возвращает stdout.

        Args:
            args: kubectl arguments after global flags.
            timeout: Optional subprocess timeout in seconds.
        Returns:
            Command stdout.
        Raises:
            DataError: If kubectl is missing, times out, or exits non-zero.
        """
        cmd = self.base_cmd() + list(args)
        try:
            # kubectl is executed as an argv list with shell disabled.
            completed = subprocess.run(  # nosec B603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=timeout or self.args.command_timeout,
            )
        except FileNotFoundError as exc:
            raise DataError("kubectl not found: %s" % exc) from exc
        except subprocess.TimeoutExpired as exc:
            raise DataError("kubectl command timed out: %s" % " ".join(cmd)) from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "exit %s" % completed.returncode
            raise DataError("%s: %s" % (" ".join(cmd), stderr))
        return completed.stdout

    def raw(self, path: str, timeout: Optional[float] = None) -> str:
        return self.run(["get", "--raw", path], timeout=timeout)

    def raw_json(self, path: str, description: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch and parse a kubectl raw JSON endpoint. / Читает и разбирает raw JSON endpoint kubectl.

        Args:
            path: Kubernetes API path.
            description: Human-readable endpoint name for errors.
            timeout: Optional command timeout.
        Returns:
            Parsed JSON object.
        Raises:
            DataError: If the request fails or JSON is invalid.
        """
        try:
            return json.loads(self.raw(path, timeout=timeout))
        except DataError:
            raise
        except json.JSONDecodeError as exc:
            raise DataError("%s returned invalid JSON: %s" % (description, exc)) from exc

    def json(self, args: Sequence[str], required: bool, warnings: List[str]) -> Dict[str, Any]:
        """Run ``kubectl get ... -o json``. / Выполняет ``kubectl get ... -o json``.

        Args:
            args: kubectl get arguments.
            required: Whether failure should abort snapshot loading.
            warnings: Mutable warning list for optional failures.
        Returns:
            Parsed JSON, or empty list object for optional failures.
        Raises:
            DataError: If required command fails or returns invalid JSON.
        """
        try:
            text = self.run(list(args) + ["-o", "json"])
            return json.loads(text)
        except (DataError, json.JSONDecodeError) as exc:
            if required:
                raise DataError(str(exc)) from exc
            warnings.append(str(exc))
            return {"items": []}

    def json_all_namespaces_or_scoped(self, resource: str, required: bool, warnings: List[str]) -> Dict[str, Any]:
        """Load a namespaced resource across all namespaces with scoped fallback. / Загружает namespaced ресурс по всем namespace с fallback.

        Args:
            resource: Kubernetes resource name accepted by ``kubectl get``.
            required: Whether the scoped fallback must succeed.
            warnings: Mutable warning list for fallback reasons.
        Returns:
            Parsed JSON list object.
        Raises:
            DataError: If both all-namespaces and required scoped calls fail.
        """
        if self.all_namespaces:
            return self.json(["get", resource, "-A"], required=required, warnings=warnings)
        try:
            text = self.run(["get", resource, "-A", "-o", "json"])
            return json.loads(text)
        except (DataError, json.JSONDecodeError) as exc:
            warnings.append("all namespaces %s unavailable, using %s: %s" % (resource, self.default_namespace, exc))
            return self.json(["get", resource] + self.scope_args(), required=required, warnings=warnings)

    def cluster_info(self, warnings: List[str]) -> Tuple[str, str, str]:
        """Load context, user, and server version. / Загружает context, user и версию сервера.

        Args:
            warnings: Mutable warning list for non-critical failures.
        Returns:
            Tuple of context, user, and Kubernetes version.
        """
        context = self.args.context or "-"
        user = "-"
        version = "-"
        try:
            context = self.run(["config", "current-context"]).strip() or context
        except DataError as exc:
            warnings.append(str(exc))
        try:
            cfg = json.loads(self.run(["config", "view", "--minify", "--raw", "-o", "json"]))
            contexts = safe_get(cfg, ["contexts"], []) or []
            if contexts:
                user = safe_get(contexts[0], ["context", "user"], "-") or "-"
        except (DataError, json.JSONDecodeError) as exc:
            warnings.append(str(exc))
        try:
            version_json = json.loads(self.run(["version", "-o", "json"]))
            version = safe_get(version_json, ["serverVersion", "gitVersion"], "-") or "-"
        except (DataError, json.JSONDecodeError) as exc:
            warnings.append(str(exc))
        return context, user, version

    def prometheus_scrape_interval(self) -> float:
        return max(0.0, float(getattr(self.args, "prometheus_scrape_interval", DEFAULT_PROMETHEUS_SCRAPE_SECONDS) or 0.0))

    def prometheus_retention(self) -> float:
        return max(1.0, float(getattr(self.args, "prometheus_retention", DEFAULT_PROMETHEUS_RETENTION_SECONDS) or DEFAULT_PROMETHEUS_RETENTION_SECONDS))

    def prometheus_max_samples(self) -> int:
        return max(1, int(getattr(self.args, "prometheus_max_samples", DEFAULT_PROMETHEUS_MAX_SAMPLES) or DEFAULT_PROMETHEUS_MAX_SAMPLES))

    def add_history_sample(self, key: Tuple[Any, ...], timestamp: float, value: float) -> None:
        """Store a bounded metric history sample. / Сохраняет sample метрики с retention limits.

        Args:
            key: Metric history key.
            timestamp: Sample Unix timestamp.
            value: Numeric sample value.
        """
        if not math.isfinite(float(value or 0.0)):
            return
        samples = self.metric_history.setdefault(key, [])
        samples.append((timestamp, max(0.0, float(value or 0.0))))
        cutoff = timestamp - self.prometheus_retention()
        max_samples = self.prometheus_max_samples()
        if len(samples) > max_samples or (samples and samples[0][0] < cutoff):
            self.metric_history[key] = [(sample_at, sample_value) for sample_at, sample_value in samples if sample_at >= cutoff][-max_samples:]

    def add_gauge_history_sample(self, key: Tuple[Any, ...], timestamp: float, value: float) -> None:
        if value and value > 0:
            self.add_history_sample(key, timestamp, value)

    def record_usage_history(
        self,
        node_metrics: Dict[str, ResourceUsage],
        pod_metrics: Dict[Tuple[str, str], ResourceUsage],
        container_metrics: Dict[Tuple[str, str, str], ResourceUsage],
        timestamp: float,
    ) -> None:
        """Record node/pod/container histories. / Записывает истории node/pod/container.

        Args:
            node_metrics: Current node metrics.
            pod_metrics: Current pod metrics.
            container_metrics: Current container metrics.
            timestamp: Sample Unix timestamp.
        """
        cluster_cpu = 0.0
        cluster_mem = 0.0
        cluster_net = 0.0
        cluster_io = 0.0
        cluster_net_rx = 0.0
        cluster_net_tx = 0.0
        cluster_fs_read = 0.0
        cluster_fs_write = 0.0
        for node_name, usage in node_metrics.items():
            self.add_history_sample(history_key_node(node_name, "cpu"), timestamp, usage.cpu_m)
            self.add_gauge_history_sample(history_key_node(node_name, "mem"), timestamp, usage.mem_b)
            self.add_history_sample(history_key_node(node_name, "net"), timestamp, usage.net_rx_bps + usage.net_tx_bps)
            self.add_history_sample(history_key_node(node_name, "net_rx"), timestamp, usage.net_rx_bps)
            self.add_history_sample(history_key_node(node_name, "net_tx"), timestamp, usage.net_tx_bps)
            self.add_history_sample(history_key_node(node_name, "io"), timestamp, usage.fs_read_bps + usage.fs_write_bps)
            self.add_history_sample(history_key_node(node_name, "io_read"), timestamp, usage.fs_read_bps)
            self.add_history_sample(history_key_node(node_name, "io_write"), timestamp, usage.fs_write_bps)
            cluster_cpu += usage.cpu_m
            cluster_mem += usage.mem_b
            cluster_net += usage.net_rx_bps + usage.net_tx_bps
            cluster_io += usage.fs_read_bps + usage.fs_write_bps
            cluster_net_rx += usage.net_rx_bps
            cluster_net_tx += usage.net_tx_bps
            cluster_fs_read += usage.fs_read_bps
            cluster_fs_write += usage.fs_write_bps
        self.add_history_sample(history_key_cluster("cpu"), timestamp, cluster_cpu)
        self.add_gauge_history_sample(history_key_cluster("mem"), timestamp, cluster_mem)
        self.add_history_sample(history_key_cluster("net"), timestamp, cluster_net)
        self.add_history_sample(history_key_cluster("net_rx"), timestamp, cluster_net_rx)
        self.add_history_sample(history_key_cluster("net_tx"), timestamp, cluster_net_tx)
        self.add_history_sample(history_key_cluster("io"), timestamp, cluster_io)
        self.add_history_sample(history_key_cluster("io_read"), timestamp, cluster_fs_read)
        self.add_history_sample(history_key_cluster("io_write"), timestamp, cluster_fs_write)
        for (namespace, pod_name), usage in pod_metrics.items():
            self.add_history_sample(history_key_pod(namespace, pod_name, "cpu"), timestamp, usage.cpu_m)
            self.add_gauge_history_sample(history_key_pod(namespace, pod_name, "mem"), timestamp, usage.mem_b)
            self.add_history_sample(history_key_pod(namespace, pod_name, "net"), timestamp, usage.net_rx_bps + usage.net_tx_bps)
            self.add_history_sample(history_key_pod(namespace, pod_name, "net_rx"), timestamp, usage.net_rx_bps)
            self.add_history_sample(history_key_pod(namespace, pod_name, "net_tx"), timestamp, usage.net_tx_bps)
            self.add_history_sample(history_key_pod(namespace, pod_name, "io"), timestamp, usage.fs_read_bps + usage.fs_write_bps)
            self.add_history_sample(history_key_pod(namespace, pod_name, "io_read"), timestamp, usage.fs_read_bps)
            self.add_history_sample(history_key_pod(namespace, pod_name, "io_write"), timestamp, usage.fs_write_bps)
        for (namespace, pod_name, container), usage in container_metrics.items():
            self.add_history_sample(history_key_container(namespace, pod_name, container, "cpu"), timestamp, usage.cpu_m)
            self.add_gauge_history_sample(history_key_container(namespace, pod_name, container, "mem"), timestamp, usage.mem_b)

    def prometheus_components(self) -> List[str]:
        raw = getattr(self.args, "prometheus_components", "kubelet,cadvisor") or "kubelet,cadvisor"
        components = []
        for part in raw.split(","):
            component = part.strip().lower()
            if component and component not in components:
                components.append(component)
        return components or ["kubelet", "cadvisor"]

    def metrics_server_pods_path(self) -> str:
        return "/apis/metrics.k8s.io/v1beta1/pods"

    def load_metrics_server_metrics(
        self,
        status: str = "metrics-server",
    ) -> Tuple[Dict[str, ResourceUsage], Dict[Tuple[str, str], ResourceUsage], Dict[Tuple[str, str, str], ResourceUsage], str, bool]:
        """Load Metrics Server CPU/MEM metrics. / Загружает CPU/MEM из Metrics Server.

        Args:
            status: Metrics status text to attach to the snapshot.
        Returns:
            Node, pod, container metrics, status, and availability flag.
        Raises:
            DataError: If Metrics Server endpoints are unavailable or empty.
        """
        timeout = max(self.args.command_timeout, 12.0)
        nodes_json = self.raw_json(
            "/apis/metrics.k8s.io/v1beta1/nodes",
            "metrics-server node metrics",
            timeout=timeout,
        )
        pods_json = self.raw_json(
            self.metrics_server_pods_path(),
            "metrics-server pod metrics",
            timeout=timeout,
        )
        node_metrics = parse_metrics_server_nodes(nodes_json)
        pod_metrics, container_metrics = parse_metrics_server_pods(pods_json)
        if not node_metrics and not pod_metrics:
            raise DataError("metrics-server returned no node or pod metrics")
        self.metrics_fresh = True
        return node_metrics, pod_metrics, container_metrics, status, True

    def prom_counter_rate(self, node_name: str, metric: str, labels: Dict[str, str], value: float, scraped_at: float) -> Optional[float]:
        """Convert a Prometheus counter sample to a rate. / Переводит counter sample Prometheus в rate.

        Args:
            node_name: Scraped node name.
            metric: Metric name.
            labels: Metric labels.
            value: Current counter value.
            scraped_at: Sample timestamp.
        Returns:
            Per-second rate, or None until a previous sample exists or counter resets.
        """
        key = prom_series_key(node_name, metric, labels)
        previous = self.prom_counter_previous.get(key)
        self.prom_counter_previous[key] = (scraped_at, value)
        if previous is None:
            return None
        prev_at, prev_value = previous
        elapsed = scraped_at - prev_at
        if elapsed <= 0 or value < prev_value:
            return None
        return (value - prev_value) / elapsed

    def process_kubelet_prometheus_samples(
        self,
        node_name: str,
        text: str,
        scraped_at: float,
        node_metrics: Dict[str, ResourceUsage],
    ) -> Tuple[int, int]:
        """Process kubelet Prometheus samples. / Обрабатывает Prometheus samples kubelet.

        Args:
            node_name: Node that was scraped.
            text: Raw Prometheus response.
            scraped_at: Sample timestamp.
            node_metrics: Mutable node metrics mapping.
        Returns:
            Tuple of parsed sample count and usable rate count.
        """
        samples = parse_prometheus_samples(text)
        rate_count = 0
        node_usage = usage_for(node_metrics, node_name)
        for metric, labels, value in samples:
            if metric == "node_cpu_usage_seconds_total":
                rate = self.prom_counter_rate(node_name, metric, labels, value, scraped_at)
                if rate is not None:
                    node_usage.cpu_m = max(node_usage.cpu_m, rate * 1000.0)
                    rate_count += 1
            elif metric == "node_memory_working_set_bytes":
                node_usage.mem_b = max(node_usage.mem_b, value)
        return len(samples), rate_count

    def process_cadvisor_prometheus_samples(
        self,
        node_name: str,
        text: str,
        scraped_at: float,
        node_metrics: Dict[str, ResourceUsage],
        pod_metrics: Dict[Tuple[str, str], ResourceUsage],
        container_metrics: Dict[Tuple[str, str, str], ResourceUsage],
    ) -> Tuple[int, int]:
        """Process cAdvisor Prometheus samples. / Обрабатывает Prometheus samples cAdvisor.

        Args:
            node_name: Node that was scraped.
            text: Raw cAdvisor metrics response.
            scraped_at: Sample timestamp.
            node_metrics: Mutable node metrics mapping.
            pod_metrics: Mutable pod metrics mapping.
            container_metrics: Mutable container metrics mapping.
        Returns:
            Tuple of parsed sample count and usable rate count.
        """
        samples = parse_prometheus_samples(text)
        rate_count = 0
        root_seen = ResourceUsage()
        pod_rollup = ResourceUsage()
        individual_pod_usage: Dict[Tuple[str, str], ResourceUsage] = {}
        aggregate_pod_usage: Dict[Tuple[str, str], ResourceUsage] = {}
        node_usage = usage_for(node_metrics, node_name)

        for metric, labels, value in samples:
            pod_key = prom_pod_key(labels)
            container = prom_container_name(labels)
            container_key = (pod_key[0], pod_key[1], container) if pod_key and prom_is_real_container(labels) else None
            is_root = prom_is_root_container(labels)
            is_aggregate = prom_is_pod_aggregate(labels)

            if metric == "container_cpu_usage_seconds_total":
                if not prom_cpu_is_total(labels):
                    continue
                rate = self.prom_counter_rate(node_name, metric, labels, value, scraped_at)
                if rate is None:
                    continue
                cpu_m = rate * 1000.0
                rate_count += 1
                if is_root:
                    node_usage.cpu_m = max(node_usage.cpu_m, cpu_m)
                    root_seen.cpu_m = 1.0
                if container_key:
                    usage_for(individual_pod_usage, pod_key).cpu_m += cpu_m
                    usage_for(container_metrics, container_key).cpu_m += cpu_m
                elif is_aggregate:
                    usage_for(aggregate_pod_usage, pod_key).cpu_m += cpu_m

            elif metric == "container_memory_working_set_bytes":
                if is_root:
                    node_usage.mem_b = max(node_usage.mem_b, value)
                    root_seen.mem_b = 1.0
                if container_key:
                    usage_for(individual_pod_usage, pod_key).mem_b += value
                    usage_for(container_metrics, container_key).mem_b += value
                elif is_aggregate:
                    usage_for(aggregate_pod_usage, pod_key).mem_b += value

            elif metric in ("container_network_receive_bytes_total", "container_network_transmit_bytes_total"):
                rate = self.prom_counter_rate(node_name, metric, labels, value, scraped_at)
                if rate is None:
                    continue
                rate_count += 1
                if metric == "container_network_receive_bytes_total":
                    if is_root:
                        node_usage.net_rx_bps += rate
                        root_seen.net_rx_bps = 1.0
                    if pod_key:
                        usage = individual_pod_usage if container_key else aggregate_pod_usage
                        usage_for(usage, pod_key).net_rx_bps += rate
                else:
                    if is_root:
                        node_usage.net_tx_bps += rate
                        root_seen.net_tx_bps = 1.0
                    if pod_key:
                        usage = individual_pod_usage if container_key else aggregate_pod_usage
                        usage_for(usage, pod_key).net_tx_bps += rate

            elif metric in ("container_fs_reads_bytes_total", "container_fs_writes_bytes_total"):
                rate = self.prom_counter_rate(node_name, metric, labels, value, scraped_at)
                if rate is None:
                    continue
                rate_count += 1
                if metric == "container_fs_reads_bytes_total":
                    if is_root:
                        node_usage.fs_read_bps += rate
                        root_seen.fs_read_bps = 1.0
                    if container_key:
                        usage_for(individual_pod_usage, pod_key).fs_read_bps += rate
                        usage_for(container_metrics, container_key).fs_read_bps += rate
                    elif is_aggregate:
                        usage_for(aggregate_pod_usage, pod_key).fs_read_bps += rate
                else:
                    if is_root:
                        node_usage.fs_write_bps += rate
                        root_seen.fs_write_bps = 1.0
                    if container_key:
                        usage_for(individual_pod_usage, pod_key).fs_write_bps += rate
                        usage_for(container_metrics, container_key).fs_write_bps += rate
                    elif is_aggregate:
                        usage_for(aggregate_pod_usage, pod_key).fs_write_bps += rate

        # Prefer per-container sums, but fall back to cAdvisor pod aggregates when
        # individual container series are missing.
        # Предпочитаем суммы контейнеров, но используем aggregate pod series.
        for pod_key in sorted(set(individual_pod_usage) | set(aggregate_pod_usage)):
            aggregate_usage = aggregate_pod_usage.get(pod_key)
            pod_usage = usage_with_fallback(individual_pod_usage.get(pod_key), aggregate_usage)
            if not usage_has_values(pod_usage):
                continue
            add_usage(usage_for(pod_metrics, pod_key), pod_usage)
            add_usage(pod_rollup, pod_usage)
            if aggregate_usage and usage_has_values(aggregate_usage):
                add_usage(usage_for(container_metrics, (pod_key[0], pod_key[1], "")), aggregate_usage)

        # Root cgroup series are not guaranteed on every runtime; roll up pod
        # values to node totals when root metrics were not observed.
        # Root cgroup есть не всегда; тогда собираем node totals из pod метрик.
        if not root_seen.cpu_m and not node_usage.cpu_m:
            node_usage.cpu_m += pod_rollup.cpu_m
        if not root_seen.mem_b and not node_usage.mem_b:
            node_usage.mem_b += pod_rollup.mem_b
        if not root_seen.net_rx_bps:
            node_usage.net_rx_bps += pod_rollup.net_rx_bps
        if not root_seen.net_tx_bps:
            node_usage.net_tx_bps += pod_rollup.net_tx_bps
        if not root_seen.fs_read_bps:
            node_usage.fs_read_bps += pod_rollup.fs_read_bps
        if not root_seen.fs_write_bps:
            node_usage.fs_write_bps += pod_rollup.fs_write_bps
        return len(samples), rate_count

    def load_prometheus_metrics(
        self,
        warnings: List[str],
        nodes_json: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, ResourceUsage], Dict[Tuple[str, str], ResourceUsage], Dict[Tuple[str, str, str], ResourceUsage], str, bool]:
        """Scrape kubelet/cAdvisor Prometheus endpoints. / Скрейпит kubelet/cAdvisor Prometheus endpoints.

        Args:
            warnings: Mutable warning list for partial scrape failures.
            nodes_json: Raw node list used to discover node names.
        Returns:
            Node, pod, container metrics, status, and availability flag.
        Raises:
            DataError: If scraping yields no usable samples.
        """
        now = time.time()
        scrape_interval = self.prometheus_scrape_interval()
        if self.prom_cached_metrics and scrape_interval > 0 and now - self.prom_last_scrape_at < scrape_interval:
            self.metrics_fresh = False
            return self.prom_cached_metrics

        node_names = [safe_get(node, ["metadata", "name"], "") for node in list_items(nodes_json)]
        node_names = [name for name in node_names if name]
        if not node_names:
            raise DataError("prometheus scrape cannot run: no nodes found")

        components = self.prometheus_components()
        node_metrics: Dict[str, ResourceUsage] = {}
        pod_metrics: Dict[Tuple[str, str], ResourceUsage] = {}
        container_metrics: Dict[Tuple[str, str, str], ResourceUsage] = {}
        sample_count = 0
        cadvisor_sample_count = 0
        rate_count = 0
        scrape_errors: List[str] = []

        for node_name in node_names:
            escaped_node = urllib.parse.quote(node_name, safe="")
            if "kubelet" in components:
                path = "/api/v1/nodes/%s/proxy/metrics" % escaped_node
                try:
                    samples, rates = self.process_kubelet_prometheus_samples(
                        node_name,
                        self.raw(path, timeout=max(self.args.command_timeout, 20.0)),
                        time.time(),
                        node_metrics,
                    )
                    sample_count += samples
                    rate_count += rates
                except DataError as exc:
                    scrape_errors.append("kubelet %s: %s" % (node_name, exc))

            if "cadvisor" in components:
                path = "/api/v1/nodes/%s/proxy/metrics/cadvisor" % escaped_node
                try:
                    samples, rates = self.process_cadvisor_prometheus_samples(
                        node_name,
                        self.raw(path, timeout=max(self.args.command_timeout, 20.0)),
                        time.time(),
                        node_metrics,
                        pod_metrics,
                        container_metrics,
                    )
                    sample_count += samples
                    cadvisor_sample_count += samples
                    rate_count += rates
                except DataError as exc:
                    scrape_errors.append("cadvisor %s: %s" % (node_name, exc))

        for error in scrape_errors[:3]:
            warnings.append("prometheus scrape warning: %s" % error)
        if sample_count <= 0:
            detail = "; ".join(scrape_errors[:2]) if scrape_errors else "no samples returned"
            raise DataError("prometheus scrape failed: %s" % detail)
        if "cadvisor" in components and cadvisor_sample_count <= 0:
            detail = "; ".join([error for error in scrape_errors if error.startswith("cadvisor")][:2]) or "no cAdvisor samples returned"
            raise DataError("prometheus cAdvisor scrape failed: %s" % detail)
        status = "prometheus"
        # Counter-based CPU/network/disk metrics need two scrapes before rates
        # are meaningful, so the first scrape is marked as warming.
        # Counter-метрикам нужно два scrape, поэтому первый проход warming.
        if rate_count <= 0:
            status = "prometheus (warming)"
        result = (node_metrics, pod_metrics, container_metrics, status, True)
        self.prom_cached_metrics = result
        self.prom_last_scrape_at = now
        self.metrics_fresh = True
        return result

    def load_metrics(
        self,
        warnings: List[str],
        nodes_json: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, ResourceUsage], Dict[Tuple[str, str], ResourceUsage], Dict[Tuple[str, str, str], ResourceUsage], str, bool]:
        """Load metrics from selected source with fallback. / Загружает метрики из выбранного источника с fallback.

        Args:
            warnings: Mutable warning list.
            nodes_json: Optional node list for Prometheus scraping.
        Returns:
            Node, pod, container metrics, status, and availability flag.
        """
        source = (self.args.metrics_source or "prometheus").lower()
        if source in ("none", "off", "disabled"):
            self.metrics_fresh = False
            return {}, {}, {}, "none", False
        if source in ("prom", "prometheus"):
            try:
                return self.load_prometheus_metrics(warnings, nodes_json)
            except DataError as exc:
                if getattr(self.args, "metrics_source_explicit", False):
                    raise
                warnings.append("prometheus unavailable: %s" % exc)
        try:
            status = "metrics-server"
            if source in ("prom", "prometheus"):
                status = "metrics-server (prom fallback)"
            return self.load_metrics_server_metrics(status=status)
        except DataError as exc:
            warnings.append("metrics unavailable: %s" % exc)
            self.metrics_fresh = False
            return {}, {}, {}, "not connected", False

    def load_snapshot(self) -> ClusterSnapshot:
        """Load one complete cluster snapshot. / Загружает один полный снимок кластера.

        Returns:
            ClusterSnapshot with Kubernetes objects, metrics, histories, and warnings.
        Raises:
            DataError: If required kubectl calls fail.
        """
        self.ensure_available()
        warnings: List[str] = []
        context, user, version = self.cluster_info(warnings)
        nodes_json = self.json(["get", "nodes"], required=True, warnings=warnings)
        pods_json = self.json_all_namespaces_or_scoped("pods", required=True, warnings=warnings)
        deployments_json = self.json_all_namespaces_or_scoped("deployments", required=False, warnings=warnings)
        replicasets_json = self.json_all_namespaces_or_scoped("replicasets", required=False, warnings=warnings)
        statefulsets_json = self.json_all_namespaces_or_scoped("statefulsets", required=False, warnings=warnings)
        daemonsets_json = self.json_all_namespaces_or_scoped("daemonsets", required=False, warnings=warnings)
        jobs_json = self.json_all_namespaces_or_scoped("jobs", required=False, warnings=warnings)
        cronjobs_json = self.json_all_namespaces_or_scoped("cronjobs", required=False, warnings=warnings)
        namespaces_json = self.json(["get", "namespaces"], required=False, warnings=warnings)
        resourcequotas_json = self.json_all_namespaces_or_scoped("resourcequotas", required=False, warnings=warnings)
        limitranges_json = self.json_all_namespaces_or_scoped("limitranges", required=False, warnings=warnings)
        pv_json = self.json(["get", "pv"], required=False, warnings=warnings)
        pvc_json = self.json_all_namespaces_or_scoped("pvc", required=False, warnings=warnings)
        events_json = self.json_all_namespaces_or_scoped("events", required=False, warnings=warnings)
        node_metrics, pod_metrics, container_metrics, metrics_status, metrics_available = self.load_metrics(warnings, nodes_json)
        if metrics_available and self.metrics_fresh:
            self.record_usage_history(node_metrics, pod_metrics, container_metrics, time.time())
        namespace_display = "(all)" if self.all_namespaces else self.default_namespace
        return build_snapshot(
            nodes_json,
            pods_json,
            deployments_json,
            replicasets_json,
            statefulsets_json,
            daemonsets_json,
            jobs_json,
            cronjobs_json,
            namespaces_json,
            resourcequotas_json,
            limitranges_json,
            pv_json,
            pvc_json,
            events_json,
            node_metrics,
            pod_metrics,
            container_metrics,
            self.metric_history,
            context,
            user,
            version,
            namespace_display,
            metrics_status,
            metrics_available,
            warnings,
        )

    def diagnostic_timeout(self) -> float:
        return max(3.0, min(float(self.args.command_timeout or 8.0), 10.0))

    def diagnostics_lines(self) -> List[str]:
        """Run Metrics/RBAC diagnostics. / Выполняет диагностику Metrics/RBAC.

        Returns:
            Human-readable diagnostics lines.
        Raises:
            DataError: If kubectl itself is unavailable.
        """
        self.ensure_available()
        lines = [
            "Metrics / RBAC diagnostics",
            "Mode: %s%s" % (self.args.metrics_source, "" if getattr(self.args, "metrics_source_explicit", False) else " (auto fallback enabled)"),
            "",
        ]
        results: List[DiagnosticResult] = []

        def add_result(name: str, status: str, detail: str, hint: str = "") -> None:
            results.append(DiagnosticResult(name, status, detail, hint))

        def check_can_i(name: str, args: Sequence[str], hint: str) -> None:
            try:
                out = self.run(["auth", "can-i"] + list(args), timeout=self.diagnostic_timeout()).strip().lower()
                if out == "yes":
                    add_result(name, "OK", "allowed")
                else:
                    add_result(name, "FAIL", "kubectl auth can-i returned %s" % (out or "no"), hint)
            except DataError as exc:
                add_result(name, "FAIL", str(exc), hint)

        def check_raw_json(name: str, path: str, hint: str) -> None:
            try:
                obj = self.raw_json(path, name, timeout=self.diagnostic_timeout())
                add_result(name, "OK", "%d item(s)" % len(list_items(obj)))
            except DataError as exc:
                add_result(name, "FAIL", str(exc), hint)

        check_can_i(
            "metrics.k8s.io nodes",
            ["list", "nodes.metrics.k8s.io"],
            "grant list on nodes.metrics.k8s.io or use --metrics-source prometheus/none",
        )
        check_can_i(
            "metrics.k8s.io pods",
            ["list", "pods.metrics.k8s.io"],
            "grant list on pods.metrics.k8s.io or use --metrics-source prometheus/none",
        )
        check_can_i(
            "kubelet node proxy",
            ["get", "nodes/proxy"],
            "grant get on nodes/proxy for direct prometheus scrape",
        )
        check_raw_json(
            "Metrics API nodes raw",
            "/apis/metrics.k8s.io/v1beta1/nodes",
            "metrics-server may be missing, unhealthy, or RBAC-blocked",
        )
        check_raw_json(
            "Metrics API pods raw",
            self.metrics_server_pods_path(),
            "metrics-server pod endpoint may be missing or RBAC-blocked",
        )

        node_names: List[str] = []
        warnings: List[str] = []
        nodes_json = self.json(["get", "nodes"], required=False, warnings=warnings)
        node_names = [safe_get(node, ["metadata", "name"], "") for node in list_items(nodes_json)]
        node_names = [name for name in node_names if name]
        if warnings:
            add_result("node list", "FAIL", warnings[0], "grant list nodes to test kubelet endpoints")
        elif not node_names:
            add_result("node list", "WARN", "no nodes returned", "check cluster access")

        for endpoint, label in (("metrics", "/metrics"), ("cadvisor", "/metrics/cadvisor")):
            ok = 0
            first_error = ""
            for node_name in node_names:
                escaped_node = urllib.parse.quote(node_name, safe="")
                try:
                    text = self.raw("/api/v1/nodes/%s/proxy%s" % (escaped_node, label), timeout=self.diagnostic_timeout())
                    if text.strip():
                        ok += 1
                    else:
                        first_error = first_error or "%s returned empty response" % node_name
                except DataError as exc:
                    first_error = first_error or "%s: %s" % (node_name, exc)
            if node_names and ok == len(node_names):
                add_result("kubelet %s" % endpoint, "OK", "%d/%d node(s) reachable" % (ok, len(node_names)))
            elif node_names:
                add_result(
                    "kubelet %s" % endpoint,
                    "FAIL" if ok == 0 else "WARN",
                    "%d/%d node(s) reachable; %s" % (ok, len(node_names), first_error or "some nodes failed"),
                    "grant nodes/proxy and verify kubelet metrics endpoint",
                )

        width = max(len(result.name) for result in results) if results else 10
        for result in results:
            lines.append("%-6s %-*s %s" % (result.status, width, result.name, truncate(result.detail, 140)))
            if result.hint and result.status != "OK":
                lines.append("       hint: %s" % result.hint)
        return lines

    def object_args(self, kind: str, namespace: str, name: str) -> List[str]:
        """Build kubectl object args. / Формирует аргументы kubectl для объекта.

        Args:
            kind: Kubernetes kind/resource.
            namespace: Object namespace, empty for cluster-scoped objects.
            name: Object name.
        Returns:
            kubectl argument list for the selected object.
        """
        resource = kind.lower()
        args = [resource, name]
        if namespace and resource not in ("node", "nodes", "namespace", "namespaces"):
            args.extend(["-n", namespace])
        return args

    def describe_object(self, kind: str, namespace: str, name: str) -> List[str]:
        """Run ``kubectl describe`` for one object. / Выполняет ``kubectl describe`` для объекта.

        Args:
            kind: Kubernetes kind/resource.
            namespace: Object namespace, empty for cluster-scoped objects.
            name: Object name.
        Returns:
            Describe output lines.
        Raises:
            DataError: If kubectl describe fails.
        """
        return self.run(["describe"] + self.object_args(kind, namespace, name), timeout=max(self.args.command_timeout, 20.0)).splitlines()

    def yaml_object(self, kind: str, namespace: str, name: str) -> List[str]:
        """Run ``kubectl get -o yaml`` for one object. / Выполняет ``kubectl get -o yaml`` для объекта.

        Args:
            kind: Kubernetes kind/resource.
            namespace: Object namespace, empty for cluster-scoped objects.
            name: Object name.
        Returns:
            YAML output lines.
        Raises:
            DataError: If kubectl get fails.
        """
        return self.run(["get"] + self.object_args(kind, namespace, name) + ["-o", "yaml"], timeout=max(self.args.command_timeout, 20.0)).splitlines()

    def get_logs(
        self,
        namespace: str,
        pod_name: str,
        container_name: str,
        tail: int,
        timestamps: bool,
        previous: bool = False,
    ) -> List[str]:
        """Load pod logs through kubectl. / Загружает logs pod через kubectl.

        Args:
            namespace: Pod namespace.
            pod_name: Pod name.
            container_name: Container name.
            tail: Number of tail lines.
            timestamps: Whether kubectl should include timestamps.
            previous: Whether to read previous container logs.
        Returns:
            Log lines.
        Raises:
            DataError: If kubectl logs fails.
        """
        args = ["logs", "-n", namespace, pod_name, "-c", container_name, "--tail", str(tail)]
        if timestamps:
            args.append("--timestamps")
        if previous:
            args.append("--previous")
        text = self.run(args, timeout=max(self.args.command_timeout, 20.0))
        return text.splitlines()


class DemoClient:
    """Synthetic client for offline demo/tests. / Синтетический клиент для demo/tests без Kubernetes."""

    def __init__(self, args: argparse.Namespace) -> None:
        """Initialize demo clock and arguments. / Инициализирует demo clock и аргументы.

        Args:
            args: Parsed CLI arguments.
        """
        self.args = args
        self.started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=34, hours=6)

    def load_snapshot(self) -> ClusterSnapshot:
        """Build a synthetic cluster snapshot. / Строит синтетический снимок кластера.

        Returns:
            Demo ClusterSnapshot with deterministic objects and metrics.
        """
        nodes_json, pods_json, deployments_json, namespaces_json, resourcequotas_json, limitranges_json, pv_json, pvc_json, events_json = demo_json(self.started)
        replicasets_json = {
            "items": [
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "web-5d77b679d9",
                        "ownerReferences": [{"kind": "Deployment", "name": "web", "controller": True}],
                    },
                    "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "web"}}},
                    "status": {"readyReplicas": 1, "fullyLabeledReplicas": 1, "availableReplicas": 1},
                },
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "api-7bf6b99795",
                        "ownerReferences": [{"kind": "Deployment", "name": "api", "controller": True}],
                    },
                    "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "api"}}},
                    "status": {"readyReplicas": 1, "fullyLabeledReplicas": 1, "availableReplicas": 1},
                },
                {
                    "metadata": {
                        "namespace": "kube-system",
                        "name": "coredns-668d6bf9bc",
                        "ownerReferences": [{"kind": "Deployment", "name": "coredns", "controller": True}],
                    },
                    "spec": {"replicas": 1, "selector": {"matchLabels": {"k8s-app": "kube-dns"}}},
                    "status": {"readyReplicas": 1, "fullyLabeledReplicas": 1, "availableReplicas": 1},
                },
            ]
        }
        empty_workloads = {"items": []}
        now = dt.datetime.now(dt.timezone.utc)
        last_cron_slot = now.replace(second=0, microsecond=0) - dt.timedelta(minutes=now.minute % 15)
        cronjobs_json = {
            "items": [
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "nightly-backup",
                        "creationTimestamp": (now - dt.timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
                    },
                    "spec": {"schedule": "*/15 * * * *", "successfulJobsHistoryLimit": 3, "failedJobsHistoryLimit": 1},
                    "status": {
                        "lastScheduleTime": last_cron_slot.isoformat().replace("+00:00", "Z"),
                        "lastSuccessfulTime": last_cron_slot.isoformat().replace("+00:00", "Z"),
                    },
                }
            ]
        }
        jobs_json = {
            "items": [
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "nightly-backup-001",
                        "creationTimestamp": (last_cron_slot - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                        "ownerReferences": [{"apiVersion": "batch/v1", "kind": "CronJob", "name": "nightly-backup", "controller": True}],
                    },
                    "spec": {"completions": 1, "parallelism": 1},
                    "status": {
                        "startTime": (last_cron_slot - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                        "completionTime": last_cron_slot.isoformat().replace("+00:00", "Z"),
                        "succeeded": 1,
                        "conditions": [{"type": "Complete", "status": "True", "lastTransitionTime": last_cron_slot.isoformat().replace("+00:00", "Z")}],
                    },
                },
                {
                    "metadata": {
                        "namespace": "default",
                        "name": "nightly-backup-000",
                        "creationTimestamp": (last_cron_slot - dt.timedelta(minutes=18)).isoformat().replace("+00:00", "Z"),
                        "ownerReferences": [{"apiVersion": "batch/v1", "kind": "CronJob", "name": "nightly-backup", "controller": True}],
                    },
                    "spec": {"completions": 1, "parallelism": 1},
                    "status": {
                        "startTime": (last_cron_slot - dt.timedelta(minutes=18)).isoformat().replace("+00:00", "Z"),
                        "completionTime": (last_cron_slot - dt.timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
                        "succeeded": 1,
                        "conditions": [{"type": "Complete", "status": "True", "lastTransitionTime": (last_cron_slot - dt.timedelta(minutes=15)).isoformat().replace("+00:00", "Z")}],
                    },
                },
            ]
        }
        pods_json["items"].append(
            {
                "metadata": {
                    "namespace": "default",
                    "name": "nightly-backup-001-pod",
                    "creationTimestamp": (last_cron_slot - dt.timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                    "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": "nightly-backup-001", "controller": True}],
                },
                "spec": {
                    "nodeName": "worker-a",
                    "containers": [
                        {
                            "name": "backup",
                            "image": "registry.local/backup:demo",
                            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "512Mi"}},
                        }
                    ],
                },
                "status": {
                    "phase": "Succeeded",
                    "podIP": "10.244.1.55",
                    "conditions": [
                        {"type": "Initialized", "status": "True", "reason": "PodCompleted"},
                        {"type": "Ready", "status": "False", "reason": "PodCompleted"},
                        {"type": "PodScheduled", "status": "True", "reason": "Scheduled"},
                    ],
                    "containerStatuses": [
                        {
                            "name": "backup",
                            "ready": False,
                            "restartCount": 0,
                            "state": {"terminated": {"reason": "Completed"}},
                        }
                    ],
                },
            }
        )
        events_json["items"].append(
            {
                "metadata": {"namespace": "default", "creationTimestamp": now.isoformat().replace("+00:00", "Z")},
                "involvedObject": {"kind": "CronJob", "namespace": "default", "name": "nightly-backup"},
                "reason": "SawCompletedJob",
                "type": "Normal",
                "message": "Demo CronJob completed successfully",
            }
        )
        node_metrics = {
            "minikube": ResourceUsage(239.0, parse_bytes("1502Mi"), parse_bytes("1.2Mi"), parse_bytes("420Ki"), parse_bytes("250Ki"), parse_bytes("80Ki")),
            "worker-a": ResourceUsage(680.0, parse_bytes("3800Mi"), parse_bytes("2.8Mi"), parse_bytes("1.1Mi"), parse_bytes("760Ki"), parse_bytes("140Ki")),
        }
        pod_metrics = {
            ("kube-system", "coredns-668d6bf9bc-mzvs6"): ResourceUsage(4.0, parse_bytes("57Mi")),
            ("kube-system", "etcd-minikube"): ResourceUsage(31.0, parse_bytes("90Mi")),
            ("kube-system", "kube-apiserver-minikube"): ResourceUsage(52.0, parse_bytes("291Mi")),
            ("default", "web-5d77b679d9-xbzqs"): ResourceUsage(126.0, parse_bytes("180Mi"), parse_bytes("940Ki"), parse_bytes("280Ki"), parse_bytes("92Ki"), parse_bytes("25Ki")),
            ("default", "api-7bf6b99795-pnn5q"): ResourceUsage(260.0, parse_bytes("420Mi"), parse_bytes("1.7Mi"), parse_bytes("530Ki"), parse_bytes("420Ki"), parse_bytes("70Ki")),
            ("default", "nightly-backup-001-pod"): ResourceUsage(18.0, parse_bytes("90Mi"), parse_bytes("120Ki"), parse_bytes("40Ki"), parse_bytes("14Ki"), parse_bytes("8Ki")),
        }
        container_metrics = {
            ("default", "web-5d77b679d9-xbzqs", "web"): ResourceUsage(126.0, parse_bytes("180Mi")),
            ("default", "api-7bf6b99795-pnn5q", "api"): ResourceUsage(260.0, parse_bytes("420Mi")),
            ("default", "nightly-backup-001-pod", "backup"): ResourceUsage(18.0, parse_bytes("90Mi")),
        }
        return build_snapshot(
            nodes_json,
            pods_json,
            deployments_json,
            replicasets_json,
            empty_workloads,
            empty_workloads,
            jobs_json,
            cronjobs_json,
            namespaces_json,
            resourcequotas_json,
            limitranges_json,
            pv_json,
            pvc_json,
            events_json,
            node_metrics,
            pod_metrics,
            container_metrics,
            None,
            "demo-minikube",
            "demo-user",
            "v1.32.0",
            "(all)" if self.args.all_namespaces else (self.args.namespace or "default"),
            "demo metrics",
            True,
            ["demo mode: data is synthetic"],
        )

    def diagnostics_lines(self) -> List[str]:
        """Return synthetic diagnostics. / Возвращает синтетическую диагностику.

        Returns:
            Demo diagnostics lines.
        """
        return [
            "Metrics / RBAC diagnostics",
            "Mode: demo",
            "",
            "OK     metrics.k8s.io nodes  demo data",
            "OK     metrics.k8s.io pods   demo data",
            "OK     kubelet node proxy    demo data",
            "OK     kubelet metrics       demo data",
            "OK     kubelet cadvisor      demo data",
        ]

    def describe_object(self, kind: str, namespace: str, name: str) -> List[str]:
        """Return synthetic describe text. / Возвращает синтетический describe text.

        Args:
            kind: Kubernetes kind/resource.
            namespace: Object namespace, empty for cluster-scoped objects.
            name: Object name.
        Returns:
            Demo describe output lines.
        """
        scope = "%s/%s" % (namespace, name) if namespace else name
        return [
            "Name:           %s" % name,
            "Namespace:      %s" % (namespace or "<cluster>"),
            "Kind:           %s" % kind,
            "Source:         demo",
            "",
            "Summary:",
            "  Synthetic describe output for %s %s." % (kind, scope),
            "  This page is read-only and mirrors kubectl describe navigation.",
            "",
            "Events:",
            "  Type    Reason     Age   From      Message",
            "  Normal  DemoReady  1m    ktop-py.py   Demo object is available",
        ]

    def yaml_object(self, kind: str, namespace: str, name: str) -> List[str]:
        """Return synthetic YAML text. / Возвращает синтетический YAML text.

        Args:
            kind: Kubernetes kind/resource.
            namespace: Object namespace, empty for cluster-scoped objects.
            name: Object name.
        Returns:
            Demo YAML output lines.
        """
        lines = [
            "apiVersion: v1",
            "kind: %s" % kind[:1].upper() + kind[1:],
            "metadata:",
            "  name: %s" % name,
        ]
        if namespace:
            lines.append("  namespace: %s" % namespace)
        lines.extend(
            [
                "  labels:",
                "    app.kubernetes.io/managed-by: ktop-py.py-demo",
                "spec: {}",
                "status:",
                "  phase: Demo",
            ]
        )
        return lines

    def get_logs(
        self,
        namespace: str,
        pod_name: str,
        container_name: str,
        tail: int,
        timestamps: bool,
        previous: bool = False,
    ) -> List[str]:
        """Return synthetic log lines. / Возвращает синтетические log lines.

        Args:
            namespace: Pod namespace.
            pod_name: Pod name.
            container_name: Container name.
            tail: Number of tail lines.
            timestamps: Whether to include timestamps.
            previous: Accepted for interface compatibility.
        Returns:
            Demo log lines.
        """
        base = []
        now = dt.datetime.now(dt.timezone.utc)
        for idx in range(max(tail, 20)):
            ts = (now - dt.timedelta(seconds=(tail - idx) * 3)).isoformat().replace("+00:00", "Z")
            prefix = "%s " % ts if timestamps else ""
            base.append(
                "%s%s/%s[%s]: demo log line %03d status=ok latency=%dms"
                % (prefix, namespace, pod_name, container_name, idx + 1, 10 + (idx % 17) * 3)
            )
        return base[-tail:]


def demo_json(started: dt.datetime) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create synthetic Kubernetes JSON objects. / Создает синтетические Kubernetes JSON объекты.

    Args:
        started: Cluster start time used for object ages.
    Returns:
        Nodes, pods, deployments, namespaces, PV, PVC, and events JSON objects.
    """
    def ts(delta: dt.timedelta) -> str:
        return (started + delta).isoformat().replace("+00:00", "Z")

    def node(name: str, ip: str, cpu: str, mem: str, storage: str, role_label: Optional[str] = None) -> Dict[str, Any]:
        labels = {"kubernetes.io/hostname": name}
        if role_label:
            labels["node-role.kubernetes.io/%s" % role_label] = ""
        return {
            "metadata": {"name": name, "creationTimestamp": ts(dt.timedelta(minutes=0)), "labels": labels},
            "spec": {"taints": []},
            "status": {
                "addresses": [{"type": "Hostname", "address": name}, {"type": "InternalIP", "address": ip}],
                "conditions": [
                    {"type": "MemoryPressure", "status": "False", "reason": "KubeletHasSufficientMemory"},
                    {"type": "DiskPressure", "status": "False", "reason": "KubeletHasNoDiskPressure"},
                    {"type": "PIDPressure", "status": "False", "reason": "KubeletHasSufficientPID"},
                    {"type": "Ready", "status": "True", "reason": "KubeletReady"},
                ],
                "allocatable": {"cpu": cpu, "memory": mem, "ephemeral-storage": storage},
                "images": [{"names": ["demo"], "sizeBytes": 1}],
                "nodeInfo": {
                    "kubeletVersion": "v1.32.0",
                    "osImage": "Demo Linux",
                    "kernelVersion": "6.8.0",
                    "containerRuntimeVersion": "containerd://1.7",
                    "architecture": "amd64",
                },
                "volumesInUse": [],
                "volumesAttached": [],
            },
        }

    def pod(
        namespace: str,
        name: str,
        node_name: str,
        ip: str,
        age_hours: int,
        cpu_req: str,
        mem_req: str,
        restarts: int = 0,
        status_phase: str = "Running",
        owner_kind: str = "",
        owner_name: str = "",
    ) -> Dict[str, Any]:
        ready = status_phase == "Running"
        owners = []
        if owner_kind and owner_name:
            owners.append({"apiVersion": "apps/v1", "kind": owner_kind, "name": owner_name, "controller": True})
        return {
            "metadata": {
                "namespace": namespace,
                "name": name,
                "creationTimestamp": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z"),
                "ownerReferences": owners,
            },
            "spec": {
                "nodeName": node_name,
                "volumes": [{"name": "config"}, {"name": "data"}],
                "containers": [
                    {
                        "name": "main",
                        "image": "registry.local/%s:demo" % name.split("-")[0],
                        "resources": {"requests": {"cpu": cpu_req, "memory": mem_req}, "limits": {"cpu": "1", "memory": "1Gi"}},
                        "ports": [{"containerPort": 8080, "protocol": "TCP"}],
                        "volumeMounts": [{"name": "config", "mountPath": "/config"}],
                    }
                ],
            },
            "status": {
                "phase": status_phase,
                "podIP": ip,
                "conditions": [
                    {"type": "Initialized", "status": "True", "reason": "PodCompleted"},
                    {"type": "Ready", "status": "True" if ready else "False", "reason": "ContainersReady" if ready else "ContainersNotReady"},
                    {"type": "PodScheduled", "status": "True", "reason": "Scheduled"},
                ],
                "containerStatuses": [
                    {
                        "name": "main",
                        "ready": ready,
                        "restartCount": restarts,
                        "state": {"running": {"startedAt": ts(dt.timedelta(hours=1))}} if ready else {"waiting": {"reason": status_phase}},
                    }
                ],
            },
        }

    nodes = {
        "items": [
            node("minikube", "192.168.49.2", "6000m", "15Gi", "78Gi", "control-plane"),
            node("worker-a", "192.168.49.3", "4000m", "8Gi", "60Gi", None),
        ]
    }
    pods = {
        "items": [
            pod("kube-system", "coredns-668d6bf9bc-mzvs6", "minikube", "10.244.0.87", 34 * 24, "100m", "70Mi", 5, owner_kind="ReplicaSet", owner_name="coredns-668d6bf9bc"),
            pod("kube-system", "etcd-minikube", "minikube", "192.168.49.2", 34 * 24, "100m", "128Mi", 5),
            pod("kube-system", "kube-apiserver-minikube", "minikube", "192.168.49.2", 34 * 24, "250m", "256Mi", 5),
            pod("default", "web-5d77b679d9-xbzqs", "worker-a", "10.244.1.23", 17, "300m", "256Mi", 1, owner_kind="ReplicaSet", owner_name="web-5d77b679d9"),
            pod("default", "api-7bf6b99795-pnn5q", "worker-a", "10.244.1.41", 12, "500m", "512Mi", 0, owner_kind="ReplicaSet", owner_name="api-7bf6b99795"),
        ]
    }
    deployments = {
        "items": [
            {
                "metadata": {"namespace": "default", "name": "web", "labels": {"app": "web"}},
                "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "web"}}, "strategy": {"type": "RollingUpdate"}},
                "status": {"readyReplicas": 1, "updatedReplicas": 1, "availableReplicas": 1},
            },
            {
                "metadata": {"namespace": "default", "name": "api", "labels": {"app": "api"}},
                "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "api"}}, "strategy": {"type": "RollingUpdate"}},
                "status": {"readyReplicas": 1, "updatedReplicas": 1, "availableReplicas": 1},
            },
            {
                "metadata": {"namespace": "kube-system", "name": "coredns", "labels": {"k8s-app": "kube-dns"}},
                "spec": {"replicas": 1, "selector": {"matchLabels": {"k8s-app": "kube-dns"}}, "strategy": {"type": "RollingUpdate"}},
                "status": {"readyReplicas": 1, "updatedReplicas": 1, "availableReplicas": 1},
            },
        ]
    }
    namespaces = {"items": [{"metadata": {"name": n}} for n in ["default", "kube-system", "monitoring", "storage"]]}
    resourcequotas = {
        "items": [
            {
                "metadata": {"namespace": "default", "name": "compute"},
                "status": {
                    "hard": {"requests.cpu": "1200m", "requests.memory": "1Gi", "limits.cpu": "3", "limits.memory": "3Gi", "pods": "10"},
                    "used": {"requests.cpu": "800m", "requests.memory": "768Mi", "limits.cpu": "2", "limits.memory": "2Gi", "pods": "2"},
                },
            }
        ]
    }
    limitranges = {
        "items": [
            {
                "metadata": {"namespace": "default", "name": "container-defaults"},
                "spec": {
                    "limits": [
                        {
                            "type": "Container",
                            "defaultRequest": {"cpu": "100m", "memory": "128Mi"},
                            "default": {"cpu": "500m", "memory": "512Mi"},
                        }
                    ]
                },
            }
        ]
    }
    pv = {"items": [{"spec": {"capacity": {"storage": "200Gi"}}}, {"spec": {"capacity": {"storage": "200Gi"}}}]}
    pvc = {"items": [{"status": {"capacity": {"storage": "20Gi"}}}, {"status": {"capacity": {"storage": "10Gi"}}}]}
    events = {
        "items": [
            {
                "metadata": {"namespace": "default", "creationTimestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")},
                "involvedObject": {"kind": "Pod", "namespace": "default", "name": "web-5d77b679d9-xbzqs"},
                "reason": "Pulled",
                "type": "Normal",
                "message": "Container image already present on machine",
            },
            {
                "metadata": {"namespace": "", "creationTimestamp": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")},
                "involvedObject": {"kind": "Node", "name": "minikube"},
                "reason": "NodeReady",
                "type": "Normal",
                "message": "Node minikube status is now: NodeReady",
            },
        ]
    }
    return nodes, pods, deployments, namespaces, resourcequotas, limitranges, pv, pvc, events


def status_rank(status: str) -> int:
    order = {
        "OK": 0,
        "Active": 0,
        "Idle": 0,
        "Ready": 0,
        "Running": 0,
        "Completed": 1,
        "Complete": 1,
        "NotReady": 2,
        "Suspended": 2,
        "Slow": 2,
        "LongRunning": 2,
        "Pending": 3,
        "ContainerCreating": 3,
        "Terminating": 4,
        "CrashLoopBackOff": 5,
        "Error": 6,
        "Failed": 7,
        "Missed": 7,
        "Unknown": 8,
    }
    return order.get(status, 9)


def sort_nodes(nodes: List[NodeRow], column: str, ascending: bool) -> List[NodeRow]:
    """Sort node rows by UI column. / Сортирует node rows по UI-колонке.

    Args:
        nodes: Node rows.
        column: Column name.
        ascending: Sort direction.
    Returns:
        Sorted node rows.
    """
    def key(node: NodeRow) -> Any:
        mapping = {
            "NAME": (node.name,),
            "STATUS": (status_rank(node.status), node.name),
            "RST": (node.restarts, node.name),
            "PODS": (node.pods_count, node.name),
            "TAINTS": (node.taints, node.name),
            "PRESSURE": (len(node.pressures), node.name),
            "IP": (node.internal_ip, node.name),
            "VOLS": (node.volumes_in_use, node.volumes_attached, node.name),
            "DISK": (node.alloc_storage_b, node.name),
            "CPU": ((node.usage_cpu_m or node.requested_cpu_m), node.name),
            "MEM": ((node.usage_mem_b or node.requested_mem_b), node.name),
            "NET": (node.net_rx_bps + node.net_tx_bps, node.name),
            "IO": (node.fs_read_bps + node.fs_write_bps, node.name),
            "NET RX": (node.net_rx_bps, node.name),
            "NET TX": (node.net_tx_bps, node.name),
            "DISK R": (node.fs_read_bps, node.name),
            "DISK W": (node.fs_write_bps, node.name),
        }
        return mapping.get(column, (node.name,))

    return sorted(nodes, key=key, reverse=not ascending)


def sort_pods(pods: List[PodRow], column: str, ascending: bool) -> List[PodRow]:
    """Sort pod rows by UI column. / Сортирует pod rows по UI-колонке.

    Args:
        pods: Pod rows.
        column: Column name.
        ascending: Sort direction.
    Returns:
        Sorted pod rows.
    """
    def key(pod: PodRow) -> Any:
        ready_ratio = float(pod.ready) / float(pod.total or 1)
        mapping = {
            "NAMESPACE": (pod.namespace, pod.name),
            "POD": (pod.name, pod.namespace),
            "READY": (ready_ratio, pod.name),
            "STATUS": (status_rank(pod.status), pod.name),
            "RST": (pod.restarts, pod.name),
            "AGE": (pod.creation_time or dt.datetime.now(dt.timezone.utc), pod.name),
            "VOLS": (pod.volumes, pod.mounts, pod.name),
            "IP": (pod.ip, pod.name),
            "NODE": (pod.node, pod.name),
            "CPU": ((pod.usage_cpu_m or pod.requested_cpu_m), pod.name),
            "MEMORY": ((pod.usage_mem_b or pod.requested_mem_b), pod.name),
        }
        return mapping.get(column, (pod.namespace, pod.name))

    return sorted(pods, key=key, reverse=not ascending)


def aggregate_histories(histories: Sequence[Sequence[float]]) -> List[float]:
    """Sum right-aligned metric histories. / Суммирует выровненные справа истории метрик.

    Args:
        histories: Per-object metric histories.
    Returns:
        Aggregated history with newest samples aligned by position.
    """
    clean_histories: List[List[float]] = []
    for history in histories:
        clean = clean_metric_values(history)
        if clean:
            clean_histories.append(clean)
    if not clean_histories:
        return []
    max_len = max(len(history) for history in clean_histories)
    result: List[float] = []
    for offset in range(max_len, 0, -1):
        total = 0.0
        for history in clean_histories:
            if len(history) >= offset:
                total += history[-offset]
        result.append(total)
    return result


def sort_namespaces(namespaces: List[NamespaceRow], column: str, ascending: bool) -> List[NamespaceRow]:
    """Sort namespace aggregate rows. / Сортирует агрегированные строки namespace.

    Args:
        namespaces: Namespace rows.
        column: Column name.
        ascending: Sort direction.
    Returns:
        Sorted namespace rows.
    """
    def key(namespace: NamespaceRow) -> Any:
        ready_ratio = float(namespace.ready) / float(namespace.total or 1)
        mapping = {
            "NAMESPACE": (namespace.name,),
            "STATUS": (status_rank(namespace.status), namespace.name),
            "PODS": (namespace.pods_count, namespace.name),
            "READY": (ready_ratio, namespace.name),
            "RST": (namespace.restarts, namespace.name),
            "FAIL": (namespace.failures, namespace.name),
            "CPU": ((namespace.usage_cpu_m or namespace.requested_cpu_m), namespace.name),
            "MEMORY": ((namespace.usage_mem_b or namespace.requested_mem_b), namespace.name),
            "NET": (namespace.net_rx_bps + namespace.net_tx_bps, namespace.name),
            "IO": (namespace.fs_read_bps + namespace.fs_write_bps, namespace.name),
            "NET RX": (namespace.net_rx_bps, namespace.name),
            "NET TX": (namespace.net_tx_bps, namespace.name),
            "DISK R": (namespace.fs_read_bps, namespace.name),
            "DISK W": (namespace.fs_write_bps, namespace.name),
        }
        return mapping.get(column, (namespace.name,))

    return sorted(namespaces, key=key, reverse=not ascending)


def sort_cronjobs(rows: List[CronJobRow], column: str, ascending: bool) -> List[CronJobRow]:
    """Sort CronJob diagnostic rows. / Сортирует строки диагностики CronJob.

    Args:
        rows: CronJob rows.
        column: Column name.
        ascending: Sort direction.
    Returns:
        Sorted rows.
    """
    min_time = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def key(row: CronJobRow) -> Any:
        mapping = {
            "NAMESPACE": (row.namespace, row.name),
            "NAME": (row.name, row.namespace),
            "SCHEDULE": (row.schedule, row.namespace, row.name),
            "TZ": (row.timezone, row.namespace, row.name),
            "SUSP": (row.suspend, row.namespace, row.name),
            "LAST": (row.last_schedule or min_time, row.namespace, row.name),
            "NEXT": (row.next_schedule or min_time, row.namespace, row.name),
            "LATE": (row.late_seconds, row.namespace, row.name),
            "ACTIVE": (row.active, row.namespace, row.name),
            "OK": (row.succeeded, row.namespace, row.name),
            "FAIL": (row.failed, row.namespace, row.name),
            "P50": (row.p50_s or -1.0, row.namespace, row.name),
            "P95": (row.p95_s or -1.0, row.namespace, row.name),
            "P99": (row.p99_s or -1.0, row.namespace, row.name),
            "STATUS": (status_rank(row.status), row.namespace, row.name),
            "HINT": (row.hint, row.namespace, row.name),
        }
        return mapping.get(column, (row.namespace, row.name))

    return sorted(rows, key=key, reverse=not ascending)


def match_text(needles: Sequence[str], query: str) -> bool:
    if not query:
        return True
    query = query.lower()
    return any(query in str(value).lower() for value in needles)


def cronjob_filter_values(row: CronJobRow) -> List[str]:
    """Return searchable CronJob row fields. / Возвращает searchable поля CronJob."""
    return [
        row.namespace,
        row.name,
        row.schedule,
        row.timezone,
        row.status,
        row.hint,
        row.latest_job,
        row.latest_status,
    ]


def node_filter_values(node: NodeRow) -> List[str]:
    return [
        node.name,
        node.status,
        str(node.restarts),
        str(node.pods_count),
        str(node.taints),
        ",".join(node.pressures) or "none",
        node.internal_ip,
        node.external_ip,
        ",".join(node.roles),
    ]


def pod_filter_values(pod: PodRow) -> List[str]:
    return [pod.namespace, pod.name, pod.status, pod.ip, pod.node, str(pod.restarts)]


def namespace_filter_values(namespace: NamespaceRow) -> List[str]:
    return [
        namespace.name,
        namespace.status,
        str(namespace.pods_count),
        str(namespace.restarts),
        str(namespace.failures),
    ]


def csv_values(raw: Any) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def clean_metric_values(values: Sequence[float]) -> List[float]:
    clean = []
    for value in values:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            clean.append(max(0.0, numeric))
    return clean


def dump_current_value(usage: float, fallback: float, history: Sequence[float], metrics_available: bool = True) -> float:
    """Choose current value for dump output. / Выбирает current значение для dump.

    Args:
        usage: Live usage value.
        fallback: Request/allocatable fallback value.
        history: Retained metric history.
        metrics_available: Whether live metrics are connected.
    Returns:
        Live usage when metrics exist; fallback only when metrics are unavailable.
    """
    if metrics_available or history:
        return max(0.0, float(usage or 0.0))
    return max(0.0, float(usage or fallback or 0.0))


def dump_sample_count(args: Optional[argparse.Namespace]) -> int:
    """Resolve dump max-value sample window. / Определяет окно samples для max в dump.

    Args:
        args: Parsed CLI args or None.
    Returns:
        Number of recent samples to inspect.
    """
    graph_width = max(1, int(getattr(args, "dump_graph_width", DEFAULT_DUMP_GRAPH_WIDTH) or DEFAULT_DUMP_GRAPH_WIDTH))
    interval = float(getattr(args, "dump_max_interval", 0.0) or 0.0)
    if interval <= 0:
        return graph_width
    refresh = max(0.001, float(getattr(args, "refresh_interval", DEFAULT_REFRESH_SECONDS) or DEFAULT_REFRESH_SECONDS))
    return max(1, int(math.ceil(interval / refresh)))


def dump_metric_max(history: Sequence[float], current: float, args: Optional[argparse.Namespace] = None) -> float:
    """Return max metric over dump window. / Возвращает максимум метрики за dump-окно.

    Args:
        history: Retained values.
        current: Current value, always included.
        args: Parsed CLI args controlling the window.
    Returns:
        Maximum non-negative value.
    """
    count = dump_sample_count(args)
    window = clean_metric_values(history)[-count:]
    values = window + [max(0.0, float(current or 0.0))]
    return max(values) if values else 0.0


def json_metric(value: float) -> Any:
    numeric = max(0.0, float(value or 0.0))
    if not math.isfinite(numeric):
        numeric = 0.0
    rounded = round(numeric, 6)
    if abs(rounded - round(rounded)) < 0.000001:
        return int(round(rounded))
    return rounded


def dump_metric_object(current: float, history: Sequence[float], args: Optional[argparse.Namespace], total: float = 0.0) -> Dict[str, Any]:
    maximum = dump_metric_max(history, current, args)
    result: Dict[str, Any] = {
        "current": json_metric(current),
        "max": json_metric(maximum),
    }
    if total and total > 0:
        result["current_pct"] = round(ratio(current, total) * 100.0, 3)
        result["max_pct"] = round(ratio(maximum, total) * 100.0, 3)
    return result


def dump_node_cpu(node: NodeRow, metrics_available: bool = True) -> float:
    return dump_current_value(node.usage_cpu_m, node.requested_cpu_m, node.cpu_history, metrics_available)


def dump_node_mem(node: NodeRow, metrics_available: bool = True) -> float:
    return dump_current_value(node.usage_mem_b, node.requested_mem_b, node.mem_history, metrics_available)


def dump_pod_cpu(pod: PodRow, metrics_available: bool = True) -> float:
    return dump_current_value(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history, metrics_available)


def dump_pod_mem(pod: PodRow, metrics_available: bool = True) -> float:
    return dump_current_value(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history, metrics_available)


def dump_container_cpu(container: ContainerInfo, metrics_available: bool = True) -> float:
    return dump_current_value(container.usage_cpu_m, container.cpu_request_m, container.cpu_history, metrics_available)


def dump_container_mem(container: ContainerInfo, metrics_available: bool = True) -> float:
    return dump_current_value(container.usage_mem_b, container.mem_request_b, container.mem_history, metrics_available)


def dump_pod_problem(pod: PodRow) -> bool:
    """Detect whether a pod is interesting for problems dump. / Определяет pod для problems dump.

    Args:
        pod: Pod row.
    Returns:
        True for unhealthy pods or pods with restarts.
    """
    healthy_statuses = {"Running", "Succeeded", "Completed"}
    if pod.status not in healthy_statuses:
        return True
    if pod.total and pod.ready < pod.total:
        return True
    if pod.restarts > 0:
        return True
    for container in pod.containers:
        if container.restarts > 0:
            return True
        if pod.status == "Running" and not container.ready:
            return True
        if container.status not in ("Running", "Completed", "Terminated"):
            return True
    return False


def dump_pod_matches_filter(pod: PodRow, query: str) -> bool:
    values = pod_filter_values(pod)
    values.append(owner_chain_text(pod.owner_chain))
    values.extend("%s %s %s" % (container.name, container.status, container.image) for container in pod.containers)
    return match_text(values, query)


def dump_pod_namespaces(args: Optional[argparse.Namespace]) -> List[str]:
    """Resolve namespace filter for pod dump. / Определяет namespace-фильтр для dump pod.

    Args:
        args: Parsed CLI args or None.
    Returns:
        Exact namespaces to include, or an empty list for all namespaces.
    """
    if args is None:
        return []
    namespaces = csv_values(getattr(args, "dump_pod_namespaces", ""))
    if not namespaces and not getattr(args, "all_namespaces", False) and getattr(args, "namespace", None):
        namespaces = [str(getattr(args, "namespace"))]
    return namespaces


def select_dump_pods(snapshot: ClusterSnapshot, args: Optional[argparse.Namespace]) -> List[PodRow]:
    """Select pod rows for dump output. / Выбирает pod rows для dump-вывода.

    Args:
        snapshot: Current cluster snapshot.
        args: Parsed CLI args with dump filters.
    Returns:
        Filtered, sorted, and limited pod rows.
    """
    mode = getattr(args, "dump_pods", "all") or "all"
    pods = list(snapshot.pods)
    namespaces = set(dump_pod_namespaces(args))
    if namespaces:
        pods = [pod for pod in pods if pod.namespace in namespaces]
    query = str(getattr(args, "dump_pod_filter", "") or "").strip()
    if query:
        pods = [pod for pod in pods if dump_pod_matches_filter(pod, query)]

    if mode == "none":
        pods = []
    elif mode == "problems":
        pods = [pod for pod in pods if dump_pod_problem(pod)]
        pods = sort_pods(pods, "NAMESPACE", True)
    elif mode == "top-cpu":
        pods = sorted(pods, key=lambda pod: (dump_pod_cpu(pod, snapshot.metrics_available), pod.namespace, pod.name), reverse=True)
    elif mode == "top-mem":
        pods = sorted(pods, key=lambda pod: (dump_pod_mem(pod, snapshot.metrics_available), pod.namespace, pod.name), reverse=True)
    else:
        pods = sort_pods(pods, "NAMESPACE", True)

    limit = int(getattr(args, "dump_pod_limit", 0) or 0)
    if limit > 0:
        pods = pods[:limit]
    return pods


def dump_usage_json(
    cpu_current: float,
    cpu_history: Sequence[float],
    mem_current: float,
    mem_history: Sequence[float],
    args: Optional[argparse.Namespace],
    cpu_total: float = 0.0,
    mem_total: float = 0.0,
) -> Dict[str, Any]:
    """Build CPU/MEM JSON usage object. / Строит JSON-объект CPU/MEM usage.

    Args:
        cpu_current: Current CPU millicores.
        cpu_history: CPU history values.
        mem_current: Current memory bytes.
        mem_history: Memory history values.
        args: Parsed CLI args controlling max window.
        cpu_total: Optional CPU denominator for percentages.
        mem_total: Optional memory denominator for percentages.
    Returns:
        JSON-ready dict with current and max values.
    """
    return {
        "cpu_m": dump_metric_object(cpu_current, cpu_history, args, cpu_total),
        "memory_bytes": dump_metric_object(mem_current, mem_history, args, mem_total),
    }


def dump_rate_json(
    rx_current: float,
    tx_current: float,
    total_history: Sequence[float],
    args: Optional[argparse.Namespace],
    read_label: str,
    write_label: str,
    total_label: str,
) -> Dict[str, Any]:
    """Build RX/TX or read/write JSON rate object. / Строит JSON rate object для RX/TX или read/write.

    Args:
        rx_current: Current receive/read rate.
        tx_current: Current transmit/write rate.
        total_history: Total-rate history.
        args: Parsed CLI args controlling max window.
        read_label: JSON key for first rate.
        write_label: JSON key for second rate.
        total_label: JSON key for total current/max object.
    Returns:
        JSON-ready rate object.
    """
    total_current = max(0.0, float(rx_current or 0.0)) + max(0.0, float(tx_current or 0.0))
    return {
        read_label: json_metric(rx_current),
        write_label: json_metric(tx_current),
        total_label: dump_metric_object(total_current, total_history, args),
    }


def dump_owner_chain_json(chain: Sequence[Tuple[str, str]]) -> List[Dict[str, str]]:
    return [{"kind": kind, "name": name} for kind, name in chain]


def dump_conditions_json(conditions: Sequence[Tuple[str, str, str]]) -> List[Dict[str, str]]:
    return [{"type": name, "status": status, "reason": reason} for name, status, reason in conditions]


def dump_container_json(container: ContainerInfo, args: Optional[argparse.Namespace], metrics_available: bool) -> Dict[str, Any]:
    """Serialize a container row for JSON dump. / Сериализует container row для JSON dump.

    Args:
        container: Container row.
        args: Parsed CLI args controlling max window.
        metrics_available: Whether live metrics are connected.
    Returns:
        JSON-ready container object.
    """
    cpu_current = dump_container_cpu(container, metrics_available)
    mem_current = dump_container_mem(container, metrics_available)
    return {
        "name": container.name,
        "image": container.image,
        "state": container.status,
        "ready": container.ready,
        "restarts": container.restarts,
        "ports": container.ports,
        "mounts": container.mounts,
        "resources": {
            "requests": {"cpu_m": json_metric(container.cpu_request_m), "memory_bytes": json_metric(container.mem_request_b)},
            "limits": {"cpu_m": json_metric(container.cpu_limit_m), "memory_bytes": json_metric(container.mem_limit_b)},
        },
        "usage": dump_usage_json(cpu_current, container.cpu_history, mem_current, container.mem_history, args),
    }


def dump_node_json(node: NodeRow, args: Optional[argparse.Namespace], include_raw: bool, metrics_available: bool) -> Dict[str, Any]:
    """Serialize a node row for JSON dump. / Сериализует node row для JSON dump.

    Args:
        node: Node row.
        args: Parsed CLI args controlling max window.
        include_raw: Whether to include the raw Kubernetes object.
        metrics_available: Whether live metrics are connected.
    Returns:
        JSON-ready node object.
    """
    cpu_current = dump_node_cpu(node, metrics_available)
    mem_current = dump_node_mem(node, metrics_available)
    result: Dict[str, Any] = {
        "name": node.name,
        "status": node.status,
        "roles": node.roles,
        "controller": node.controller,
        "hostname": node.hostname,
        "ip": {"internal": node.internal_ip, "external": node.external_ip},
        "created_at": isoformat_utc(node.creation_time),
        "pods": node.pods_count,
        "images": node.images_count,
        "volumes": {"in_use": node.volumes_in_use, "attached": node.volumes_attached},
        "taints": node.taints,
        "unschedulable": node.unschedulable,
        "restarts": node.restarts,
        "system": {
            "kubelet": node.kubelet,
            "os_image": node.os_image,
            "kernel": node.kernel,
            "runtime": node.runtime,
            "arch": node.arch,
        },
        "allocatable": {
            "cpu_m": json_metric(node.alloc_cpu_m),
            "memory_bytes": json_metric(node.alloc_mem_b),
            "storage_bytes": json_metric(node.alloc_storage_b),
        },
        "requested": {
            "cpu_m": json_metric(node.requested_cpu_m),
            "memory_bytes": json_metric(node.requested_mem_b),
        },
        "usage": dump_usage_json(cpu_current, node.cpu_history, mem_current, node.mem_history, args, node.alloc_cpu_m, node.alloc_mem_b),
        "network": dump_rate_json(node.net_rx_bps, node.net_tx_bps, node.net_history, args, "rx_bps", "tx_bps", "total_bps"),
        "io": dump_rate_json(node.fs_read_bps, node.fs_write_bps, node.io_history, args, "read_bps", "write_bps", "total_bps"),
        "pressures": node.pressures,
        "conditions": dump_conditions_json(node.conditions),
    }
    if include_raw:
        result["raw"] = node.raw
    return result


def dump_pod_json(pod: PodRow, args: Optional[argparse.Namespace], include_raw: bool, metrics_available: bool) -> Dict[str, Any]:
    """Serialize a pod row for JSON dump. / Сериализует pod row для JSON dump.

    Args:
        pod: Pod row.
        args: Parsed CLI args controlling max window.
        include_raw: Whether to include the raw Kubernetes object.
        metrics_available: Whether live metrics are connected.
    Returns:
        JSON-ready pod object.
    """
    cpu_current = dump_pod_cpu(pod, metrics_available)
    mem_current = dump_pod_mem(pod, metrics_available)
    result: Dict[str, Any] = {
        "namespace": pod.namespace,
        "name": pod.name,
        "status": pod.status,
        "node": pod.node,
        "ip": pod.ip,
        "created_at": isoformat_utc(pod.creation_time),
        "ready": {"ready": pod.ready, "total": pod.total},
        "restarts": pod.restarts,
        "volumes": pod.volumes,
        "mounts": pod.mounts,
        "owners": dump_owner_chain_json(pod.owner_chain or pod.owners),
        "resources": {
            "requests": {"cpu_m": json_metric(pod.requested_cpu_m), "memory_bytes": json_metric(pod.requested_mem_b)},
            "node_allocatable": {"cpu_m": json_metric(pod.node_alloc_cpu_m), "memory_bytes": json_metric(pod.node_alloc_mem_b)},
        },
        "usage": dump_usage_json(cpu_current, pod.cpu_history, mem_current, pod.mem_history, args, pod.node_alloc_cpu_m, pod.node_alloc_mem_b),
        "network": dump_rate_json(pod.net_rx_bps, pod.net_tx_bps, pod.net_history, args, "rx_bps", "tx_bps", "total_bps"),
        "io": dump_rate_json(pod.fs_read_bps, pod.fs_write_bps, pod.io_history, args, "read_bps", "write_bps", "total_bps"),
        "conditions": dump_conditions_json(pod.conditions),
        "containers": [dump_container_json(container, args, metrics_available) for container in pod.containers],
        "problem": dump_pod_problem(pod),
    }
    if include_raw:
        result["raw"] = pod.raw
    return result


def dump_cronjob_json(row: CronJobRow, include_raw: bool) -> Dict[str, Any]:
    """Serialize a CronJob diagnostic row. / Сериализует строку диагностики CronJob.

    Args:
        row: CronJob diagnostic row.
        include_raw: Whether to include the raw Kubernetes object.
    Returns:
        JSON-ready CronJob object.
    """
    result: Dict[str, Any] = {
        "namespace": row.namespace,
        "name": row.name,
        "schedule": row.schedule,
        "timezone": row.timezone,
        "suspend": row.suspend,
        "last_schedule": isoformat_utc(row.last_schedule),
        "last_success": isoformat_utc(row.last_success),
        "next_schedule": isoformat_utc(row.next_schedule),
        "late_seconds": json_metric(row.late_seconds),
        "active": row.active,
        "succeeded": row.succeeded,
        "failed": row.failed,
        "duration_percentiles_seconds": {
            "p50": json_metric(row.p50_s),
            "p95": json_metric(row.p95_s),
            "p99": json_metric(row.p99_s),
        },
        "latest_job": {"name": row.latest_job, "status": row.latest_status},
        "status": row.status,
        "severity": row.severity,
        "hint": row.hint,
        "suggestions": list(row.suggestions),
        "parse_error": row.parse_error,
    }
    if include_raw:
        result["raw"] = row.raw
    return result


def dump_snapshot_json(snapshot: ClusterSnapshot, args: Optional[argparse.Namespace] = None) -> str:
    """Render snapshot as stable JSON dump. / Рендерит snapshot как стабильный JSON dump.

    Args:
        snapshot: Cluster snapshot to serialize.
        args: Optional CLI args for pod selection and max window.
    Returns:
        Pretty-printed JSON string.
    """
    selected_pods = select_dump_pods(snapshot, args)
    include_raw = bool(getattr(args, "include_raw", False))
    cpu_total = sum(node.alloc_cpu_m for node in snapshot.nodes)
    mem_total = sum(node.alloc_mem_b for node in snapshot.nodes)
    cpu_used = sum(dump_node_cpu(node, snapshot.metrics_available) for node in snapshot.nodes)
    mem_used = sum(dump_node_mem(node, snapshot.metrics_available) for node in snapshot.nodes)
    net_rx = sum(node.net_rx_bps for node in snapshot.nodes)
    net_tx = sum(node.net_tx_bps for node in snapshot.nodes)
    io_read = sum(node.fs_read_bps for node in snapshot.nodes)
    io_write = sum(node.fs_write_bps for node in snapshot.nodes)
    cronjob_rows = sort_cronjobs(build_cronjob_rows(snapshot), "STATUS", True)
    payload = {
        "version": __VERSION__,
        "loaded_at": isoformat_utc(snapshot.loaded_at),
        "metrics_status": snapshot.metrics_status,
        "metrics_available": snapshot.metrics_available,
        "warnings": list(snapshot.warnings),
        "dump": {
            "output": "json",
            "pod_mode": getattr(args, "dump_pods", "all") if args is not None else "all",
            "pod_filter": getattr(args, "dump_pod_filter", "") if args is not None else "",
            "pod_namespaces": dump_pod_namespaces(args),
            "pod_limit": int(getattr(args, "dump_pod_limit", 0) or 0) if args is not None else 0,
            "pod_count": len(selected_pods),
            "pod_total": len(snapshot.pods),
            "max_interval_seconds": float(getattr(args, "dump_max_interval", 0.0) or 0.0) if args is not None else 0.0,
            "max_samples": dump_sample_count(args),
            "include_raw": include_raw,
        },
        "cluster": {
            "context": snapshot.context,
            "user": snapshot.user,
            "k8s_version": snapshot.k8s_version,
            "namespace": snapshot.namespace,
            "uptime_start": isoformat_utc(snapshot.uptime_start),
            "uptime": human_age(snapshot.uptime_start),
            "nodes": {"ready": sum(1 for node in snapshot.nodes if node.status == "Ready"), "total": len(snapshot.nodes)},
            "namespaces": snapshot.namespaces_count,
            "deployments": {"ready": snapshot.deployments_ready, "total": snapshot.deployments_total},
            "pods": {"running": sum(1 for pod in snapshot.pods if pod.status == "Running"), "total": len(snapshot.pods)},
            "pvs": {"count": snapshot.pv_count, "capacity_bytes": json_metric(snapshot.pv_capacity_b)},
            "pvcs": {"count": snapshot.pvc_count, "capacity_bytes": json_metric(snapshot.pvc_capacity_b)},
            "volumes_in_use": snapshot.volumes_in_use,
            "usage": dump_usage_json(cpu_used, snapshot.cluster_cpu_history, mem_used, snapshot.cluster_mem_history, args, cpu_total, mem_total),
            "network": dump_rate_json(net_rx, net_tx, snapshot.cluster_net_history, args, "rx_bps", "tx_bps", "total_bps"),
            "io": dump_rate_json(io_read, io_write, snapshot.cluster_io_history, args, "read_bps", "write_bps", "total_bps"),
        },
        "nodes": [dump_node_json(node, args, include_raw, snapshot.metrics_available) for node in sort_nodes(snapshot.nodes, "NAME", True)],
        "pods": [dump_pod_json(pod, args, include_raw, snapshot.metrics_available) for pod in selected_pods],
        "cronjobs": [dump_cronjob_json(row, include_raw) for row in cronjob_rows],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def dump_snapshot(snapshot: ClusterSnapshot, args: Optional[argparse.Namespace] = None) -> str:
    """Render snapshot as text dump. / Рендерит snapshot как текстовый dump.

    Args:
        snapshot: Cluster snapshot to serialize.
        args: Optional CLI args for pod selection and max window.
    Returns:
        Human-readable multiline text.
    """
    cpu_total = sum(n.alloc_cpu_m for n in snapshot.nodes)
    cpu_used = sum(dump_node_cpu(n, snapshot.metrics_available) for n in snapshot.nodes)
    mem_total = sum(n.alloc_mem_b for n in snapshot.nodes)
    mem_used = sum(dump_node_mem(n, snapshot.metrics_available) for n in snapshot.nodes)
    net_rx = sum(n.net_rx_bps for n in snapshot.nodes)
    net_tx = sum(n.net_tx_bps for n in snapshot.nodes)
    io_read = sum(n.fs_read_bps for n in snapshot.nodes)
    io_write = sum(n.fs_write_bps for n in snapshot.nodes)
    selected_pods = select_dump_pods(snapshot, args)
    lines = []
    lines.append("ktop-py.py %s" % __VERSION__)
    lines.append(
        "Context: %s | K8s: %s | User: %s | Namespace: %s | Metrics: %s"
        % (snapshot.context, snapshot.k8s_version, snapshot.user, snapshot.namespace, snapshot.metrics_status)
    )
    lines.append(
        "Summary: Uptime %s | Nodes %d | NS %d | Deploys %d/%d | Pods %d/%d | PVs %d (%s) | PVCs %d (%s)"
        % (
            human_age(snapshot.uptime_start),
            sum(1 for n in snapshot.nodes if n.status == "Ready"),
            snapshot.namespaces_count,
            snapshot.deployments_ready,
            snapshot.deployments_total,
            sum(1 for p in snapshot.pods if p.status == "Running"),
            len(snapshot.pods),
            snapshot.pv_count,
            format_bytes(snapshot.pv_capacity_b),
            snapshot.pvc_count,
            format_bytes(snapshot.pvc_capacity_b),
        )
    )
    lines.append(
        "CPU: %s/%s %.1f%% max=%s | MEM: %s/%s %.1f%% max=%s"
        % (
            format_mcpu(cpu_used),
            format_mcpu(cpu_total),
            ratio(cpu_used, cpu_total) * 100,
            format_mcpu(dump_metric_max(snapshot.cluster_cpu_history, cpu_used, args)),
            format_bytes(mem_used),
            format_bytes(mem_total),
            ratio(mem_used, mem_total) * 100,
            format_bytes(dump_metric_max(snapshot.cluster_mem_history, mem_used, args)),
        )
    )
    lines.append(
        "NET: rx=%s tx=%s max=%s | IO: read=%s write=%s max=%s"
        % (
            format_bytes_per_sec(net_rx),
            format_bytes_per_sec(net_tx),
            format_bytes_per_sec(dump_metric_max(snapshot.cluster_net_history, net_rx + net_tx, args)),
            format_bytes_per_sec(io_read),
            format_bytes_per_sec(io_write),
            format_bytes_per_sec(dump_metric_max(snapshot.cluster_io_history, io_read + io_write, args)),
        )
    )
    lines.append("")
    lines.append("Nodes:")
    for node in sort_nodes(snapshot.nodes, "NAME", True):
        node_cpu = dump_node_cpu(node, snapshot.metrics_available)
        node_mem = dump_node_mem(node, snapshot.metrics_available)
        lines.append(
            "  %-20s %-8s pods=%-3d cpu=%s(max %s)/%s mem=%s(max %s)/%s net=%s/%s(max %s) io=%s/%s(max %s) ip=%s"
            % (
                node.name,
                node.status,
                node.pods_count,
                format_mcpu(node_cpu),
                format_mcpu(dump_metric_max(node.cpu_history, node_cpu, args)),
                format_mcpu(node.alloc_cpu_m),
                format_bytes(node_mem),
                format_bytes(dump_metric_max(node.mem_history, node_mem, args)),
                format_bytes(node.alloc_mem_b),
                format_bytes_per_sec(node.net_rx_bps),
                format_bytes_per_sec(node.net_tx_bps),
                format_bytes_per_sec(dump_metric_max(node.net_history, node.net_rx_bps + node.net_tx_bps, args)),
                format_bytes_per_sec(node.fs_read_bps),
                format_bytes_per_sec(node.fs_write_bps),
                format_bytes_per_sec(dump_metric_max(node.io_history, node.fs_read_bps + node.fs_write_bps, args)),
                node.internal_ip,
            )
        )
    lines.append("")
    lines.append(
        "Pods: %d/%d selected (mode=%s)"
        % (len(selected_pods), len(snapshot.pods), getattr(args, "dump_pods", "all") if args is not None else "all")
    )
    for pod in selected_pods:
        pod_cpu = dump_pod_cpu(pod, snapshot.metrics_available)
        pod_mem = dump_pod_mem(pod, snapshot.metrics_available)
        lines.append(
            "  %-12s %-36s %-12s ready=%d/%d node=%s cpu=%s(max %s) mem=%s(max %s) net=%s/%s(max %s) io=%s/%s(max %s)"
            % (
                pod.namespace,
                truncate(pod.name, 36),
                pod.status,
                pod.ready,
                pod.total,
                pod.node,
                format_mcpu(pod_cpu),
                format_mcpu(dump_metric_max(pod.cpu_history, pod_cpu, args)),
                format_bytes(pod_mem),
                format_bytes(dump_metric_max(pod.mem_history, pod_mem, args)),
                format_bytes_per_sec(pod.net_rx_bps),
                format_bytes_per_sec(pod.net_tx_bps),
                format_bytes_per_sec(dump_metric_max(pod.net_history, pod.net_rx_bps + pod.net_tx_bps, args)),
                format_bytes_per_sec(pod.fs_read_bps),
                format_bytes_per_sec(pod.fs_write_bps),
                format_bytes_per_sec(dump_metric_max(pod.io_history, pod.fs_read_bps + pod.fs_write_bps, args)),
            )
        )
    cronjob_rows = sort_cronjobs(build_cronjob_rows(snapshot), "STATUS", True)
    if cronjob_rows:
        lines.append("")
        lines.append("CronJobs:")
        now = dt.datetime.now(dt.timezone.utc)
        for row in cronjob_rows:
            last_text = human_age(row.last_schedule, now)
            if row.next_schedule and row.next_schedule > now:
                next_text = "in %s" % format_duration_compact((row.next_schedule - now).total_seconds())
            elif row.late_seconds:
                next_text = "late %s" % format_duration_compact(row.late_seconds)
            else:
                next_text = "-"
            lines.append(
                "  %-12s %-32s %-12s schedule=%-14s last=%-8s next=%-10s active=%d ok=%d fail=%d p50=%s p95=%s hint=%s"
                % (
                    row.namespace,
                    truncate(row.name, 32),
                    row.status,
                    truncate(row.schedule, 14),
                    last_text,
                    next_text,
                    row.active,
                    row.succeeded,
                    row.failed,
                    format_duration_compact(row.p50_s),
                    format_duration_compact(row.p95_s),
                    truncate(row.hint, 60),
                )
            )
    if snapshot.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in snapshot.warnings:
            lines.append("  - %s" % warning)
    return "\n".join(lines)


class KtopApp:
    """Curses application controller. / Контроллер curses-приложения."""

    def __init__(self, stdscr: "curses._CursesWindow", args: argparse.Namespace, client: Any) -> None:
        """Initialize UI state. / Инициализирует состояние UI.

        Args:
            stdscr: curses root window.
            args: Parsed CLI arguments.
            client: Data client implementing snapshot/log/diagnostics methods.
        """
        self.stdscr = stdscr
        self.args = args
        self.client = client
        self.snapshot: Optional[ClusterSnapshot] = None
        self.page = "overview"
        self.stack: List[Tuple[str, Optional[str], Optional[Tuple[str, str]], Optional[str], Optional[Tuple[str, str]]]] = []
        self.overview_mode = "nodes"
        self.focus = "nodes"
        self.resource_focus = RESOURCE_PANEL_KEYS[0]
        self.health_focus = HEALTH_PANEL_KEYS[0]
        self.node_sort = ("NAME", True)
        self.namespace_sort = ("NAMESPACE", True)
        self.pod_sort = ("NAMESPACE", True)
        self.cronjob_sort = ("STATUS", True)
        self.selected = {
            "nodes": 0,
            "overview_namespaces": 0,
            "pods": 0,
            "node_pods": 0,
            "namespace_pods": 0,
            "containers": 0,
            "cronjobs": 0,
            "cronjob_pods": 0,
            "namespaces": 0,
        }
        self.scroll = {
            "nodes": 0,
            "overview_namespaces": 0,
            "pods": 0,
            "node_pods": 0,
            "namespace_pods": 0,
            "containers": 0,
            "cronjobs": 0,
            "cronjob_pods": 0,
            "logs": 0,
            "help": 0,
            "health": 0,
            "health_runtime": 0,
            "health_workloads": 0,
            "health_resources": 0,
            "resources": 0,
            "resource_missing": 0,
            "resource_ratios": 0,
            "resource_top": 0,
            "owner": 0,
            "diagnostics": 0,
            "namespaces": 0,
            "viewer": 0,
        }
        self.hscroll = {
            "nodes": 0,
            "overview_namespaces": 0,
            "pods": 0,
            "node_pods": 0,
            "namespace_pods": 0,
            "containers": 0,
            "cronjobs": 0,
            "cronjob_pods": 0,
            "health_runtime": 0,
            "health_workloads": 0,
            "health_resources": 0,
            "resource_missing": 0,
            "resource_ratios": 0,
            "resource_top": 0,
        }
        initial_namespace = "" if getattr(args, "all_namespaces", False) else (args.namespace or "")
        self.filters = {
            "namespace": initial_namespace,
            "nodes": "",
            "overview_namespaces": "",
            "pods": "",
            "cronjobs": "",
            "logs": "",
            "namespace_picker": "",
            "viewer": "",
        }
        self.editing_filter: Optional[str] = None
        self.filter_buffer = ""
        self.current_node: Optional[str] = None
        self.current_namespace: Optional[str] = None
        self.current_pod: Optional[Tuple[str, str]] = None
        self.current_container: Optional[str] = None
        self.current_cronjob: Optional[Tuple[str, str]] = None
        self.message = ""
        self.message_until = 0.0
        self.pending_esc_at = 0.0
        self.last_refresh = 0.0
        self.last_log_refresh = 0.0
        self.log_lines: List[str] = []
        self.log_tail = int(args.log_tail)
        self.log_timestamps = False
        self.log_wrap = True
        self.log_stream = True
        self.log_plain = False
        self.log_previous = False
        self.log_autoscroll = True
        self.log_filter_error = ""
        self.viewer_title = ""
        self.viewer_lines: List[str] = []
        self.viewer_filter_error = ""
        self.viewer_wrap = True
        self.viewer_plain = False
        self.viewer_mode = ""
        self.viewer_target: Optional[ObjectTarget] = None
        self.search_match_index = {"logs": 0, "viewer": 0}
        self.search_query_cache = {"logs": "", "viewer": ""}
        self.diagnostics_cache: List[str] = []
        self.colors: Dict[str, int] = {}
        self.rate_chart_peaks: Dict[Tuple[Any, ...], float] = {}
        self.resource_panel_visible = {key: 0 for key in RESOURCE_PANEL_KEYS}
        self.health_panel_visible = {key: 0 for key in HEALTH_PANEL_KEYS}
        self.snapshot_lock = threading.Lock()
        self.refresh_lock = threading.Lock()
        self.refreshing = False
        self.refresh_started_at = 0.0
        self.refresh_error = ""

    def run(self) -> None:
        """Run the TUI event loop. / Запускает TUI event loop.

        Returns:
            None; exits when the user requests quit.
        """
        self.setup_curses()
        self.refresh_snapshot(force=False)
        while True:
            now = time.time()
            if now - self.last_refresh >= self.args.refresh_interval and not self.editing_filter:
                self.refresh_snapshot(force=False)
            if self.page == "logs" and self.log_stream and now - self.last_log_refresh >= max(2.0, self.args.refresh_interval):
                self.load_logs()
            self.draw()
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                ch = None
            if ch is not None and self.handle_key(ch):
                break

    def setup_curses(self) -> None:
        """Configure curses colors and input. / Настраивает цвета и ввод curses."""
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.timeout(200)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            pairs = {
                "white": (curses.COLOR_WHITE, -1),
                "yellow": (curses.COLOR_YELLOW, -1),
                "green": (curses.COLOR_GREEN, -1),
                "red": (curses.COLOR_RED, -1),
                "cyan": (curses.COLOR_CYAN, -1),
                "blue": (curses.COLOR_BLUE, -1),
                "magenta": (curses.COLOR_MAGENTA, -1),
                "black_on_cyan": (curses.COLOR_BLACK, curses.COLOR_CYAN),
                "yellow_on_cyan": (curses.COLOR_YELLOW, curses.COLOR_CYAN),
                "black_on_white": (curses.COLOR_BLACK, curses.COLOR_WHITE),
                "white_on_black": (curses.COLOR_WHITE, curses.COLOR_BLACK),
                "black_on_yellow": (curses.COLOR_BLACK, curses.COLOR_YELLOW),
            }
            for idx, (name, value) in enumerate(pairs.items(), start=1):
                curses.init_pair(idx, value[0], value[1])
                self.colors[name] = curses.color_pair(idx)
        self.colors.setdefault("white", 0)
        self.colors.setdefault("yellow", curses.A_BOLD)
        self.colors.setdefault("green", curses.A_BOLD)
        self.colors.setdefault("red", curses.A_BOLD)
        self.colors.setdefault("cyan", curses.A_BOLD)
        self.colors.setdefault("blue", curses.A_BOLD)
        self.colors.setdefault("magenta", curses.A_BOLD)
        self.colors.setdefault("black_on_cyan", curses.A_REVERSE)
        self.colors.setdefault("yellow_on_cyan", curses.A_REVERSE)
        self.colors.setdefault("black_on_white", curses.A_REVERSE)
        self.colors.setdefault("white_on_black", 0)
        self.colors.setdefault("black_on_yellow", curses.A_REVERSE)

    def refresh_snapshot(self, force: bool = False) -> None:
        """Start background snapshot refresh. / Запускает фоновое обновление snapshot.

        Args:
            force: Whether this was explicitly requested by the user.
        """
        with self.refresh_lock:
            if self.refreshing:
                if force:
                    self.flash("refresh already running")
                return
            self.refreshing = True
            self.refresh_started_at = time.time()
            self.refresh_error = ""
        worker = threading.Thread(target=self.refresh_worker, args=(force,), daemon=True)
        worker.start()

    def refresh_worker(self, force: bool = False) -> None:
        """Load snapshot in a worker thread. / Загружает snapshot в worker thread.

        Args:
            force: Whether to show success feedback when loading finishes.
        """
        try:
            snapshot = self.client.load_snapshot()
            with self.snapshot_lock:
                self.snapshot = snapshot
            self.last_refresh = time.time()
            if force:
                self.flash("cluster data loaded")
        except DataError as exc:
            self.last_refresh = time.time()
            self.refresh_error = str(exc)
            self.flash(str(exc), error=True, ttl=8.0)
        finally:
            with self.refresh_lock:
                self.refreshing = False

    def flash(self, text: str, error: bool = False, ttl: float = 3.0) -> None:
        self.message = text
        self.message_until = time.time() + ttl
        if error:
            self.message = "ERROR: " + text

    def draw(self) -> None:
        """Draw the current page. / Рисует текущую страницу."""
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < MIN_ROWS or width < 80:
            self.add(0, 0, "Terminal too small: %dx%d, need at least 80x%d" % (width, height, MIN_ROWS), self.colors.get("red", 0))
            self.stdscr.refresh()
            return
        if self.page == "logs" and self.log_plain:
            self.draw_logs_plain(0, 0, height, width)
            self.stdscr.refresh()
            return
        if self.page == "viewer" and self.viewer_plain:
            self.draw_viewer_plain(0, 0, height, width)
            self.stdscr.refresh()
            return
        header_h = 1
        footer_h = 2
        content_y = header_h
        content_h = height - header_h - footer_h
        self.draw_header(0, 0, header_h, width)
        if self.page == "overview":
            self.draw_overview(content_y, 0, content_h, width)
        elif self.page == "node":
            self.draw_node_detail(content_y, 0, content_h, width)
        elif self.page == "namespace":
            self.draw_namespace_detail(content_y, 0, content_h, width)
        elif self.page == "pod":
            self.draw_pod_detail(content_y, 0, content_h, width)
        elif self.page == "cronjobs":
            self.draw_cronjobs(content_y, 0, content_h, width)
        elif self.page == "cronjob":
            self.draw_cronjob_detail(content_y, 0, content_h, width)
        elif self.page == "logs":
            self.draw_logs(content_y, 0, content_h, width)
        elif self.page == "viewer":
            self.draw_viewer(content_y, 0, content_h, width)
        elif self.page == "health":
            self.draw_health(content_y, 0, content_h, width)
        elif self.page == "resources":
            self.draw_resource_risk(content_y, 0, content_h, width)
        elif self.page == "owner":
            self.draw_text_page(content_y, 0, content_h, width, "Workload / Owner", self.owner_lines(), "owner")
        elif self.page == "diagnostics":
            lines = self.diagnostics_cache or ["Diagnostics have not been loaded yet. Press r to run checks."]
            self.draw_text_page(content_y, 0, content_h, width, "Metrics / RBAC Diagnostics", lines, "diagnostics")
        elif self.page == "namespaces":
            self.draw_namespace_picker(content_y, 0, content_h, width)
        elif self.page == "help":
            self.draw_text_page(content_y, 0, content_h, width, "Help", help_lines(), "help")
        self.draw_footer(height - footer_h, 0, footer_h, width)
        self.stdscr.refresh()

    def draw_header(self, y: int, x: int, height: int, width: int) -> None:
        if height <= 0:
            return
        snap = self.snapshot
        if snap:
            namespace = self.filter_display("namespace", snap.namespace)
            left = "Context: %s | K8s: %s | User: %s | Namespace: %s | Metrics: %s" % (
                snap.context,
                snap.k8s_version,
                snap.user,
                namespace,
                snap.metrics_status,
            )
        else:
            left = "Context: - | K8s: - | User: - | Namespace: - | Metrics: loading"
        refresh_state = self.refresh_state_text()
        if refresh_state:
            left += " | Refresh: %s" % refresh_state
        right = "ktop-py.py: v%s" % __VERSION__
        self.add(y, x + 1, left, self.colors.get("yellow", 0), max(1, width - len(right) - 4))
        self.add(y, max(x + 1, x + width - len(right) - 1), right, curses.A_BOLD)

    def refresh_state_text(self) -> str:
        if self.refreshing:
            return "loading %ds" % max(0, int(time.time() - self.refresh_started_at))
        if self.refresh_error:
            return "error"
        if self.last_refresh > 0:
            age = time.time() - self.last_refresh
            if age > max(self.args.refresh_interval * 2.0, self.args.refresh_interval + 5.0):
                return "stale %s" % human_age(dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age))
        return ""

    def filter_display(self, key: str, fallback: str) -> str:
        if self.editing_filter == key:
            return (self.filter_buffer or "") + "_"
        return self.filters.get(key) or fallback

    def draw_overview(self, y: int, x: int, height: int, width: int) -> None:
        snap = self.snapshot
        if not snap:
            self.box(y, x, height, width, "No cluster data", focused=False)
            self.add(y + 2, x + 2, "No data loaded. Check kubectl access or run with --demo.", self.colors.get("red", 0))
            return
        summary_h = METRIC_PANEL_HEIGHT + 4 if height >= 34 else 9 if height >= 28 else 7
        remaining = max(8, height - summary_h)
        node_h = max(6, remaining // 2)
        pod_h = max(6, remaining - node_h)
        self.draw_summary(y, x, summary_h, width, snap)
        if self.overview_mode == "namespaces":
            self.draw_namespaces_overview(y + summary_h, x, node_h, width, snap)
        else:
            self.draw_nodes(y + summary_h, x, node_h, width, snap)
        self.draw_pods(y + summary_h + node_h, x, pod_h, width, snap)

    def draw_summary(self, y: int, x: int, height: int, width: int, snap: ClusterSnapshot) -> None:
        self.box(y, x, height, width, "Cluster Summary", focused=False)
        ready_nodes = sum(1 for node in snap.nodes if node.status == "Ready")
        running_pods = sum(1 for pod in snap.pods if pod.status == "Running")
        failed = sum(1 for pod in snap.pods if pod.status in ("Failed", "Error", "CrashLoopBackOff"))
        evicted = sum(1 for pod in snap.pods if pod.status == "Evicted")
        restarts = sum(pod.restarts for pod in snap.pods)
        pressure = sum(1 for node in snap.nodes if node.pressures)
        cpu_total = sum(node.alloc_cpu_m for node in snap.nodes)
        mem_total = sum(node.alloc_mem_b for node in snap.nodes)
        if snap.metrics_available:
            cpu_value = sum(node.usage_cpu_m for node in snap.nodes)
            mem_value = sum(node.usage_mem_b for node in snap.nodes)
            label = "used"
        else:
            cpu_value = sum(node.requested_cpu_m for node in snap.nodes)
            mem_value = sum(node.requested_mem_b for node in snap.nodes)
            label = "requested"
        stat = (
            "Uptime: %s | Nodes: %d/%d | NS: %d | Deploys: %d/%d | Pods: %d/%d | Vols: %d | PVs: %d (%s) | PVCs: %d (%s)"
            % (
                human_age(snap.uptime_start),
                ready_nodes,
                len(snap.nodes),
                snap.namespaces_count,
                snap.deployments_ready,
                snap.deployments_total,
                running_pods,
                len(snap.pods),
                snap.volumes_in_use,
                snap.pv_count,
                format_bytes(snap.pv_capacity_b),
                snap.pvc_count,
                format_bytes(snap.pvc_capacity_b),
            )
        )
        if height < METRIC_PANEL_HEIGHT + 4:
            self.draw_summary_compact(y, x, height, width, snap, stat, cpu_value, cpu_total, mem_value, mem_total, label)
            return

        self.add(y + 1, x + 2, stat, self.colors.get("yellow", 0), width - 4)

        net_rx = sum(node.net_rx_bps for node in snap.nodes)
        net_tx = sum(node.net_tx_bps for node in snap.nodes)
        fs_read = sum(node.fs_read_bps for node in snap.nodes)
        fs_write = sum(node.fs_write_bps for node in snap.nodes)
        net_scale = self.rate_pair_chart_scale(history_key_cluster("net_split"), snap.cluster_net_rx_history, net_rx, snap.cluster_net_tx_history, net_tx)
        io_scale = self.rate_pair_chart_scale(history_key_cluster("io_split"), snap.cluster_fs_read_history, fs_read, snap.cluster_fs_write_history, fs_write)
        panel_y = y + 2
        panel_h = min(METRIC_PANEL_HEIGHT, max(4, y + height - 2 - panel_y))
        panel_w = max(10, (width - 5) // 4)
        panel_gap = 1
        panels = [
            (
                "CPU %s/%s (%4.1f%% %s)" % (format_mcpu(cpu_value), format_mcpu(cpu_total), ratio(cpu_value, cpu_total) * 100, label),
                snap.cluster_cpu_history,
                cpu_value,
                cpu_total,
            ),
            (
                "MEM %s/%s (%4.1f%% %s)" % (format_bytes(mem_value), format_bytes(mem_total), ratio(mem_value, mem_total) * 100, label),
                snap.cluster_mem_history,
                mem_value,
                mem_total,
            ),
        ]
        for idx, (title, history, current, total) in enumerate(panels):
            panel_x = x + 1 + idx * (panel_w + panel_gap)
            panel_w_current = panel_w
            self.draw_metric_panel(panel_y, panel_x, panel_h, panel_w_current, title, history, current, total)
        net_x = x + 1 + 2 * (panel_w + panel_gap)
        disk_x = x + 1 + 3 * (panel_w + panel_gap)
        net_w = panel_w
        disk_w = max(10, x + width - disk_x - 1)
        self.draw_rate_split_panel(
            panel_y,
            net_x,
            panel_h,
            net_w,
            "Net ↓%s ↑%s %s" % (format_bytes_per_sec(net_rx), format_bytes_per_sec(net_tx), self.rate_scale_title(net_scale)),
            "rx",
            snap.cluster_net_rx_history,
            net_rx,
            "tx",
            snap.cluster_net_tx_history,
            net_tx,
            net_scale,
        )
        self.draw_rate_split_panel(
            panel_y,
            disk_x,
            panel_h,
            disk_w,
            "Disk R:%s W:%s %s" % (format_bytes_per_sec(fs_read), format_bytes_per_sec(fs_write), self.rate_scale_title(io_scale)),
            "r",
            snap.cluster_fs_read_history,
            fs_read,
            "w",
            snap.cluster_fs_write_history,
            fs_write,
            io_scale,
        )

        enhanced = "Restarts: %d | Failures: %d | Evicted: %d | Pressure: %d | Loaded: %s" % (
            restarts,
            failed,
            evicted,
            pressure,
            snap.loaded_at.astimezone().strftime("%H:%M:%S"),
        )
        self.add(panel_y + panel_h, x + 2, enhanced, self.colors.get("yellow", 0), width - 4)

    def draw_summary_compact(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        snap: ClusterSnapshot,
        stat: str,
        cpu_value: float,
        cpu_total: float,
        mem_value: float,
        mem_total: float,
        label: str,
    ) -> None:
        self.add(y + 1, x + 2, stat, self.colors.get("yellow", 0), width - 4)
        graph_w = max(6, min(32, max(6, (width - 44) // 2)))
        net_rx = sum(node.net_rx_bps for node in snap.nodes)
        net_tx = sum(node.net_tx_bps for node in snap.nodes)
        fs_read = sum(node.fs_read_bps for node in snap.nodes)
        fs_write = sum(node.fs_write_bps for node in snap.nodes)
        net_current = net_rx + net_tx
        io_current = fs_read + fs_write
        net_scale = self.rate_chart_scale(history_key_cluster("net"), snap.cluster_net_history, net_current)
        io_scale = self.rate_chart_scale(history_key_cluster("io"), snap.cluster_io_history, io_current)
        rows = [
            (
                "CPU",
                "%s %s/%s (%4.1f%% %s)"
                % (
                    self.trend_or_bar(snap.cluster_cpu_history, ratio(cpu_value, cpu_total), width=graph_w, total=cpu_total),
                    format_mcpu(cpu_value),
                    format_mcpu(cpu_total),
                    ratio(cpu_value, cpu_total) * 100,
                    label,
                ),
                self.resource_attr(ratio(cpu_value, cpu_total)),
            ),
            (
                "MEM",
                "%s %s/%s (%4.1f%% %s)"
                % (
                    self.trend_or_bar(snap.cluster_mem_history, ratio(mem_value, mem_total), width=graph_w, total=mem_total),
                    format_bytes(mem_value),
                    format_bytes(mem_total),
                    ratio(mem_value, mem_total) * 100,
                    label,
                ),
                self.resource_attr(ratio(mem_value, mem_total)),
            ),
            (
                "Net",
                "%s ↓%s ↑%s %s"
                % (
                    self.trend_or_bar(snap.cluster_net_history, ratio(net_current, net_scale), width=graph_w, total=net_scale),
                    format_bytes_per_sec(net_rx),
                    format_bytes_per_sec(net_tx),
                    self.rate_scale_title(net_scale),
                ),
                self.colors.get("green", 0),
            ),
            (
                "Disk",
                "%s R:%s W:%s %s"
                % (
                    self.trend_or_bar(snap.cluster_io_history, ratio(io_current, io_scale), width=graph_w, total=io_scale),
                    format_bytes_per_sec(fs_read),
                    format_bytes_per_sec(fs_write),
                    self.rate_scale_title(io_scale),
                ),
                self.colors.get("green", 0),
            ),
        ]
        available_rows = max(0, height - 3)
        for idx, (name, text, attr) in enumerate(rows[:available_rows]):
            self.add(y + 2 + idx, x + 2, "%-4s %s" % (name, text), attr, width - 4)
        if snap.warnings and available_rows > len(rows):
            self.add(y + 2 + len(rows), x + 2, "Warning: " + truncate(snap.warnings[-1], width - 14), self.colors.get("red", 0), width - 4)

    def draw_metric_panel(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        history: Sequence[float],
        current: float,
        total: float,
    ) -> None:
        """Draw a framed metric chart panel. / Рисует панель графика метрики.

        Args:
            y: Top row.
            x: Left column.
            height: Panel height.
            width: Panel width.
            title: Panel title.
            history: Metric history.
            current: Current value.
            total: Capacity or scale.
        """
        self.box(y, x, height, width, truncate(title, max(1, width - 4)), focused=False)
        plot_h = max(1, height - 2)
        plot_w = max(1, width - 2)
        self.draw_graph_rows(y + 1, x + 1, plot_h, plot_w, history, current, total)

    def draw_rate_split_panel(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        first_label: str,
        first_history: Sequence[float],
        first_current: float,
        second_label: str,
        second_history: Sequence[float],
        second_current: float,
        scale: float,
    ) -> None:
        """Draw a two-direction rate chart panel. / Рисует split-панель rate-графика по двум направлениям.

        Args:
            y: Top row.
            x: Left column.
            height: Panel height.
            width: Panel width.
            title: Panel title.
            first_label: Label for the first series, e.g. rx/read.
            first_history: First series history.
            first_current: First current value.
            second_label: Label for the second series, e.g. tx/write.
            second_history: Second series history.
            second_current: Second current value.
            scale: Shared chart scale.
        """
        self.box(y, x, height, width, truncate(title, max(1, width - 4)), focused=False)
        inner_h = max(1, height - 2)
        inner_w = max(1, width - 2)
        label_w = min(max(len(first_label), len(second_label)) + 1, max(1, inner_w - 1))
        plot_w = max(1, inner_w - label_w)
        if inner_h >= 5:
            first_h = 2
            second_h = 2
            first_y = y + 1
            second_y = y + 4
        elif inner_h >= 4:
            first_h = 2
            second_h = 2
            first_y = y + 1
            second_y = y + 3
        else:
            first_h = 1
            second_h = 1
            first_y = y + 1
            second_y = y + 1 + min(1, inner_h - 1)

        first_attr = self.colors.get("green", 0)
        second_attr = self.colors.get("yellow", 0)
        self.add(first_y, x + 1, first_label.ljust(label_w), first_attr, label_w)
        self.draw_graph_rows(first_y, x + 1 + label_w, first_h, plot_w, first_history, first_current, scale, first_attr)
        if inner_h > 1:
            self.add(second_y, x + 1, second_label.ljust(label_w), second_attr, label_w)
            self.draw_graph_rows(second_y, x + 1 + label_w, second_h, plot_w, second_history, second_current, scale, second_attr)

    def chart_values(self, history: Sequence[float], current: float, width: int) -> List[float]:
        """Align history values to chart width. / Выравнивает историю под ширину графика.

        Args:
            history: Retained metric values.
            current: Current metric value used when history is empty.
            width: Target chart width.
        Returns:
            Values padded or downsampled to exactly width items.
        """
        clean = [float(value or 0.0) for value in history if math.isfinite(float(value or 0.0))]
        if not clean:
            clean = [float(current or 0.0)]
        if len(clean) == 1:
            return [0.0] * (width - 1) + clean
        if len(clean) > width:
            # Downsample by averaging buckets instead of dropping spikes blindly.
            # Уменьшаем историю средними bucket, а не простым отбрасыванием.
            step = float(len(clean)) / float(width)
            reduced = []
            for idx in range(width):
                start = int(idx * step)
                end = int((idx + 1) * step)
                chunk = clean[start : max(start + 1, end)]
                reduced.append(sum(chunk) / float(len(chunk)))
            clean = reduced
        if len(clean) < width:
            clean = [0.0] * (width - len(clean)) + clean
        return clean

    def chart_sample_count(self, history: Sequence[float], current: float, width: int) -> int:
        clean = [float(value or 0.0) for value in history if math.isfinite(float(value or 0.0))]
        if clean:
            return min(len(clean), max(1, int(width)))
        if math.isfinite(float(current or 0.0)):
            return 1
        return 0

    def rate_chart_scale(self, key: Tuple[Any, ...], history: Sequence[float], current: float) -> float:
        """Return stable scale for rate charts. / Возвращает стабильный масштаб rate-графиков.

        Args:
            key: Metric identity.
            history: Retained rate values.
            current: Current rate value.
        Returns:
            Peak scale with a minimum baseline for net/disk panels.
        """
        clean = [float(value or 0.0) for value in history if math.isfinite(float(value or 0.0))]
        peak = self.rate_chart_peaks.get(key, 0.0)
        if clean:
            peak = max(peak, max(clean))
        peak = max(peak, float(current or 0.0))
        self.rate_chart_peaks[key] = peak
        return max(peak, RATE_CHART_MIN_BYTES_PER_SECOND)

    def rate_pair_chart_scale(
        self,
        key: Tuple[Any, ...],
        first_history: Sequence[float],
        first_current: float,
        second_history: Sequence[float],
        second_current: float,
    ) -> float:
        """Return one stable scale for two related rate series. / Возвращает общий масштаб для двух rate-серий.

        Args:
            key: Shared chart identity.
            first_history: Retained values for the first direction.
            first_current: Current value for the first direction.
            second_history: Retained values for the second direction.
            second_current: Current value for the second direction.
        Returns:
            Shared peak scale with a minimum baseline.
        """
        clean_first = [float(value or 0.0) for value in first_history if math.isfinite(float(value or 0.0))]
        clean_second = [float(value or 0.0) for value in second_history if math.isfinite(float(value or 0.0))]
        peak = self.rate_chart_peaks.get(key, 0.0)
        if clean_first:
            peak = max(peak, max(clean_first))
        if clean_second:
            peak = max(peak, max(clean_second))
        peak = max(peak, float(first_current or 0.0), float(second_current or 0.0))
        self.rate_chart_peaks[key] = peak
        return max(peak, RATE_CHART_MIN_BYTES_PER_SECOND)

    def rate_scale_title(self, scale: float) -> str:
        """Format rate chart scale for panel title. / Форматирует масштаб rate-графика для заголовка."""
        return "max:%s" % format_bytes_per_sec(scale)

    def chart_attr(self, value: float, total: float) -> int:
        if total > 0:
            return self.resource_attr(ratio(value, total))
        return self.colors.get("green", 0)

    def draw_nodes(self, y: int, x: int, height: int, width: int, snap: ClusterSnapshot) -> None:
        rows = self.current_nodes()
        title = "Nodes (%d/%d)" % (len(rows), len(snap.nodes))
        if self.filters["nodes"] or self.editing_filter == "nodes":
            title += " filter:%s" % self.filter_display("nodes", "")
        self.draw_table(
            y,
            x,
            height,
            width,
            title,
            normalize_columns(self.args.node_columns, NODE_COLUMNS, NODE_DEFAULT_COLUMNS),
            rows,
            self.node_cell,
            "nodes",
            self.node_sort,
            focused=(self.page == "overview" and self.focus == "nodes"),
        )

    def draw_namespaces_overview(self, y: int, x: int, height: int, width: int, snap: ClusterSnapshot) -> None:
        rows = self.current_namespace_rows()
        title = "Namespaces (%d/%d)" % (len(rows), len(self.all_namespace_rows()))
        if self.filters["overview_namespaces"] or self.editing_filter == "overview_namespaces":
            title += " filter:%s" % self.filter_display("overview_namespaces", "")
        self.draw_table(
            y,
            x,
            height,
            width,
            title,
            NAMESPACE_COLUMNS,
            rows,
            self.namespace_cell,
            "overview_namespaces",
            self.namespace_sort,
            focused=(self.page == "overview" and self.focus == "overview_namespaces"),
        )

    def draw_pods(self, y: int, x: int, height: int, width: int, snap: ClusterSnapshot) -> None:
        rows = self.current_pods()
        title = "Pods (%d/%d)" % (len(rows), len(snap.pods))
        if self.filters["pods"] or self.filters["namespace"] or self.editing_filter in ("pods", "namespace"):
            pieces = []
            if self.filters["namespace"] or self.editing_filter == "namespace":
                pieces.append("ns:%s" % self.filter_display("namespace", ""))
            if self.filters["pods"] or self.editing_filter == "pods":
                pieces.append("filter:%s" % self.filter_display("pods", ""))
            title += " " + " ".join(pieces)
        self.draw_table(
            y,
            x,
            height,
            width,
            title,
            normalize_columns(self.args.pod_columns, POD_COLUMNS),
            rows,
            self.pod_cell,
            "pods",
            self.pod_sort,
            focused=(self.page == "overview" and self.focus == "pods"),
        )

    def draw_cronjobs(self, y: int, x: int, height: int, width: int) -> None:
        """Draw CronJob diagnostics list. / Рисует список диагностики CronJob."""
        rows = self.current_cronjobs()
        title = "CronJobs (%d/%d)" % (len(rows), len(self.all_cronjob_rows()))
        if self.filters["cronjobs"] or self.editing_filter == "cronjobs":
            title += " filter:%s" % self.filter_display("cronjobs", "")
        self.draw_table(
            y,
            x,
            height,
            width,
            title,
            CRONJOB_COLUMNS,
            rows,
            self.cronjob_cell,
            "cronjobs",
            self.cronjob_sort,
            focused=self.page == "cronjobs",
        )

    def draw_table(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        columns: List[str],
        rows: Sequence[Any],
        cell_func: Any,
        state_key: str,
        sort_state: Tuple[str, bool],
        focused: bool,
    ) -> None:
        self.box(y, x, height, width, title, focused=focused)
        inner_w = max(1, width - 2)
        header_y = y + 1
        data_y = y + 2
        data_h = max(0, height - 3)
        selected = min(self.selected.get(state_key, 0), max(0, len(rows) - 1))
        self.selected[state_key] = selected
        scroll = self.adjust_scroll(state_key, selected, data_h, len(rows))
        col_widths = self.column_widths(columns, inner_w)
        total_w = sum(col_widths.get(col, 0) for col in columns) + max(0, len(columns) - 1)
        max_hscroll = max(0, total_w - inner_w)
        if not hasattr(self, "hscroll"):
            self.hscroll = {}
        hscroll = max(0, min(max_hscroll, self.hscroll.get(state_key, 0)))
        self.hscroll[state_key] = hscroll
        sort_col, asc = sort_state

        def draw_virtual(row_y: int, start: int, text: str, attr: int) -> None:
            visible_start = max(0, hscroll - start)
            visible_end = min(len(text), hscroll + inner_w - start)
            if visible_end <= visible_start:
                return
            draw_x = x + 1 + max(0, start - hscroll)
            self.add(row_y, draw_x, text[visible_start:visible_end], attr, visible_end - visible_start)

        header_attr = self.colors.get("black_on_cyan", curses.A_REVERSE)
        self.add(header_y, x + 1, " " * inner_w, header_attr, inner_w)
        virtual_x = 0
        for idx, col in enumerate(columns):
            col_w = col_widths.get(col, 0)
            if col_w <= 0:
                continue
            label = col + (" ↑" if col == sort_col and asc else " ↓" if col == sort_col else "")
            segment = truncate(label, col_w).ljust(col_w)
            if idx < len(columns) - 1:
                segment += " "
            draw_virtual(header_y, virtual_x, segment, header_attr)
            virtual_x += len(segment)
        for idx, row in enumerate(rows[scroll : scroll + data_h], start=scroll):
            row_y = data_y + idx - scroll
            base_attr = 0
            if focused and idx == selected:
                base_attr = curses.A_REVERSE
                self.add(row_y, x + 1, " " * inner_w, base_attr, inner_w)
            virtual_x = 0
            for col_idx, col in enumerate(columns):
                col_w = col_widths.get(col, 0)
                if col_w <= 0:
                    continue
                text, attr = cell_func(row, col)
                attr = base_attr if attr is None else attr
                if focused and idx == selected:
                    attr = curses.A_REVERSE
                segment = truncate(text, col_w).ljust(col_w)
                if col_idx < len(columns) - 1:
                    segment += " "
                draw_virtual(row_y, virtual_x, segment, attr)
                virtual_x += len(segment)
        indicators = []
        if len(rows) > data_h and data_h > 0:
            indicators.append("%d-%d/%d" % (scroll + 1, min(len(rows), scroll + data_h), len(rows)))
        if max_hscroll > 0:
            indicators.append("cols %d-%d/%d" % (hscroll + 1, min(total_w, hscroll + inner_w), total_w))
        if indicators:
            indicator = " | ".join(indicators)
            self.add(y + height - 1, max(x + 1, x + width - len(indicator) - 2), indicator, curses.A_BOLD, len(indicator))

    def column_widths(self, columns: Sequence[str], inner_width: int) -> Dict[str, int]:
        del inner_width
        desired = {
            "NAME": 20,
            "STATUS": 11,
            "RST": 5,
            "PODS": 5,
            "TAINTS": 7,
            "PRESSURE": 12,
            "IP": 15,
            "VOLS": 7,
            "DISK": 7,
            "CPU": 27,
            "MEM": 28,
            "NET": 19,
            "IO": 19,
            "NET RX": 19,
            "NET TX": 19,
            "DISK R": 19,
            "DISK W": 19,
            "MEMORY": 28,
            "NAMESPACE": 12,
            "POD": 40,
            "READY": 6,
            "AGE": 6,
            "NODE": 20,
            "CONTAINER": 20,
            "IMAGE": 34,
            "CPU USE": 13,
            "MEM USE": 13,
            "CPU REQ": 9,
            "MEM REQ": 9,
            "CPU LIM": 9,
            "MEM LIM": 9,
            "PORTS": 12,
            "MOUNTS": 7,
        }
        if "FAIL" in columns and "NAMESPACE" in columns:
            desired.update(
                {
                    "NAMESPACE": 28,
                    "STATUS": 12,
                    "PODS": 6,
                    "READY": 7,
                    "RST": 5,
                    "FAIL": 5,
                    "CPU": 27,
                    "MEMORY": 28,
                    "NET RX": 20,
                    "NET TX": 20,
                    "DISK R": 20,
                    "DISK W": 20,
                }
            )
        if "RESTARTS" in columns and "NAME" in columns:
            desired.update(
                {
                    "NAMESPACE": 34,
                    "NAME": 44,
                    "STATUS": 20,
                    "READY": 18,
                    "RESTARTS": 20,
                    "CPU": 14,
                    "MEM": 14,
                    "AGE": 8,
                }
            )
        if "STATE" in columns and "IMAGE" in columns:
            desired.update(
                {
                    "NAME": 38,
                    "IMAGE": 70,
                    "STATE": 22,
                    "READY": 18,
                    "RESTARTS": 20,
                    "CPU": 18,
                    "MEM": 18,
                }
            )
        if "SCHEDULE" in columns and "P95" in columns:
            desired.update(
                {
                    "NAMESPACE": 16,
                    "NAME": 34,
                    "SCHEDULE": 14,
                    "TZ": 12,
                    "SUSP": 6,
                    "LAST": 8,
                    "NEXT": 8,
                    "LATE": 8,
                    "ACTIVE": 7,
                    "OK": 5,
                    "FAIL": 5,
                    "P50": 8,
                    "P95": 8,
                    "P99": 8,
                    "STATUS": 12,
                    "HINT": 42,
                }
            )
        return {col: max(1, desired.get(col, 12)) for col in columns}

    def rate_mini_cell(self, key: Tuple[Any, ...], history: Sequence[float], current: float, width: int = 6) -> Tuple[str, Optional[int]]:
        """Render a one-line rate sparkline cell. / Рендерит однострочную rate-ячейку с миниграфиком.

        Args:
            key: Stable chart scale key.
            history: Retained rate history for one direction.
            current: Current rate value.
            width: Sparkline width inside brackets.
        Returns:
            Cell text and optional color attribute.
        """
        scale = self.rate_chart_scale(key, history, current)
        text = "%s %s" % (self.trend_or_bar(history, ratio(current, scale), width=width, total=scale), format_bytes_per_sec(current))
        attr = self.colors.get("cyan", 0) if current or clean_metric_values(history) else None
        return text, attr

    def node_cell(self, node: NodeRow, col: str) -> Tuple[str, Optional[int]]:
        if col == "NAME":
            return ("*" + node.name if node.controller else node.name, self.colors.get("yellow", 0))
        if col == "STATUS":
            return node.status, self.status_attr(node.status)
        if col == "RST":
            return str(node.restarts), self.colors.get("yellow", 0) if node.restarts else self.colors.get("green", 0)
        if col == "PODS":
            return str(node.pods_count), self.colors.get("yellow", 0)
        if col == "TAINTS":
            return str(node.taints), self.colors.get("yellow", 0) if node.taints else self.colors.get("green", 0)
        if col == "PRESSURE":
            return "/".join(node.pressures) if node.pressures else "none", self.colors.get("red", 0) if node.pressures else self.colors.get("green", 0)
        if col == "IP":
            return node.internal_ip, self.colors.get("yellow", 0)
        if col == "VOLS":
            return "%d/%d" % (node.volumes_in_use, node.volumes_attached), self.colors.get("yellow", 0)
        if col == "DISK":
            return format_bytes(node.alloc_storage_b), self.colors.get("yellow", 0)
        if col == "CPU":
            value = self.display_usage(node.usage_cpu_m, node.requested_cpu_m, node.cpu_history)
            pct = ratio(value, node.alloc_cpu_m) * 100
            return "%s %5s %4.1f%% %s" % (self.trend_or_bar(node.cpu_history, pct / 100.0, total=node.alloc_cpu_m), format_mcpu(value), pct, self.history_arrow(node.cpu_history)), self.resource_attr(pct / 100.0)
        if col == "MEM":
            value = self.display_usage(node.usage_mem_b, node.requested_mem_b, node.mem_history)
            pct = ratio(value, node.alloc_mem_b) * 100
            return "%s %6s %4.1f%% %s" % (self.trend_or_bar(node.mem_history, pct / 100.0, total=node.alloc_mem_b), format_bytes(value), pct, self.history_arrow(node.mem_history)), self.resource_attr(pct / 100.0)
        if col == "DISK R":
            return self.rate_mini_cell(history_key_node(node.name, "io_read"), node.fs_read_history, node.fs_read_bps)
        if col == "DISK W":
            return self.rate_mini_cell(history_key_node(node.name, "io_write"), node.fs_write_history, node.fs_write_bps)
        if col == "NET TX":
            return self.rate_mini_cell(history_key_node(node.name, "net_tx"), node.net_tx_history, node.net_tx_bps)
        if col == "NET RX":
            return self.rate_mini_cell(history_key_node(node.name, "net_rx"), node.net_rx_history, node.net_rx_bps)
        if col == "NET":
            current = node.net_rx_bps + node.net_tx_bps
            return self.rate_mini_cell(history_key_node(node.name, "net"), node.net_history, current)
        if col == "IO":
            current = node.fs_read_bps + node.fs_write_bps
            return self.rate_mini_cell(history_key_node(node.name, "io"), node.io_history, current)
        return "-", None

    def namespace_cell(self, namespace: NamespaceRow, col: str) -> Tuple[str, Optional[int]]:
        if col == "NAMESPACE":
            return namespace.name, self.colors.get("yellow", 0)
        if col == "STATUS":
            return namespace.status, self.status_attr(namespace.status)
        if col == "PODS":
            return "%d/%d" % (namespace.running_pods, namespace.pods_count), self.colors.get("yellow", 0)
        if col == "READY":
            return "%d/%d" % (namespace.ready, namespace.total), self.colors.get("green", 0) if namespace.ready == namespace.total else self.colors.get("yellow", 0)
        if col == "RST":
            return str(namespace.restarts), self.colors.get("yellow", 0) if namespace.restarts else self.colors.get("green", 0)
        if col == "FAIL":
            return str(namespace.failures), self.colors.get("red", 0) if namespace.failures else self.colors.get("green", 0)
        if col == "CPU":
            value = self.display_usage(namespace.usage_cpu_m, namespace.requested_cpu_m, namespace.cpu_history)
            pct = ratio(value, namespace.cpu_total_m) * 100.0
            return "%s %5s %4.1f%% %s" % (self.trend_or_bar(namespace.cpu_history, pct / 100.0, total=namespace.cpu_total_m), format_mcpu(value), pct, self.history_arrow(namespace.cpu_history)), self.resource_attr(pct / 100.0)
        if col == "MEMORY":
            value = self.display_usage(namespace.usage_mem_b, namespace.requested_mem_b, namespace.mem_history)
            pct = ratio(value, namespace.mem_total_b) * 100.0
            return "%s %6s %4.1f%% %s" % (self.trend_or_bar(namespace.mem_history, pct / 100.0, total=namespace.mem_total_b), format_bytes(value), pct, self.history_arrow(namespace.mem_history)), self.resource_attr(pct / 100.0)
        if col == "DISK R":
            return self.rate_mini_cell(history_key_namespace(namespace.name, "io_read"), namespace.fs_read_history, namespace.fs_read_bps)
        if col == "DISK W":
            return self.rate_mini_cell(history_key_namespace(namespace.name, "io_write"), namespace.fs_write_history, namespace.fs_write_bps)
        if col == "NET TX":
            return self.rate_mini_cell(history_key_namespace(namespace.name, "net_tx"), namespace.net_tx_history, namespace.net_tx_bps)
        if col == "NET RX":
            return self.rate_mini_cell(history_key_namespace(namespace.name, "net_rx"), namespace.net_rx_history, namespace.net_rx_bps)
        if col == "NET":
            current = namespace.net_rx_bps + namespace.net_tx_bps
            return self.rate_mini_cell(history_key_namespace(namespace.name, "net"), namespace.net_history, current)
        if col == "IO":
            current = namespace.fs_read_bps + namespace.fs_write_bps
            return self.rate_mini_cell(history_key_namespace(namespace.name, "io"), namespace.io_history, current)
        return "-", None

    def cronjob_time_text(self, value: Optional[dt.datetime], late_seconds: float = 0.0) -> str:
        """Format CronJob time in a table cell. / Форматирует время CronJob для таблицы."""
        if not value:
            return "-"
        now = dt.datetime.now(dt.timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        if value > now:
            return "in %s" % format_duration_compact((value - now).total_seconds())
        if late_seconds > 0:
            return "late %s" % format_duration_compact(late_seconds)
        return human_age(value, now)

    def cronjob_cell(self, row: CronJobRow, col: str) -> Tuple[str, Optional[int]]:
        """Render one CronJob table cell. / Рендерит одну ячейку таблицы CronJob."""
        attr = self.health_severity_attr(row.severity)
        if col == "NAMESPACE":
            return row.namespace, self.colors.get("yellow", 0)
        if col == "NAME":
            return row.name, self.colors.get("yellow", 0)
        if col == "SCHEDULE":
            return row.schedule, None
        if col == "TZ":
            return row.timezone, None
        if col == "SUSP":
            return "yes" if row.suspend else "no", self.colors.get("yellow", 0) if row.suspend else self.colors.get("green", 0)
        if col == "LAST":
            return self.cronjob_time_text(row.last_schedule), None
        if col == "NEXT":
            return self.cronjob_time_text(row.next_schedule, row.late_seconds), attr
        if col == "LATE":
            return format_duration_compact(row.late_seconds) if row.late_seconds else "-", attr if row.late_seconds else None
        if col == "ACTIVE":
            return str(row.active), self.colors.get("yellow", 0) if row.active else self.colors.get("green", 0)
        if col == "OK":
            return str(row.succeeded), self.colors.get("green", 0)
        if col == "FAIL":
            return str(row.failed), self.colors.get("red", 0) if row.failed else self.colors.get("green", 0)
        if col == "P50":
            return format_duration_compact(row.p50_s), None
        if col == "P95":
            return format_duration_compact(row.p95_s), None
        if col == "P99":
            return format_duration_compact(row.p99_s), None
        if col == "STATUS":
            return row.status, attr
        if col == "HINT":
            return row.hint, attr
        return "-", None

    def pod_cell(self, pod: PodRow, col: str) -> Tuple[str, Optional[int]]:
        if col == "NAMESPACE":
            return pod.namespace, self.colors.get("yellow", 0)
        if col == "POD":
            return pod.name, self.colors.get("yellow", 0)
        if col == "READY":
            return "%d/%d" % (pod.ready, pod.total), self.colors.get("yellow", 0)
        if col == "STATUS":
            return pod.status, self.status_attr(pod.status)
        if col == "RST":
            return str(pod.restarts), self.colors.get("yellow", 0) if pod.restarts else None
        if col == "AGE":
            return human_age(pod.creation_time), self.colors.get("yellow", 0)
        if col == "VOLS":
            return "%d/%d" % (pod.volumes, pod.mounts), self.colors.get("yellow", 0)
        if col == "IP":
            return pod.ip, self.colors.get("yellow", 0)
        if col == "NODE":
            return pod.node, self.colors.get("yellow", 0)
        if col == "CPU":
            value = self.display_usage(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history)
            pct = ratio(value, pod.node_alloc_cpu_m) * 100
            return "%s %5s %4.1f%% %s" % (self.trend_or_bar(pod.cpu_history, pct / 100.0, total=pod.node_alloc_cpu_m), format_mcpu(value), pct, self.history_arrow(pod.cpu_history)), self.resource_attr(pct / 100.0)
        if col == "MEMORY":
            value = self.display_usage(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history)
            pct = ratio(value, pod.node_alloc_mem_b) * 100
            return "%s %6s %4.1f%% %s" % (self.trend_or_bar(pod.mem_history, pct / 100.0, total=pod.node_alloc_mem_b), format_bytes(value), pct, self.history_arrow(pod.mem_history)), self.resource_attr(pct / 100.0)
        return "-", None

    def draw_namespace_detail(self, y: int, x: int, height: int, width: int) -> None:
        namespace = self.find_namespace(self.current_namespace)
        if not namespace:
            self.box(y, x, height, width, "Namespace Detail", focused=False)
            self.add(y + 2, x + 2, "Namespace not found", self.colors.get("red", 0))
            return
        if height < 20:
            self.draw_namespace_detail_compact(y, x, height, width, namespace)
            return

        self.box(y, x, height, width, "Namespaces > %s" % namespace.name, focused=True)
        inner_x = x + 1
        inner_w = width - 2
        info_y = y + 1
        metrics_y = info_y + 3
        pods_y = metrics_y + METRIC_PANEL_HEIGHT
        pods_h = max(6, y + height - pods_y - 1)

        self.draw_namespace_info_panel(info_y, inner_x, 3, inner_w, namespace)
        self.draw_namespace_metric_panels(metrics_y, inner_x, METRIC_PANEL_HEIGHT, inner_w, namespace)
        pods = self.current_namespace_pods(namespace.name)
        title = "Pods (%d/%d)" % (len(pods), namespace.pods_count)
        if self.filters["pods"] or self.editing_filter == "pods":
            title += " filter:%s" % self.filter_display("pods", "")
        self.draw_table(
            pods_y,
            x + 1,
            pods_h,
            width - 2,
            title,
            ["POD", "READY", "STATUS", "RST", "AGE", "VOLS", "IP", "NODE", "CPU", "MEMORY"],
            pods,
            self.pod_cell,
            "namespace_pods",
            self.pod_sort,
            focused=True,
        )

    def draw_namespace_detail_compact(self, y: int, x: int, height: int, width: int, namespace: NamespaceRow) -> None:
        self.box(y, x, height, width, "Namespaces > %s" % namespace.name, focused=True)
        line = "Status: %s | Pods: %d | Ready: %d/%d | Restarts: %d | Failures: %d" % (
            namespace.status,
            namespace.pods_count,
            namespace.ready,
            namespace.total,
            namespace.restarts,
            namespace.failures,
        )
        self.add(y + 1, x + 2, line, 0, width - 4)
        pods = self.current_namespace_pods(namespace.name)
        self.draw_table(
            y + 3,
            x + 1,
            max(5, height - 4),
            width - 2,
            "Pods (%d/%d)" % (len(pods), namespace.pods_count),
            ["POD", "READY", "STATUS", "RST", "AGE", "NODE", "CPU", "MEMORY"],
            pods,
            self.pod_cell,
            "namespace_pods",
            self.pod_sort,
            focused=True,
        )

    def draw_namespace_info_panel(self, y: int, x: int, height: int, width: int, namespace: NamespaceRow) -> None:
        self.box(y, x, height, width, "Info", focused=False)
        line = "Status: %s | Pods: %d | Running: %d | Ready: %d/%d | Restarts: %d | Failures: %d" % (
            namespace.status,
            namespace.pods_count,
            namespace.running_pods,
            namespace.ready,
            namespace.total,
            namespace.restarts,
            namespace.failures,
        )
        self.add(y + 1, x + 2, line, 0, width - 4)

    def draw_namespace_metric_panels(self, y: int, x: int, height: int, width: int, namespace: NamespaceRow) -> None:
        gap = 1
        panel_w = max(10, (width - 3 * gap) // 4)
        cpu_value = self.display_usage(namespace.usage_cpu_m, namespace.requested_cpu_m, namespace.cpu_history)
        mem_value = self.display_usage(namespace.usage_mem_b, namespace.requested_mem_b, namespace.mem_history)
        net_scale = self.rate_pair_chart_scale(history_key_namespace(namespace.name, "net_split"), namespace.net_rx_history, namespace.net_rx_bps, namespace.net_tx_history, namespace.net_tx_bps)
        io_scale = self.rate_pair_chart_scale(history_key_namespace(namespace.name, "io_split"), namespace.fs_read_history, namespace.fs_read_bps, namespace.fs_write_history, namespace.fs_write_bps)
        usage_metrics = [
            (
                "CPU %s/%s (%4.1f%% used) %s"
                % (format_cpu_millis(cpu_value), format_cpu_millis(namespace.cpu_total_m), ratio(cpu_value, namespace.cpu_total_m) * 100, self.history_arrow(namespace.cpu_history)),
                namespace.cpu_history,
                cpu_value,
                namespace.cpu_total_m,
                self.resource_attr(ratio(cpu_value, namespace.cpu_total_m)),
            ),
            (
                "MEM %s/%s (%4.1f%% used) %s"
                % (format_mib(mem_value), format_mib(namespace.mem_total_b), ratio(mem_value, namespace.mem_total_b) * 100, self.history_arrow(namespace.mem_history)),
                namespace.mem_history,
                mem_value,
                namespace.mem_total_b,
                self.resource_attr(ratio(mem_value, namespace.mem_total_b)),
            ),
        ]
        for idx, (title, history, current, total, attr) in enumerate(usage_metrics):
            panel_x = x + idx * (panel_w + gap)
            panel_width = panel_w
            self.draw_node_timeseries_panel(y, panel_x, height, panel_width, title, history, current, total, attr)
        net_x = x + 2 * (panel_w + gap)
        disk_x = x + 3 * (panel_w + gap)
        self.draw_rate_split_panel(
            y,
            net_x,
            height,
            panel_w,
            "Net ↓%s ↑%s %s" % (format_bytes_per_sec(namespace.net_rx_bps), format_bytes_per_sec(namespace.net_tx_bps), self.rate_scale_title(net_scale)),
            "rx",
            namespace.net_rx_history,
            namespace.net_rx_bps,
            "tx",
            namespace.net_tx_history,
            namespace.net_tx_bps,
            net_scale,
        )
        self.draw_rate_split_panel(
            y,
            disk_x,
            height,
            width - 3 * (panel_w + gap),
            "Disk R:%s W:%s %s" % (format_bytes_per_sec(namespace.fs_read_bps), format_bytes_per_sec(namespace.fs_write_bps), self.rate_scale_title(io_scale)),
            "r",
            namespace.fs_read_history,
            namespace.fs_read_bps,
            "w",
            namespace.fs_write_history,
            namespace.fs_write_bps,
            io_scale,
        )

    def draw_node_detail(self, y: int, x: int, height: int, width: int) -> None:
        node = self.find_node(self.current_node)
        if not node:
            self.box(y, x, height, width, "Node Detail", focused=False)
            self.add(y + 2, x + 2, "Node not found", self.colors.get("red", 0))
            return
        if height < 28:
            self.draw_node_detail_compact(y, x, height, width, node)
            return

        self.box(y, x, height, width, "Nodes > %s" % node.name, focused=True)
        inner_x = x + 1
        inner_w = width - 2
        info_y = y + 1
        metrics_y = info_y + 3
        system_y = metrics_y + METRIC_PANEL_HEIGHT
        system_h = 13 if height >= 38 else 11
        pods_y = system_y + system_h
        pods_h = max(6, y + height - pods_y - 1)

        self.draw_node_info_panel(info_y, inner_x, 3, inner_w, node)
        self.draw_node_metric_panels(metrics_y, inner_x, METRIC_PANEL_HEIGHT, inner_w, node)
        self.draw_node_system_detail(system_y, inner_x, system_h, inner_w, node)

        pods = [pod for pod in self.current_pods(ignore_namespace_filter=True) if pod.node == node.name]
        self.draw_table(
            pods_y,
            x + 1,
            pods_h,
            width - 2,
            "Pods (%d)" % len(pods),
            ["NAMESPACE", "NAME", "STATUS", "READY", "RESTARTS", "CPU", "MEM", "AGE"],
            pods,
            self.node_detail_pod_cell,
            "node_pods",
            ("", True),
            focused=True,
        )

    def draw_node_detail_compact(self, y: int, x: int, height: int, width: int, node: NodeRow) -> None:
        self.box(y, x, height, width, "Nodes > %s" % node.name, focused=True)
        info = "Status: %s | Roles: %s | Age: %s | IP: %s | Hostname: %s" % (
            node.status,
            ",".join(node.roles),
            human_age(node.creation_time),
            node.internal_ip,
            node.hostname,
        )
        self.add(y + 1, x + 2, info, 0, width - 4)
        pods = [pod for pod in self.current_pods(ignore_namespace_filter=True) if pod.node == node.name]
        self.draw_table(
            y + 3,
            x + 1,
            max(5, height - 4),
            width - 2,
            "Pods (%d)" % len(pods),
            ["NAMESPACE", "NAME", "STATUS", "READY", "RESTARTS", "CPU", "MEM", "AGE"],
            pods,
            self.node_detail_pod_cell,
            "node_pods",
            ("", True),
            focused=True,
        )

    def draw_node_info_panel(self, y: int, x: int, height: int, width: int, node: NodeRow) -> None:
        self.box(y, x, height, width, "Info", focused=False)
        line = "Status: %s | Roles: %s | Age: %s | IP: %s | Hostname: %s" % (
            node.status,
            ",".join(node.roles),
            human_age(node.creation_time),
            node.internal_ip,
            node.hostname,
        )
        self.add(y + 1, x + 2, line, 0, width - 4)

    def draw_node_metric_panels(self, y: int, x: int, height: int, width: int, node: NodeRow) -> None:
        gap = 1
        panel_w = max(10, (width - 3 * gap) // 4)
        cpu_value = self.display_usage(node.usage_cpu_m, node.requested_cpu_m, node.cpu_history)
        mem_value = self.display_usage(node.usage_mem_b, node.requested_mem_b, node.mem_history)
        net_scale = self.rate_pair_chart_scale(history_key_node(node.name, "net_split"), node.net_rx_history, node.net_rx_bps, node.net_tx_history, node.net_tx_bps)
        io_scale = self.rate_pair_chart_scale(history_key_node(node.name, "io_split"), node.fs_read_history, node.fs_read_bps, node.fs_write_history, node.fs_write_bps)
        usage_metrics = [
            (
                "CPU %s/%s (%4.1f%% used)" % (format_cpu_millis(cpu_value), format_cpu_millis(node.alloc_cpu_m), ratio(cpu_value, node.alloc_cpu_m) * 100),
                node.cpu_history,
                cpu_value,
                node.alloc_cpu_m,
                self.resource_attr(ratio(cpu_value, node.alloc_cpu_m)),
            ),
            (
                "MEM %s/%s (%4.1f%% used) %s" % (format_mib(mem_value), format_mib(node.alloc_mem_b), ratio(mem_value, node.alloc_mem_b) * 100, self.history_arrow(node.mem_history)),
                node.mem_history,
                mem_value,
                node.alloc_mem_b,
                self.resource_attr(ratio(mem_value, node.alloc_mem_b)),
            ),
        ]
        for idx, (title, history, current, total, attr) in enumerate(usage_metrics):
            panel_x = x + idx * (panel_w + gap)
            panel_width = panel_w
            self.draw_node_timeseries_panel(y, panel_x, height, panel_width, title, history, current, total, attr)
        net_x = x + 2 * (panel_w + gap)
        disk_x = x + 3 * (panel_w + gap)
        self.draw_rate_split_panel(
            y,
            net_x,
            height,
            panel_w,
            "Net ↓%s ↑%s %s" % (format_bytes_per_sec(node.net_rx_bps), format_bytes_per_sec(node.net_tx_bps), self.rate_scale_title(net_scale)),
            "rx",
            node.net_rx_history,
            node.net_rx_bps,
            "tx",
            node.net_tx_history,
            node.net_tx_bps,
            net_scale,
        )
        self.draw_rate_split_panel(
            y,
            disk_x,
            height,
            width - 3 * (panel_w + gap),
            "Disk R:%s W:%s %s" % (format_bytes_per_sec(node.fs_read_bps), format_bytes_per_sec(node.fs_write_bps), self.rate_scale_title(io_scale)),
            "r",
            node.fs_read_history,
            node.fs_read_bps,
            "w",
            node.fs_write_history,
            node.fs_write_bps,
            io_scale,
        )

    def draw_node_timeseries_panel(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        history: Sequence[float],
        current: float,
        total: float,
        attr: int,
    ) -> None:
        self.box(y, x, height, width, truncate(title, max(1, width - 4)), focused=False)
        self.draw_graph_rows(y + 1, x + 1, max(1, height - 2), max(1, width - 2), history, current, total, attr)

    def draw_node_system_detail(self, y: int, x: int, height: int, width: int, node: NodeRow) -> None:
        self.box(y, x, height, width, "System Detail", focused=False)
        col_w = max(18, (width - 4) // 4)
        columns = [
            ("System", self.node_system_rows(node)),
            ("Conditions", self.node_condition_rows(node)),
            ("Labels", self.node_metadata_rows(safe_get(node.raw, ["metadata", "labels"], {}) or {}, 8)),
            ("Annotations", self.node_metadata_rows(safe_get(node.raw, ["metadata", "annotations"], {}) or {}, 6)),
        ]
        for idx, (title, rows) in enumerate(columns):
            col_x = x + 2 + idx * col_w
            col_width = max(1, (x + width - 2) - col_x if idx == 3 else col_w - 1)
            self.add(y + 1, col_x, title, self.colors.get("cyan", 0), col_width)
            self.draw_detail_rows(y + 2, col_x, height - 3, col_width, rows)

    def draw_detail_rows(self, y: int, x: int, height: int, width: int, rows: Sequence[Tuple[str, str, int]]) -> None:
        label_w = max(8, min(18, width // 2 - 1))
        for idx, (label, value, attr) in enumerate(rows[: max(0, height)]):
            row_y = y + idx
            if label == "":
                self.add(row_y, x, value, self.colors.get("cyan", 0), width)
                continue
            self.add(row_y, x, truncate(label, label_w).ljust(label_w), 0, label_w)
            self.add(row_y, x + label_w + 1, truncate(value, max(1, width - label_w - 1)), attr, max(1, width - label_w - 1))

    def node_system_rows(self, node: NodeRow) -> List[Tuple[str, str, int]]:
        alloc_pods = safe_get(node.raw, ["status", "allocatable", "pods"], "-") or "-"
        cidr = safe_get(node.raw, ["spec", "podCIDR"]) or ",".join(safe_get(node.raw, ["spec", "podCIDRs"], []) or []) or "-"
        return [
            ("MachineID", safe_get(node.raw, ["status", "nodeInfo", "machineID"], "-") or "-", 0),
            ("OS", node.os_image, 0),
            ("Arch", node.arch, 0),
            ("Kernel", node.kernel, 0),
            ("Kubelet", node.kubelet, 0),
            ("Runtime", node.runtime, 0),
            ("Pods", "%d/%s" % (node.pods_count, alloc_pods), 0),
            ("Volumes", "%d/%d" % (node.volumes_in_use, node.volumes_attached), 0),
            ("CIDR", cidr, 0),
        ]

    def node_condition_rows(self, node: NodeRow) -> List[Tuple[str, str, int]]:
        conditions = {ctype: status for ctype, status, _ in node.conditions}
        ok = self.colors.get("green", 0)
        warn = self.colors.get("yellow", 0)
        bad = self.colors.get("red", 0)

        def pressure_attr(value: str) -> int:
            return bad if value == "True" else ok

        rows = [
            ("MemoryPressure", conditions.get("MemoryPressure", "-"), pressure_attr(conditions.get("MemoryPressure", "-"))),
            ("DiskPressure", conditions.get("DiskPressure", "-"), pressure_attr(conditions.get("DiskPressure", "-"))),
            ("PIDPressure", conditions.get("PIDPressure", "-"), pressure_attr(conditions.get("PIDPressure", "-"))),
            ("Ready", conditions.get("Ready", "-"), ok if conditions.get("Ready") == "True" else bad),
            ("Cordoned", "True" if node.unschedulable else "False", warn if node.unschedulable else ok),
            ("Taints", str(node.taints), warn if node.taints else ok),
            ("Pressures", ",".join(node.pressures) if node.pressures else "None", bad if node.pressures else ok),
            ("", "Events", self.colors.get("cyan", 0)),
            ("Total", str(len(self.events_for("Node", node.name, ""))), 0),
        ]
        return rows

    def node_metadata_rows(self, values: Dict[str, Any], limit: int) -> List[Tuple[str, str, int]]:
        rows = []
        for key in sorted(values)[:limit]:
            rows.append((self.short_metadata_key(key), str(values.get(key, "")), 0))
        return rows or [("-", "-", 0)]

    def short_metadata_key(self, key: str, width: int = 22) -> str:
        text = str(key)
        if len(text) <= width:
            return text
        return text[: max(1, width - 3)] + "..."

    def node_detail_pod_cell(self, pod: PodRow, col: str) -> Tuple[str, Optional[int]]:
        if col == "NAMESPACE":
            return pod.namespace, 0
        if col == "NAME":
            return pod.name, 0
        if col == "STATUS":
            return pod.status, self.status_attr(pod.status)
        if col == "READY":
            return "%d/%d" % (pod.ready, pod.total), 0
        if col == "RESTARTS":
            return str(pod.restarts), self.colors.get("yellow", 0) if pod.restarts else 0
        if col == "CPU":
            return format_cpu_millis(self.display_usage(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history)), 0
        if col == "MEM":
            return format_mib(self.display_usage(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history)), 0
        if col == "AGE":
            return human_age(pod.creation_time), 0
        return "-", None

    def draw_pod_detail(self, y: int, x: int, height: int, width: int) -> None:
        pod = self.find_pod(self.current_pod)
        if not pod:
            self.box(y, x, height, width, "Pod Detail", focused=False)
            self.add(y + 2, x + 2, "Pod not found", self.colors.get("red", 0))
            return
        if height < 28:
            self.draw_pod_detail_compact(y, x, height, width, pod)
            return

        self.box(y, x, height, width, "Pods > %s" % pod.name, focused=True)
        inner_x = x + 1
        inner_w = width - 2
        info_y = y + 1
        metrics_y = info_y + 3
        detail_y = metrics_y + METRIC_PANEL_HEIGHT
        detail_h = 13 if height >= 38 else 11
        containers_y = detail_y + detail_h
        containers_h = max(6, y + height - containers_y - 1)

        self.draw_pod_info_panel(info_y, inner_x, 3, inner_w, pod)
        self.draw_pod_metric_panels(metrics_y, inner_x, METRIC_PANEL_HEIGHT, inner_w, pod)
        self.draw_pod_detail_panel(detail_y, inner_x, detail_h, inner_w, pod)
        self.draw_table(
            containers_y,
            x + 1,
            containers_h,
            width - 2,
            "Containers (%d) - Enter/l: logs" % len(pod.containers),
            ["NAME", "IMAGE", "STATE", "READY", "RESTARTS", "CPU", "MEM"],
            pod.containers,
            self.pod_detail_container_cell,
            "containers",
            ("", True),
            focused=True,
        )

    def draw_pod_detail_compact(self, y: int, x: int, height: int, width: int, pod: PodRow) -> None:
        self.box(y, x, height, width, "Pods > %s" % pod.name, focused=True)
        info = "Status: %s | Node: %s | NS: %s | IP: %s | Age: %s | Restarts: %d" % (
            pod.status,
            pod.node,
            pod.namespace,
            pod.ip,
            human_age(pod.creation_time),
            pod.restarts,
        )
        self.add(y + 1, x + 2, info, 0, width - 4)
        self.draw_table(
            y + 3,
            x + 1,
            max(5, height - 4),
            width - 2,
            "Containers (%d) - Enter/l: logs" % len(pod.containers),
            ["NAME", "IMAGE", "STATE", "READY", "RESTARTS", "CPU", "MEM"],
            pod.containers,
            self.pod_detail_container_cell,
            "containers",
            ("", True),
            focused=True,
        )

    def draw_pod_info_panel(self, y: int, x: int, height: int, width: int, pod: PodRow) -> None:
        self.box(y, x, height, width, "Info", focused=False)
        line = "Status: %s | Node: %s | NS: %s | IP: %s | Age: %s | Restarts: %d" % (
            pod.status,
            pod.node,
            pod.namespace,
            pod.ip,
            human_age(pod.creation_time),
            pod.restarts,
        )
        self.add(y + 1, x + 2, line, 0, width - 4)

    def draw_pod_metric_panels(self, y: int, x: int, height: int, width: int, pod: PodRow) -> None:
        gap = 1
        panel_w = max(10, (width - 3 * gap) // 4)
        cpu_value = self.display_usage(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history)
        mem_value = self.display_usage(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history)
        net_scale = self.rate_pair_chart_scale(history_key_pod(pod.namespace, pod.name, "net_split"), pod.net_rx_history, pod.net_rx_bps, pod.net_tx_history, pod.net_tx_bps)
        io_scale = self.rate_pair_chart_scale(history_key_pod(pod.namespace, pod.name, "io_split"), pod.fs_read_history, pod.fs_read_bps, pod.fs_write_history, pod.fs_write_bps)
        usage_metrics = [
            (
                "CPU %s/%s (%4.1f%% used) %s"
                % (format_cpu_millis(cpu_value), format_cpu_millis(pod.node_alloc_cpu_m), ratio(cpu_value, pod.node_alloc_cpu_m) * 100, self.history_arrow(pod.cpu_history)),
                pod.cpu_history,
                cpu_value,
                pod.node_alloc_cpu_m,
                self.resource_attr(ratio(cpu_value, pod.node_alloc_cpu_m)),
            ),
            (
                "MEM %s/%s (%4.1f%% used)" % (format_mib(mem_value), format_mib(pod.node_alloc_mem_b), ratio(mem_value, pod.node_alloc_mem_b) * 100),
                pod.mem_history,
                mem_value,
                pod.node_alloc_mem_b,
                self.resource_attr(ratio(mem_value, pod.node_alloc_mem_b)),
            ),
        ]
        for idx, (title, history, current, total, attr) in enumerate(usage_metrics):
            panel_x = x + idx * (panel_w + gap)
            panel_width = panel_w
            self.draw_node_timeseries_panel(y, panel_x, height, panel_width, title, history, current, total, attr)
        net_x = x + 2 * (panel_w + gap)
        disk_x = x + 3 * (panel_w + gap)
        net_title = (
            "Net ↓%s ↑%s %s" % (format_bytes_per_sec(pod.net_rx_bps), format_bytes_per_sec(pod.net_tx_bps), self.rate_scale_title(net_scale))
            if pod.net_rx_bps or pod.net_tx_bps or pod.net_rx_history or pod.net_tx_history
            else "Net (unavailable) %s" % self.rate_scale_title(net_scale)
        )
        self.draw_rate_split_panel(
            y,
            net_x,
            height,
            panel_w,
            net_title,
            "rx",
            pod.net_rx_history,
            pod.net_rx_bps,
            "tx",
            pod.net_tx_history,
            pod.net_tx_bps,
            net_scale,
        )
        self.draw_rate_split_panel(
            y,
            disk_x,
            height,
            width - 3 * (panel_w + gap),
            "Disk R:%s W:%s %s" % (format_bytes_per_sec(pod.fs_read_bps), format_bytes_per_sec(pod.fs_write_bps), self.rate_scale_title(io_scale)),
            "r",
            pod.fs_read_history,
            pod.fs_read_bps,
            "w",
            pod.fs_write_history,
            pod.fs_write_bps,
            io_scale,
        )

    def draw_pod_detail_panel(self, y: int, x: int, height: int, width: int, pod: PodRow) -> None:
        self.box(y, x, height, width, "Pod Detail", focused=False)
        col_w = max(24, (width - 4) // 3)
        left_x = x + 2
        middle_x = left_x + col_w
        right_x = middle_x + col_w
        right_w = max(1, x + width - 2 - right_x)
        self.add(y + 1, left_x, "Pod Info", self.colors.get("cyan", 0), col_w - 1)
        self.draw_detail_rows(y + 2, left_x, height - 3, col_w - 1, self.pod_info_rows(pod))
        self.add(y + 1, middle_x, "Conditions", self.colors.get("cyan", 0), col_w - 1)
        self.draw_detail_rows(y + 2, middle_x, height - 3, col_w - 1, self.pod_condition_resource_rows(pod))
        self.add(y + 1, right_x, "Labels", self.colors.get("cyan", 0), right_w)
        label_rows = self.pod_metadata_rows(safe_get(pod.raw, ["metadata", "labels"], {}) or {}, max(2, (height - 4) // 2))
        self.draw_detail_rows(y + 2, right_x, max(1, len(label_rows)), right_w, label_rows)
        annotations_y = y + 3 + len(label_rows)
        if annotations_y < y + height - 1:
            self.add(annotations_y, right_x, "Annotations", self.colors.get("cyan", 0), right_w)
            self.draw_detail_rows(annotations_y + 1, right_x, y + height - annotations_y - 2, right_w, self.pod_metadata_rows(safe_get(pod.raw, ["metadata", "annotations"], {}) or {}, max(1, y + height - annotations_y - 2)))

    def pod_info_rows(self, pod: PodRow) -> List[Tuple[str, str, int]]:
        term_grace = safe_get(pod.raw, ["spec", "terminationGracePeriodSeconds"])
        return [
            ("Owner", owner_chain_text(pod.owner_chain), self.colors.get("cyan", 0) if pod.owner_chain else 0),
            ("ServiceAcct", safe_get(pod.raw, ["spec", "serviceAccountName"], "-") or "-", 0),
            ("Priority", str(safe_get(pod.raw, ["spec", "priority"], "-") or "-"), 0),
            ("QoS", safe_get(pod.raw, ["status", "qosClass"], "-") or "-", 0),
            ("DNSPolicy", safe_get(pod.raw, ["spec", "dnsPolicy"], "-") or "-", 0),
            ("RestartPol", safe_get(pod.raw, ["spec", "restartPolicy"], "-") or "-", 0),
            ("TermGrace", "%ss" % term_grace if term_grace is not None else "-", 0),
            ("ImgPull", self.image_pull_policy(pod), 0),
            ("Scheduler", safe_get(pod.raw, ["spec", "schedulerName"], "-") or "-", 0),
            ("Node", pod.node, 0),
        ]

    def pod_condition_resource_rows(self, pod: PodRow) -> List[Tuple[str, str, int]]:
        ok = self.colors.get("green", 0)
        bad = self.colors.get("red", 0)
        rows: List[Tuple[str, str, int]] = []
        for ctype, status, _ in pod.conditions:
            rows.append((ctype, status, ok if status == "True" else bad))
        rows.append(("", "Resources", self.colors.get("cyan", 0)))
        rows.append(("Requests", "%s / %s" % (format_resource_cpu(pod.requested_cpu_m), format_resource_mem(pod.requested_mem_b)), 0))
        cpu_limit = sum(container.cpu_limit_m for container in pod.containers)
        mem_limit = sum(container.mem_limit_b for container in pod.containers)
        rows.append(("Limits", "%s / %s" % (format_resource_cpu(cpu_limit), format_resource_mem(mem_limit)), 0))
        return rows

    def pod_metadata_rows(self, values: Dict[str, Any], limit: int) -> List[Tuple[str, str, int]]:
        rows = []
        for key in sorted(values)[:limit]:
            rows.append((self.short_metadata_key(key), str(values.get(key, "")), 0))
        return rows or [("-", "-", 0)]

    def image_pull_policy(self, pod: PodRow) -> str:
        policies = sorted(set(str(container.get("imagePullPolicy", "")) for container in safe_get(pod.raw, ["spec", "containers"], []) or [] if container.get("imagePullPolicy")))
        return ",".join(policies) if policies else "-"

    def pod_detail_container_cell(self, container: ContainerInfo, col: str) -> Tuple[str, Optional[int]]:
        if col == "NAME":
            return container.name, 0
        if col == "IMAGE":
            return container.image, 0
        if col == "STATE":
            return container.status, self.status_attr(container.status)
        if col == "READY":
            return "Yes" if container.ready else "No", self.colors.get("green", 0) if container.ready else self.colors.get("red", 0)
        if col == "RESTARTS":
            return str(container.restarts), self.colors.get("yellow", 0) if container.restarts else 0
        if col == "CPU":
            return format_cpu_millis(container.usage_cpu_m), 0
        if col == "MEM":
            return format_mib(container.usage_mem_b), 0
        return "-", None

    def container_cell(self, container: ContainerInfo, col: str) -> Tuple[str, Optional[int]]:
        if col == "CONTAINER":
            return container.name, None
        if col == "STATUS":
            return container.status, self.status_attr(container.status)
        if col == "RST":
            return str(container.restarts), self.colors.get("yellow", 0) if container.restarts else None
        if col == "IMAGE":
            return container.image, None
        if col == "CPU USE":
            return self.trend_value(container.cpu_history, container.usage_cpu_m, format_mcpu), self.colors.get("cyan", 0) if container.usage_cpu_m or container.cpu_history else None
        if col == "MEM USE":
            return self.trend_value(container.mem_history, container.usage_mem_b, format_bytes), self.colors.get("cyan", 0) if container.usage_mem_b or container.mem_history else None
        if col == "CPU REQ":
            return format_mcpu(container.cpu_request_m), None
        if col == "MEM REQ":
            return format_bytes(container.mem_request_b), None
        if col == "CPU LIM":
            return format_mcpu(container.cpu_limit_m), None
        if col == "MEM LIM":
            return format_bytes(container.mem_limit_b), None
        if col == "PORTS":
            return container.ports, None
        if col == "MOUNTS":
            return str(container.mounts), None
        return "-", None

    def cronjob_info_rows(self, row: CronJobRow) -> List[Tuple[str, str, int]]:
        """Build CronJob info rows. / Формирует строки Info для CronJob."""
        return [
            ("Status", row.status, self.health_severity_attr(row.severity)),
            ("Schedule", row.schedule, 0),
            ("Timezone", row.timezone, 0),
            ("Suspended", "yes" if row.suspend else "no", self.colors.get("yellow", 0) if row.suspend else self.colors.get("green", 0)),
            ("Last", self.cronjob_time_text(row.last_schedule), 0),
            ("Next", self.cronjob_time_text(row.next_schedule, row.late_seconds), self.health_severity_attr(row.severity)),
            ("LastSuccess", self.cronjob_time_text(row.last_success), self.colors.get("green", 0) if row.last_success else 0),
            ("Hint", row.hint, self.health_severity_attr(row.severity)),
        ]

    def cronjob_sla_rows(self, row: CronJobRow) -> List[Tuple[str, str, int]]:
        """Build CronJob SLA rows. / Формирует строки SLA для CronJob."""
        return [
            ("Active", str(row.active), self.colors.get("yellow", 0) if row.active else self.colors.get("green", 0)),
            ("Succeeded", str(row.succeeded), self.colors.get("green", 0)),
            ("Failed", str(row.failed), self.colors.get("red", 0) if row.failed else self.colors.get("green", 0)),
            ("Late", format_duration_compact(row.late_seconds) if row.late_seconds else "-", self.health_severity_attr(row.severity) if row.late_seconds else 0),
            ("P50", format_duration_compact(row.p50_s), 0),
            ("P95", format_duration_compact(row.p95_s), 0),
            ("P99", format_duration_compact(row.p99_s), 0),
            ("LatestJob", row.latest_job, self.status_attr(row.latest_status)),
            ("LatestState", row.latest_status, self.status_attr(row.latest_status)),
        ]

    def cronjob_context_rows(self, row: CronJobRow, max_rows: int) -> List[Tuple[str, str, int]]:
        """Build suggestions/events/job context rows. / Формирует строки подсказок/events/job context."""
        rows: List[Tuple[str, str, int]] = []
        for suggestion in row.suggestions:
            rows.append(("Suggest", suggestion, self.colors.get("yellow", 0)))
        runs = self.cronjob_runs(row)
        if runs:
            rows.append(("", "Recent Jobs", self.colors.get("cyan", 0)))
            for run in runs[:3]:
                started = human_age(run.start_time)
                duration = format_duration_compact(run.duration_s)
                value = "%s status=%s dur=%s" % (truncate(run.name, 28), run.status, duration)
                rows.append((started, value, self.status_attr(run.status)))
        events = self.cronjob_events(row)
        if events:
            rows.append(("", "Events", self.colors.get("cyan", 0)))
            for event in events[: max(1, max_rows - len(rows))]:
                value = "%s %s" % (event.reason or event.event_type or "-", truncate(event.message, 70))
                rows.append((human_age(event.timestamp), value, self.colors.get("yellow", 0) if event.event_type == "Warning" else 0))
        return rows[:max_rows] or [("-", "No related events or suggestions.", self.colors.get("green", 0))]

    def draw_cronjob_detail(self, y: int, x: int, height: int, width: int) -> None:
        """Draw CronJob detail screen. / Рисует экран деталей CronJob."""
        row = self.find_cronjob(self.current_cronjob)
        if not row:
            self.box(y, x, height, width, "CronJob Detail", focused=False)
            self.add(y + 2, x + 2, "CronJob not found", self.colors.get("red", 0))
            return
        related_pods = self.cronjob_related_pods(row)
        if height < 18:
            self.box(y, x, height, width, "CronJobs > %s" % row.name, focused=True)
            lines = [
                "Status: %s | Schedule: %s | Last: %s | Next: %s"
                % (row.status, row.schedule, self.cronjob_time_text(row.last_schedule), self.cronjob_time_text(row.next_schedule, row.late_seconds)),
                "SLA: active=%d ok=%d fail=%d p50=%s p95=%s p99=%s"
                % (row.active, row.succeeded, row.failed, format_duration_compact(row.p50_s), format_duration_compact(row.p95_s), format_duration_compact(row.p99_s)),
                "Hint: %s" % row.hint,
            ]
            for idx, line in enumerate(lines[: max(0, height - 2)]):
                self.add(y + 1 + idx, x + 2, line, self.health_severity_attr(row.severity), width - 4)
            return

        self.box(y, x, height, width, "CronJobs > %s" % row.name, focused=True)
        inner_x = x + 1
        inner_w = width - 2
        detail_h = min(13, max(9, height // 3))
        table_y = y + detail_h
        table_h = max(6, y + height - table_y - 1)
        self.box(y + 1, inner_x, detail_h - 1, inner_w, "Info / SLA / Context", focused=False)
        col_w = max(24, (inner_w - 4) // 3)
        info_x = inner_x + 2
        sla_x = info_x + col_w
        context_x = sla_x + col_w
        context_w = max(1, inner_x + inner_w - 2 - context_x)
        self.add(y + 2, info_x, "Info", self.colors.get("cyan", 0), col_w - 1)
        self.draw_detail_rows(y + 3, info_x, detail_h - 4, col_w - 1, self.cronjob_info_rows(row))
        self.add(y + 2, sla_x, "SLA", self.colors.get("cyan", 0), col_w - 1)
        self.draw_detail_rows(y + 3, sla_x, detail_h - 4, col_w - 1, self.cronjob_sla_rows(row))
        self.add(y + 2, context_x, "Context", self.colors.get("cyan", 0), context_w)
        self.draw_detail_rows(y + 3, context_x, detail_h - 4, context_w, self.cronjob_context_rows(row, detail_h - 4))
        self.draw_table(
            table_y,
            inner_x,
            table_h,
            inner_w,
            "Related Pods (%d) - Enter: pod detail" % len(related_pods),
            ["NAMESPACE", "POD", "STATUS", "READY", "RST", "AGE", "NODE", "CPU", "MEMORY"],
            related_pods,
            self.pod_cell,
            "cronjob_pods",
            self.pod_sort,
            focused=True,
        )

    def draw_events(self, y: int, x: int, height: int, width: int, title: str, events: Sequence[EventInfo]) -> None:
        if height < 4 or width < 20:
            return
        self.box(y, x, height, width, title, focused=False)
        for idx, event in enumerate(events[: max(0, height - 2)]):
            line = "%s %-8s %s" % (human_age(event.timestamp), event.reason or event.event_type, event.message)
            self.add(y + 1 + idx, x + 1, line, self.colors.get("yellow", 0) if event.event_type == "Warning" else 0, width - 2)

    def health_severity_attr(self, severity: str) -> int:
        """Return color for a health severity. / Возвращает цвет для severity health."""
        if severity == "critical":
            return self.colors.get("red", 0)
        if severity == "ok":
            return self.colors.get("green", 0)
        return self.colors.get("yellow", 0)

    def health_data(self) -> Optional[HealthData]:
        """Build structured Problems / Health data. / Формирует структурированные данные Problems / Health.

        Returns:
            HealthData for rendering, or None when no snapshot is loaded.
        """
        snap = self.snapshot
        if not snap:
            return None

        node_findings: List[Tuple[str, str]] = []
        for node in snap.nodes:
            reasons = []
            if node.status != "Ready":
                reasons.append(node.status)
            if node.pressures:
                reasons.append("pressure=%s" % ",".join(node.pressures))
            if node.unschedulable:
                reasons.append("cordoned")
            if node.taints:
                reasons.append("taints=%d" % node.taints)
            if reasons:
                severity = "critical" if node.status != "Ready" or node.pressures else "warning"
                node_findings.append(("%-5s %-14s %-44s %s" % ("NODE", "-", truncate(node.name, 44), ", ".join(reasons)), severity))

        bad_status = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "Pending", "Failed", "Evicted", "Error", "Unknown", "Terminating", "NotReady"}
        critical_pod_statuses = bad_status - {"Pending", "Terminating"}
        pod_findings: List[Tuple[str, str]] = []
        for pod in snap.pods:
            reasons = []
            if pod.status in bad_status:
                reasons.append(pod.status)
            if pod.total and pod.ready < pod.total and pod.status not in ("Completed",):
                reasons.append("ready=%d/%d" % (pod.ready, pod.total))
            if pod.restarts >= 5:
                reasons.append("restarts=%d" % pod.restarts)
            if reasons:
                owner = owner_chain_text(pod.owner_chain)
                severity = "critical" if pod.status in critical_pod_statuses else "warning"
                pod_findings.append(("%-5s %-14s %-44s %-24s owner=%s" % ("POD", truncate(pod.namespace, 14), truncate(pod.name, 44), ", ".join(reasons), owner), severity))

        workload_findings: List[Tuple[str, str]] = []
        healthy_workload_statuses = {"Ready", "Idle", "Complete", "Active", "ScaledDown"}
        for workload in sorted(snap.workloads.values(), key=lambda item: (item.namespace, item.kind, item.name)):
            if workload.status not in healthy_workload_statuses:
                severity = "critical" if workload.ready == 0 and workload.desired > 0 else "warning"
                workload_findings.append(
                    (
                        "%-5s %-14s %-44s status=%s ready=%d/%d updated=%d available=%d"
                    % (
                        truncate(workload.kind.upper(), 5),
                        truncate(workload.namespace, 14),
                        truncate(workload.name, 44),
                        workload.status,
                        workload.ready,
                        workload.desired,
                        workload.updated,
                        workload.available,
                    ),
                        severity,
                    )
                )

        cronjob_findings: List[Tuple[str, str]] = []
        for row in build_cronjob_rows(snap):
            if row.severity != "ok":
                cronjob_findings.append(
                    (
                        "%-5s %-14s %-44s status=%s next=%s late=%s p95=%s hint=%s"
                        % (
                            "CRON",
                            truncate(row.namespace, 14),
                            truncate(row.name, 44),
                            row.status,
                            isoformat_utc(row.next_schedule) or "-",
                            format_duration_compact(row.late_seconds) if row.late_seconds else "-",
                            format_duration_compact(row.p95_s),
                            truncate(row.hint, 80),
                        ),
                        row.severity,
                    )
                )

        event_findings: List[Tuple[str, str]] = []
        warning_events = [event for event in snap.events if event.event_type == "Warning"]
        for event in warning_events:
            where = "%s/%s" % (event.kind or "-", event.name or "-")
            if event.namespace:
                where = "%s %s" % (event.namespace, where)
            event_findings.append(("%-5s %-14s %-44s %-16s %s" % ("EVT", human_age(event.timestamp), truncate(where, 44), event.reason or "-", truncate(event.message, 90)), "warning"))

        collection_warnings = [("WARN  %-14s %-44s %s" % ("collection", "-", warning), "warning") for warning in snap.warnings]
        resource_findings = self.health_resource_findings(snap)
        scheduling_findings = self.health_scheduling_findings(snap)
        return HealthData(
            loaded_at=snap.loaded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            metrics_status=snap.metrics_status,
            node_findings=node_findings,
            pod_findings=pod_findings,
            workload_findings=workload_findings,
            cronjob_findings=cronjob_findings,
            event_findings=event_findings,
            collection_warnings=collection_warnings,
            resource_findings=resource_findings,
            scheduling_findings=scheduling_findings,
        )

    def quota_quantity_value(self, resource: str, value: Any) -> float:
        """Parse a ResourceQuota value. / Разбирает значение ResourceQuota.

        Args:
            resource: Quota resource key.
            value: Kubernetes quantity.
        Returns:
            Numeric value in millicores, bytes, or raw count.
        """
        if resource.endswith("cpu") or resource == "cpu":
            return parse_cpu_millis(value)
        if resource.endswith("memory") or resource == "memory":
            return parse_bytes(value)
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def quota_quantity_text(self, resource: str, value: float) -> str:
        """Format a ResourceQuota value. / Форматирует значение ResourceQuota."""
        if resource.endswith("cpu") or resource == "cpu":
            return format_mcpu(value)
        if resource.endswith("memory") or resource == "memory":
            return format_bytes(value)
        return str(int(value))

    def resource_pair_text(self, values: Dict[str, Any]) -> str:
        """Format CPU and memory resource dict. / Форматирует CPU и memory resource dict."""
        if not values:
            return "-"
        parts = []
        if values.get("cpu") is not None:
            parts.append("cpu=%s" % format_mcpu(parse_cpu_millis(values.get("cpu"))))
        if values.get("memory") is not None:
            parts.append("mem=%s" % format_bytes(parse_bytes(values.get("memory"))))
        return ",".join(parts) if parts else "-"

    def health_quota_findings(self, snap: ClusterSnapshot) -> List[Tuple[str, str]]:
        """Build ResourceQuota rows. / Формирует строки ResourceQuota.

        Args:
            snap: Current cluster snapshot.
        Returns:
            Quota rows with severity based on used/hard ratio.
        """
        rows: List[Tuple[str, str]] = []
        preferred = ["requests.cpu", "requests.memory", "limits.cpu", "limits.memory", "cpu", "memory", "pods"]
        for quota in snap.resource_quotas:
            namespace = safe_get(quota, ["metadata", "namespace"], "-") or "-"
            name = safe_get(quota, ["metadata", "name"], "-") or "-"
            hard = safe_get(quota, ["status", "hard"], {}) or {}
            used = safe_get(quota, ["status", "used"], {}) or {}
            keys = [key for key in preferred if key in hard]
            keys.extend(sorted(key for key in hard if key not in keys and ("cpu" in key or "memory" in key or key == "pods")))
            for resource in keys:
                hard_value = self.quota_quantity_value(resource, hard.get(resource))
                if hard_value <= 0:
                    continue
                used_value = self.quota_quantity_value(resource, used.get(resource))
                pct = ratio(used_value, hard_value) * 100.0
                severity = "critical" if pct >= 98.0 else "warning" if pct >= 80.0 else "ok"
                line = "%-5s %-36s %-18s used=%-9s hard=%-9s %5.1f%%" % (
                    "QUOTA",
                    truncate("%s/%s" % (namespace, name), 36),
                    truncate(resource, 18),
                    self.quota_quantity_text(resource, used_value),
                    self.quota_quantity_text(resource, hard_value),
                    pct,
                )
                rows.append((line, severity))
        return rows

    def health_limitrange_findings(self, snap: ClusterSnapshot) -> List[Tuple[str, str]]:
        """Build LimitRange policy rows. / Формирует строки LimitRange policy."""
        rows: List[Tuple[str, str]] = []
        for limitrange in snap.limit_ranges:
            namespace = safe_get(limitrange, ["metadata", "namespace"], "-") or "-"
            name = safe_get(limitrange, ["metadata", "name"], "-") or "-"
            limits = safe_get(limitrange, ["spec", "limits"], []) or []
            if not limits:
                rows.append(("LRNG  %-36s %-18s no limit items" % (truncate("%s/%s" % (namespace, name), 36), "-"), "warning"))
                continue
            for item in limits:
                limit_type = item.get("type", "-") or "-"
                pieces = [
                    "defaultReq=%s" % self.resource_pair_text(item.get("defaultRequest", {}) or {}),
                    "default=%s" % self.resource_pair_text(item.get("default", {}) or {}),
                    "min=%s" % self.resource_pair_text(item.get("min", {}) or {}),
                    "max=%s" % self.resource_pair_text(item.get("max", {}) or {}),
                ]
                ratio_values = item.get("maxLimitRequestRatio", {}) or {}
                if ratio_values:
                    pieces.append("maxRatio=%s" % ",".join("%s=%s" % (key, value) for key, value in sorted(ratio_values.items())))
                line = "%-5s %-36s %-18s %s" % (
                    "LRNG",
                    truncate("%s/%s" % (namespace, name), 36),
                    truncate(limit_type, 18),
                    " ".join(piece for piece in pieces if not piece.endswith("=-")),
                )
                rows.append((line, "ok"))
        return rows

    def toleration_matches_taint(self, toleration: Dict[str, Any], taint: Dict[str, Any]) -> bool:
        """Return whether one toleration matches one taint. / Проверяет toleration против taint."""
        taint_key = str(taint.get("key", ""))
        taint_value = str(taint.get("value", ""))
        taint_effect = str(taint.get("effect", ""))
        tol_key = str(toleration.get("key", ""))
        tol_value = str(toleration.get("value", ""))
        tol_effect = str(toleration.get("effect", ""))
        operator = str(toleration.get("operator", "Equal") or "Equal")
        if tol_effect and tol_effect != taint_effect:
            return False
        if operator == "Exists":
            return not tol_key or tol_key == taint_key
        return tol_key == taint_key and tol_value == taint_value

    def pod_tolerates_node_taints(self, pod: PodRow, node: NodeRow) -> Tuple[bool, int]:
        """Check blocking node taints. / Проверяет блокирующие taints узла."""
        tolerations = safe_get(pod.raw, ["spec", "tolerations"], []) or []
        blocking = 0
        for taint in safe_get(node.raw, ["spec", "taints"], []) or []:
            if taint.get("effect") not in ("NoSchedule", "NoExecute"):
                continue
            if not any(self.toleration_matches_taint(toleration, taint) for toleration in tolerations):
                blocking += 1
        return blocking == 0, blocking

    def node_requirement_matches(self, source: Dict[str, str], requirement: Dict[str, Any]) -> bool:
        """Evaluate one node selector requirement. / Проверяет одно node selector требование."""
        key = str(requirement.get("key", ""))
        operator = str(requirement.get("operator", "In") or "In")
        values = [str(value) for value in requirement.get("values", []) or []]
        present = key in source
        value = source.get(key, "")
        if operator == "In":
            return present and value in values
        if operator == "NotIn":
            return (not present) or value not in values
        if operator == "Exists":
            return present
        if operator == "DoesNotExist":
            return not present
        if operator in ("Gt", "Lt"):
            try:
                left = int(value)
                right = int(values[0])
            except (TypeError, ValueError, IndexError):
                return False
            return left > right if operator == "Gt" else left < right
        return False

    def node_selector_matches(self, pod: PodRow, node: NodeRow) -> bool:
        """Check pod nodeSelector against node labels. / Проверяет nodeSelector pod против labels node."""
        labels = safe_get(node.raw, ["metadata", "labels"], {}) or {}
        selector = safe_get(pod.raw, ["spec", "nodeSelector"], {}) or {}
        return all(str(labels.get(key, "")) == str(value) for key, value in selector.items())

    def node_field_values(self, node: NodeRow) -> Dict[str, str]:
        """Return supported node field selector values. / Возвращает поддержанные node field values."""
        return {
            "metadata.name": node.name,
            "metadata.namespace": "",
        }

    def node_affinity_matches(self, pod: PodRow, node: NodeRow) -> bool:
        """Check required node affinity. / Проверяет required node affinity."""
        required = safe_get(pod.raw, ["spec", "affinity", "nodeAffinity", "requiredDuringSchedulingIgnoredDuringExecution"], {}) or {}
        terms = required.get("nodeSelectorTerms", []) or []
        if not terms:
            return True
        labels = safe_get(node.raw, ["metadata", "labels"], {}) or {}
        fields = self.node_field_values(node)
        for term in terms:
            expressions = term.get("matchExpressions", []) or []
            match_fields = term.get("matchFields", []) or []
            if all(self.node_requirement_matches(labels, expr) for expr in expressions) and all(self.node_requirement_matches(fields, expr) for expr in match_fields):
                return True
        return False

    def pod_feasible_on_node(self, pod: PodRow, node: NodeRow, include_resources: bool = True) -> Tuple[bool, List[str]]:
        """Approximate scheduler feasibility for a pod/node pair. / Приближенно проверяет планируемость pod на node.

        Args:
            pod: Pod to test.
            node: Candidate node.
            include_resources: Whether to check remaining CPU and memory requests.
        Returns:
            Tuple of feasibility and blocking reason labels.
        """
        reasons = []
        if node.status != "Ready":
            reasons.append("not-ready")
        if node.unschedulable:
            reasons.append("cordoned")
        if not self.node_selector_matches(pod, node):
            reasons.append("selector")
        if not self.node_affinity_matches(pod, node):
            reasons.append("affinity")
        taints_ok, blocking_taints = self.pod_tolerates_node_taints(pod, node)
        if not taints_ok:
            reasons.append("taints:%d" % blocking_taints)
        if include_resources:
            available_cpu = max(0.0, node.alloc_cpu_m - node.requested_cpu_m)
            available_mem = max(0.0, node.alloc_mem_b - node.requested_mem_b)
            if pod.node == node.name:
                available_cpu += pod.requested_cpu_m
                available_mem += pod.requested_mem_b
            if pod.requested_cpu_m > available_cpu:
                reasons.append("cpu")
            if pod.requested_mem_b > available_mem:
                reasons.append("memory")
        return not reasons, reasons

    def reason_summary(self, blocked_reasons: Sequence[Sequence[str]]) -> str:
        """Summarize scheduler block reasons. / Суммирует причины блокировки scheduler."""
        counts: Dict[str, int] = {}
        for reasons in blocked_reasons:
            for reason in reasons:
                key = reason.split(":", 1)[0]
                counts[key] = counts.get(key, 0) + 1
        return ",".join("%s:%d" % (key, counts[key]) for key in sorted(counts)) or "-"

    def health_scheduling_findings(self, snap: ClusterSnapshot) -> List[Tuple[str, str]]:
        """Build approximate scheduler-fit rows. / Формирует строки приблизительной планируемости."""
        rows: List[Tuple[str, str]] = []
        nodes = snap.nodes
        node_by_name = {node.name: node for node in nodes}
        terminal_statuses = {"Succeeded", "Completed"}
        for pod in snap.pods:
            if pod.status in terminal_statuses:
                continue
            is_pending = pod.status in ("Pending", "Unknown") or pod.node == "-"
            feasible = []
            blocked: List[List[str]] = []
            for node in nodes:
                ok, reasons = self.pod_feasible_on_node(pod, node, include_resources=True)
                if ok:
                    feasible.append(node.name)
                else:
                    blocked.append(reasons)
            if is_pending:
                severity = "critical" if not feasible else "warning" if len(feasible) == 1 else "ok"
                line = "%-5s %-36s %-18s feasible=%d/%d nodes=%s req=%s/%s blocked=%s" % (
                    "SCHED",
                    truncate("%s/%s" % (pod.namespace, pod.name), 36),
                    pod.status,
                    len(feasible),
                    len(nodes),
                    truncate(",".join(feasible[:3]) or "-", 24),
                    format_mcpu(pod.requested_cpu_m),
                    format_bytes(pod.requested_mem_b),
                    self.reason_summary(blocked),
                )
                rows.append((line, severity))
            elif pod.node in node_by_name:
                ok, reasons = self.pod_feasible_on_node(pod, node_by_name[pod.node], include_resources=False)
                if not ok:
                    line = "%-5s %-36s %-18s current=%s violates=%s" % (
                        "SCHED",
                        truncate("%s/%s" % (pod.namespace, pod.name), 36),
                        "current-node",
                        truncate(pod.node, 24),
                        ",".join(reasons),
                    )
                    rows.append((line, "warning"))
        return rows

    def health_resource_findings(self, snap: ClusterSnapshot) -> List[Tuple[str, str]]:
        """Build resource saturation findings. / Формирует findings по насыщению ресурсов.

        Args:
            snap: Current cluster snapshot.
        Returns:
            Rows with severity for node and namespace resource pressure.
        """
        rows: List[Tuple[str, str]] = []
        node_limits: Dict[str, List[float]] = {}
        namespace_totals: Dict[str, List[float]] = {}
        for pod in snap.pods:
            pod_cpu = self.display_usage(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history)
            pod_mem = self.display_usage(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history)
            pod_limit_cpu = sum(container.cpu_limit_m for container in pod.containers)
            pod_limit_mem = sum(container.mem_limit_b for container in pod.containers)
            if pod.node and pod.node != "-":
                node_limits.setdefault(pod.node, [0.0, 0.0])
                node_limits[pod.node][0] += pod_limit_cpu
                node_limits[pod.node][1] += pod_limit_mem
            namespace_totals.setdefault(pod.namespace, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            values = namespace_totals[pod.namespace]
            values[0] += pod.requested_cpu_m
            values[1] += pod.requested_mem_b
            values[2] += pod_limit_cpu
            values[3] += pod_limit_mem
            values[4] += pod_cpu
            values[5] += pod_mem

        def resource_signal(resource: str, kind: str, value: float, total: float) -> Tuple[str, str]:
            if total <= 0 or value <= 0:
                return "ok", ""
            current = value / total
            if kind == "usage":
                if resource == "MEM":
                    if current >= 0.9:
                        return "critical", "mem usage %.0f%%" % (current * 100.0)
                    if current >= 0.75:
                        return "warning", "mem usage %.0f%%" % (current * 100.0)
                else:
                    if current >= 1.0:
                        return "warning", "cpu saturated %.0f%%" % (current * 100.0)
                    if current >= 0.9:
                        return "warning", "cpu usage %.0f%%" % (current * 100.0)
            elif kind == "request":
                if resource == "MEM":
                    if current >= 1.0:
                        return "critical", "mem requests %.0f%%" % (current * 100.0)
                    if current >= 0.8:
                        return "warning", "mem requests %.0f%%" % (current * 100.0)
                else:
                    if current >= 0.9:
                        return "warning", "cpu requests %.0f%%" % (current * 100.0)
            elif kind == "limit":
                if current > 1.0:
                    return "warning", "%s limit overcommit %.1fx" % (resource.lower(), current)
            return "ok", ""

        def add_resource_row(scope: str, name: str, resource: str, total: float, usage_value: float, request_value: float, limit_value: float, formatter: Any, extra: str = "") -> None:
            signal_values = [
                resource_signal(resource, "usage", usage_value, total),
                resource_signal(resource, "request", request_value, total),
                resource_signal(resource, "limit", limit_value, total),
            ]
            severities = [item[0] for item in signal_values]
            notes = [item[1] for item in signal_values if item[1]]
            if "critical" in severities:
                severity = "critical"
            elif "warning" in severities:
                severity = "warning"
            else:
                return
            note = "; ".join(notes)
            if extra:
                note = ("%s; %s" % (extra, note)) if note else extra
            line = "%-5s %-36s %-4s cap=%-8s use=%-8s req=%-8s lim=%-8s %s" % (
                scope,
                truncate(name, 36),
                resource,
                formatter(total),
                formatter(usage_value),
                formatter(request_value),
                formatter(limit_value) if limit_value > 0 else "-",
                note,
            )
            rows.append((line, severity))

        for node in snap.nodes:
            limit_cpu, limit_mem = node_limits.get(node.name, [0.0, 0.0])
            extra = "taints=%d" % node.taints if node.taints else ""
            add_resource_row("NODE", node.name, "CPU", node.alloc_cpu_m, self.display_usage(node.usage_cpu_m, node.requested_cpu_m, node.cpu_history), node.requested_cpu_m, limit_cpu, format_mcpu, extra)
            add_resource_row("NODE", node.name, "MEM", node.alloc_mem_b, self.display_usage(node.usage_mem_b, node.requested_mem_b, node.mem_history), node.requested_mem_b, limit_mem, format_bytes, extra)

        cluster_cpu = sum(node.alloc_cpu_m for node in snap.nodes)
        cluster_mem = sum(node.alloc_mem_b for node in snap.nodes)
        for namespace, values in sorted(namespace_totals.items()):
            req_cpu, req_mem, limit_cpu, limit_mem, use_cpu, use_mem = values
            add_resource_row("NS", namespace, "CPU", cluster_cpu, use_cpu, req_cpu, limit_cpu, format_mcpu, "share of cluster")
            add_resource_row("NS", namespace, "MEM", cluster_mem, use_mem, req_mem, limit_mem, format_bytes, "share of cluster")
        rows.extend(self.health_quota_findings(snap))
        rows.extend(self.health_limitrange_findings(snap))
        return rows

    def health_lines(self) -> List[str]:
        """Build Problems / Health page lines. / Формирует строки страницы Problems / Health.

        Returns:
            Human-readable health findings.
        """
        data = self.health_data()
        if not data:
            return ["No cluster data loaded yet."]

        lines = [
            "Problems / Health",
            "Loaded: %s | Metrics: %s" % (data.loaded_at, data.metrics_status),
            "",
        ]

        def append_section(title: str, rows: Sequence[Tuple[str, str]], limit: int) -> None:
            lines.append(title)
            if rows:
                for text, _severity in rows[:limit]:
                    lines.append("  %s" % text)
                if len(rows) > limit:
                    lines.append("  ... %d more finding(s)" % (len(rows) - limit))
            else:
                lines.append("  No findings.")
            lines.append("")

        append_section("Nodes", data.node_findings, 50)
        append_section("Pods", data.pod_findings, 50)
        append_section("Workloads", data.workload_findings, 40)
        append_section("CronJobs", data.cronjob_findings, 40)
        append_section("Warning Events", data.event_findings, 30)
        append_section("Resource Pressure", data.resource_findings, 50)
        append_section("Scheduling Fit", data.scheduling_findings, 50)
        append_section("Collection Warnings", data.collection_warnings, 20)
        resource_problems = [row for row in data.resource_findings if row[1] != "ok"]
        scheduling_problems = [row for row in data.scheduling_findings if row[1] != "ok"]
        if not any((data.node_findings, data.pod_findings, data.workload_findings, data.cronjob_findings, data.event_findings, resource_problems, scheduling_problems, data.collection_warnings)):
            lines.append("No obvious problems found in loaded snapshot.")
        return lines

    def draw_health_rows_panel(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        key: str,
        header: str,
        rows: Sequence[Tuple[str, str]],
        empty_text: str,
    ) -> None:
        """Draw a scrollable Problems / Health panel. / Рисует прокручиваемую панель Problems / Health.

        Args:
            y: Top row.
            x: Left column.
            height: Panel height.
            width: Panel width.
            title: Panel title.
            key: Scroll/hscroll state key.
            header: Virtual table header.
            rows: Text rows with severity values.
            empty_text: Message shown when rows are empty.
        """
        self.box(y, x, height, width, title, focused=self.health_focus == key)
        if height < 4 or width < 4:
            return
        inner_w = max(1, width - 2)
        data_h = max(0, height - 3)
        if not hasattr(self, "health_panel_visible"):
            self.health_panel_visible = {}
        self.health_panel_visible[key] = data_h
        total_w = max([len(header), len(empty_text)] + [len(text) for text, _severity in rows])
        max_hscroll = max(0, total_w - inner_w)
        hscroll = max(0, min(max_hscroll, self.hscroll.get(key, 0)))
        self.hscroll[key] = hscroll

        def slice_virtual(text: str) -> str:
            return text.ljust(total_w)[hscroll : hscroll + inner_w].ljust(inner_w)

        self.add(y + 1, x + 1, slice_virtual(header), self.colors.get("black_on_cyan", curses.A_REVERSE), inner_w)
        if not rows:
            self.scroll[key] = 0
            self.add(y + 2, x + 1, slice_virtual(empty_text), self.colors.get("green", 0), inner_w)
        else:
            max_scroll = max(0, len(rows) - data_h)
            scroll = max(0, min(max_scroll, self.scroll.get(key, 0)))
            self.scroll[key] = scroll
            for idx, (text, severity) in enumerate(rows[scroll : scroll + data_h], start=scroll):
                self.add(y + 2 + idx - scroll, x + 1, slice_virtual(text), self.health_severity_attr(severity), inner_w)

        indicators = []
        if len(rows) > data_h and data_h > 0:
            scroll = self.scroll.get(key, 0)
            indicators.append("%d-%d/%d" % (scroll + 1, min(len(rows), scroll + data_h), len(rows)))
        if max_hscroll > 0:
            indicators.append("cols %d-%d/%d" % (hscroll + 1, min(total_w, hscroll + inner_w), total_w))
        if indicators:
            indicator = " | ".join(indicators)
            self.add(y + height - 1, max(x + 1, x + width - len(indicator) - 2), indicator, curses.A_BOLD, len(indicator))

    def health_runtime_panel_rows(self, data: HealthData) -> Tuple[str, List[Tuple[str, str]], str]:
        """Build runtime health panel rows. / Формирует строки runtime панели health."""
        header = "%-5s %-14s %-44s %s" % ("KIND", "NAMESPACE", "NAME", "REASON")
        return header, data.node_findings + data.pod_findings, "No node or pod runtime problems found."

    def health_workload_panel_rows(self, data: HealthData) -> Tuple[str, List[Tuple[str, str]], str]:
        """Build workload and event health panel rows. / Формирует строки панели workloads/events."""
        header = "%-5s %-14s %-44s %s" % ("KIND", "NAMESPACE/AGE", "NAME/WHERE", "STATUS / MESSAGE")
        return header, data.workload_findings + data.cronjob_findings + data.event_findings, "No workload, CronJob, or warning event findings."

    def health_resource_panel_rows(self, data: HealthData) -> Tuple[str, List[Tuple[str, str]], str]:
        """Build resource pressure health panel rows. / Формирует строки панели resource pressure."""
        header = "%-5s %-36s %-4s %-8s %-12s %-12s %-12s %s" % ("SCOPE", "NAME", "RES", "CAP", "USAGE", "REQUEST", "LIMIT", "NOTE")
        return header, data.resource_findings + data.scheduling_findings + data.collection_warnings, "No resource pressure, scheduling, or collection warnings."

    def health_panel_rows(self, key: str, data: HealthData) -> Tuple[str, List[Tuple[str, str]], str]:
        """Return rows for the requested Health panel. / Возвращает строки выбранной панели Health."""
        if key == "health_workloads":
            return self.health_workload_panel_rows(data)
        if key == "health_resources":
            return self.health_resource_panel_rows(data)
        return self.health_runtime_panel_rows(data)

    def health_panel_row_count(self, key: str, data: Optional[HealthData]) -> int:
        """Return scrollable row count for a Health panel. / Возвращает число строк панели Health."""
        if not data:
            return 0
        _header, rows, _empty = self.health_panel_rows(key, data)
        return len(rows)

    def draw_health(self, y: int, x: int, height: int, width: int) -> None:
        """Draw styled Problems / Health screen. / Рисует стилизованный экран Problems / Health."""
        data = self.health_data()
        if not data:
            self.box(y, x, height, width, "Problems / Health", focused=True)
            self.add(y + 2, x + 2, "No cluster data loaded yet.", self.colors.get("yellow", 0), width - 4)
            return
        if height < 20 or width < 100:
            self.draw_text_page(y, x, height, width, "Problems / Health", self.health_lines(), "health")
            return

        self.box(y, x, height, width, "Problems / Health", focused=True)
        inner_x = x + 1
        inner_w = width - 2
        self.add(y + 1, inner_x + 1, "Loaded: %s | Metrics: %s" % (data.loaded_at, data.metrics_status), self.colors.get("yellow", 0), inner_w - 2)

        runtime_count = len(data.node_findings) + len(data.pod_findings)
        workload_count = len(data.workload_findings) + len(data.cronjob_findings) + len(data.event_findings)
        warnings_count = len(data.event_findings) + len(data.collection_warnings)
        resource_problem_count = len([row for row in data.resource_findings if row[1] != "ok"])
        scheduling_problem_count = len([row for row in data.scheduling_findings if row[1] != "ok"])
        summary_y = y + 2
        summary_h = 5
        gap = 1
        card_w = max(12, (inner_w - 3 * gap) // 4)
        cards = [
            ("Runtime", "nodes: %d\npods: %d" % (len(data.node_findings), len(data.pod_findings)), "", self.resource_risk_attr(runtime_count)),
            ("Workloads", "items: %d\ncron: %d" % (len(data.workload_findings), len(data.cronjob_findings)), "", self.resource_risk_attr(workload_count)),
            ("Resources", "pressure: %d\nsched: %d" % (resource_problem_count, scheduling_problem_count), "", self.resource_risk_attr(resource_problem_count + scheduling_problem_count)),
            ("Warnings", "events: %d\ncollect: %d" % (len(data.event_findings), len(data.collection_warnings)), "", self.resource_risk_attr(warnings_count)),
        ]
        for idx, (title, value, subtitle, attr) in enumerate(cards):
            card_x = inner_x + idx * (card_w + gap)
            card_width = max(12, x + width - 1 - card_x) if idx == len(cards) - 1 else card_w
            self.draw_resource_summary_card(summary_y, card_x, summary_h, card_width, title, value, subtitle, attr)

        bottom_h = max(7, min(11, height // 3))
        bottom_y = y + height - bottom_h - 1
        middle_y = summary_y + summary_h
        middle_h = max(6, bottom_y - middle_y)
        left_w = max(40, (inner_w - gap) // 2)
        right_x = inner_x + left_w + gap
        right_w = max(20, x + width - 1 - right_x)
        header, rows, empty = self.health_runtime_panel_rows(data)
        self.draw_health_rows_panel(middle_y, inner_x, middle_h, left_w, "Runtime", "health_runtime", header, rows, empty)
        header, rows, empty = self.health_workload_panel_rows(data)
        self.draw_health_rows_panel(middle_y, right_x, middle_h, right_w, "Workloads / Events", "health_workloads", header, rows, empty)
        header, rows, empty = self.health_resource_panel_rows(data)
        self.draw_health_rows_panel(bottom_y, inner_x, bottom_h, inner_w, "Resource Pressure / Collection", "health_resources", header, rows, empty)

    def resource_metric_value(self, usage: float, fallback: float, history: Sequence[float], metrics_available: bool) -> float:
        """Choose live usage or request fallback for resource summaries. / Выбирает live usage или request fallback.

        Args:
            usage: Current live usage value.
            fallback: Request value used when live metrics are missing.
            history: Retained live metric history.
            metrics_available: Whether the snapshot has live metrics.
        Returns:
            Numeric value suitable for top-consumer summaries.
        """
        if metrics_available and (usage > 0 or clean_metric_values(history)):
            return max(0.0, float(usage or 0.0))
        return max(0.0, float(fallback or 0.0))

    def resource_container_label(self, pod: PodRow, container: ContainerInfo) -> str:
        """Build a compact container identity. / Формирует компактное имя контейнера."""
        return "%-12s %-38s %-18s" % (pod.namespace, truncate(pod.name, 38), truncate(container.name, 18))

    def resource_risk_data(self) -> Optional[ResourceRiskData]:
        """Build structured Resource Risk data. / Формирует структурированные данные Resource Risk.

        Returns:
            ResourceRiskData for rendering, or None when no snapshot is loaded.
        """
        snap = self.snapshot
        if not snap:
            return None

        containers = [(pod, container) for pod in snap.pods for container in pod.containers]
        missing_requests_rows: List[Tuple[PodRow, ContainerInfo, str, str]] = []
        missing_limits_rows: List[Tuple[PodRow, ContainerInfo, str, str]] = []
        ratio_findings: List[Tuple[float, str, str, PodRow, ContainerInfo, str, str]] = []
        namespace_totals: Dict[str, List[float]] = {}
        workload_totals: Dict[Tuple[str, str], List[float]] = {}

        for pod, container in containers:
            missing_requests = []
            missing_limits = []
            if container.cpu_request_m <= 0:
                missing_requests.append("cpu")
            if container.mem_request_b <= 0:
                missing_requests.append("mem")
            if container.cpu_limit_m <= 0:
                missing_limits.append("cpu")
            if container.mem_limit_b <= 0:
                missing_limits.append("mem")
            if missing_requests:
                missing_requests_rows.append((pod, container, ",".join(missing_requests), owner_chain_text(pod.owner_chain) or "-"))
            if missing_limits:
                missing_limits_rows.append((pod, container, ",".join(missing_limits), owner_chain_text(pod.owner_chain) or "-"))

            if snap.metrics_available:
                cpu_usage = container.usage_cpu_m if container.usage_cpu_m > 0 or container.cpu_history else 0.0
                mem_usage = container.usage_mem_b if container.usage_mem_b > 0 or container.mem_history else 0.0
                if container.cpu_request_m > 0 and cpu_usage > 0:
                    score = cpu_usage / container.cpu_request_m
                    if score >= 0.8:
                        ratio_findings.append((score, "CPU", "request", pod, container, format_mcpu(cpu_usage), format_mcpu(container.cpu_request_m)))
                if container.mem_request_b > 0 and mem_usage > 0:
                    score = mem_usage / container.mem_request_b
                    if score >= 0.8:
                        ratio_findings.append((score, "MEM", "request", pod, container, format_bytes(mem_usage), format_bytes(container.mem_request_b)))
                if container.cpu_limit_m > 0 and cpu_usage > 0:
                    score = cpu_usage / container.cpu_limit_m
                    if score >= 0.9:
                        ratio_findings.append((score, "CPU", "limit", pod, container, format_mcpu(cpu_usage), format_mcpu(container.cpu_limit_m)))
                if container.mem_limit_b > 0 and mem_usage > 0:
                    score = mem_usage / container.mem_limit_b
                    if score >= 0.9:
                        ratio_findings.append((score, "MEM", "limit", pod, container, format_bytes(mem_usage), format_bytes(container.mem_limit_b)))

        for pod in snap.pods:
            cpu_value = self.resource_metric_value(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history, snap.metrics_available)
            mem_value = self.resource_metric_value(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history, snap.metrics_available)
            namespace_totals.setdefault(pod.namespace, [0.0, 0.0])
            namespace_totals[pod.namespace][0] += cpu_value
            namespace_totals[pod.namespace][1] += mem_value
            owner = owner_chain_text(pod.owner_chain) or "Pod/%s" % pod.name
            workload_key = (pod.namespace, owner)
            workload_totals.setdefault(workload_key, [0.0, 0.0])
            workload_totals[workload_key][0] += cpu_value
            workload_totals[workload_key][1] += mem_value

        namespace_rows = [(namespace, values[0], values[1]) for namespace, values in namespace_totals.items()]
        workload_rows = [("%s %s" % (namespace, owner), values[0], values[1]) for (namespace, owner), values in workload_totals.items()]
        return ResourceRiskData(
            loaded_at=snap.loaded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            metrics_status=snap.metrics_status,
            metrics_available=snap.metrics_available,
            pod_count=len(snap.pods),
            container_count=len(containers),
            missing_requests=missing_requests_rows,
            missing_limits=missing_limits_rows,
            ratio_findings=sorted(ratio_findings, key=lambda item: item[0], reverse=True),
            namespace_totals=namespace_rows,
            workload_totals=workload_rows,
        )

    def resource_risk_lines(self) -> List[str]:
        """Build Resource Risk text lines. / Формирует текстовые строки Resource Risk.

        Returns:
            Human-readable resource configuration and usage risk findings.
        """
        data = self.resource_risk_data()
        if not data:
            return ["No cluster data loaded yet."]

        lines = [
            "Resource Risk",
            "Loaded: %s | Metrics: %s | Top values: %s"
            % (
                data.loaded_at,
                data.metrics_status,
                "live usage with request fallback" if data.metrics_available else "requests fallback",
            ),
            "",
            "Summary",
            "  Pods: %d | Containers: %d | missing requests: %d | missing limits: %d"
            % (data.pod_count, data.container_count, len(data.missing_requests), len(data.missing_limits)),
            "  Usage/request risk threshold: >=80%% | usage/limit risk threshold: >=90%%",
            "  Missing limits are reported as policy risk signals; some clusters intentionally do not require limits.",
            "",
        ]

        lines.append("Missing Resource Requests")
        if data.missing_requests:
            for pod, container, missing, owner in data.missing_requests[:40]:
                lines.append("  %s missing=%-7s owner=%s" % (self.resource_container_label(pod, container), missing, owner))
            if len(data.missing_requests) > 40:
                lines.append("  ... %d more container(s) without full requests" % (len(data.missing_requests) - 40))
        else:
            lines.append("  No containers without CPU/MEM requests found.")
        lines.append("")

        lines.append("Missing Resource Limits")
        if data.missing_limits:
            for pod, container, missing, owner in data.missing_limits[:40]:
                lines.append("  %s missing=%-7s owner=%s" % (self.resource_container_label(pod, container), missing, owner))
            if len(data.missing_limits) > 40:
                lines.append("  ... %d more container(s) without full limits" % (len(data.missing_limits) - 40))
        else:
            lines.append("  No containers without CPU/MEM limits found.")
        lines.append("")

        lines.append("High Usage Ratios")
        if not data.metrics_available:
            lines.append("  Live metrics are unavailable; usage/request and usage/limit ratios cannot be assessed.")
        elif data.ratio_findings:
            for score, resource, base_name, pod, container, used, base_value in data.ratio_findings[:40]:
                lines.append(
                    "  %-4s %5.0f%% %s use=%s %s=%s"
                    % (resource, score * 100.0, self.resource_container_label(pod, container), used, base_name, base_value)
                )
            if len(data.ratio_findings) > 40:
                lines.append("  ... %d more high ratio finding(s)" % (len(data.ratio_findings) - 40))
        else:
            lines.append("  No high usage/request or usage/limit ratios found in loaded live metrics.")
        lines.append("")

        def append_top(title: str, totals: Sequence[Tuple[str, float, float]], by_mem: bool = False) -> None:
            lines.append(title)
            index = 1 if by_mem else 0
            ranked = sorted(totals, key=lambda item: item[index + 1], reverse=True)
            for label, cpu_value, mem_value in ranked[:10]:
                lines.append("  %-46s cpu=%7s mem=%7s" % (truncate(label, 46), format_mcpu(cpu_value), format_bytes(mem_value)))
            if not ranked:
                lines.append("  No pods loaded.")
            lines.append("")

        append_top("Top Namespaces by CPU", data.namespace_totals)
        append_top("Top Namespaces by Memory", data.namespace_totals, by_mem=True)
        append_top("Top Workloads by CPU", data.workload_totals)
        append_top("Top Workloads by Memory", data.workload_totals, by_mem=True)
        return lines

    def resource_risk_attr(self, count: int) -> int:
        """Return color for a resource risk count. / Возвращает цвет для счетчика resource risk."""
        if count <= 0:
            return self.colors.get("green", 0)
        if count >= 10:
            return self.colors.get("red", 0)
        return self.colors.get("yellow", 0)

    def resource_missing_counts(self, rows: Sequence[Tuple[PodRow, ContainerInfo, str, str]]) -> Tuple[int, int]:
        """Count containers missing CPU and memory settings. / Считает containers без CPU и memory настроек.

        Args:
            rows: Missing request or limit rows.
        Returns:
            ``(cpu_count, mem_count)`` where containers missing both resources are counted in both values.
        """
        cpu_count = 0
        mem_count = 0
        for _pod, _container, missing, _owner in rows:
            parts = set(part.strip() for part in missing.split(","))
            if "cpu" in parts:
                cpu_count += 1
            if "mem" in parts:
                mem_count += 1
        return cpu_count, mem_count

    def draw_resource_summary_card(self, y: int, x: int, height: int, width: int, title: str, value: str, subtitle: str, attr: int) -> None:
        """Draw one Resource Risk summary card. / Рисует карточку сводки Resource Risk."""
        if height <= 0 or width <= 0:
            return
        self.box(y, x, height, width, title, focused=False)
        value_lines = str(value).splitlines() or [""]
        content = [(line, attr | curses.A_BOLD) for line in value_lines]
        if subtitle:
            content.append((subtitle, self.colors.get("green", 0)))
        for idx, (line, line_attr) in enumerate(content[: max(0, height - 2)]):
            self.add(y + 1 + idx, x + 2, truncate(line, width - 4), line_attr, width - 4)

    def draw_resource_table_header(self, y: int, x: int, width: int, text: str) -> None:
        """Draw a cyan table header row. / Рисует cyan header строки таблицы."""
        self.add(y, x, truncate(text.ljust(width), width), self.colors.get("black_on_cyan", curses.A_REVERSE), width)

    def draw_resource_rows_panel(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str,
        key: str,
        header: str,
        rows: Sequence[Tuple[str, int]],
        empty_text: str,
        empty_attr: int,
    ) -> None:
        """Draw a scrollable Resource Risk panel. / Рисует прокручиваемую панель Resource Risk.

        Args:
            y: Top row.
            x: Left column.
            height: Panel height.
            width: Panel width.
            title: Panel title.
            key: Scroll/hscroll state key.
            header: Virtual table header.
            rows: Virtual table data rows with attributes.
            empty_text: Message shown when rows are empty.
            empty_attr: Color attribute for the empty message.
        """
        self.box(y, x, height, width, title, focused=self.resource_focus == key)
        if height < 4 or width < 4:
            return
        inner_w = max(1, width - 2)
        header_y = y + 1
        data_y = y + 2
        data_h = max(0, height - 3)
        if not hasattr(self, "resource_panel_visible"):
            self.resource_panel_visible = {}
        self.resource_panel_visible[key] = data_h
        total_w = max([len(header), len(empty_text)] + [len(row_text) for row_text, _ in rows])
        max_hscroll = max(0, total_w - inner_w)
        hscroll = max(0, min(max_hscroll, self.hscroll.get(key, 0)))
        self.hscroll[key] = hscroll

        def slice_virtual(text: str) -> str:
            return text.ljust(total_w)[hscroll : hscroll + inner_w].ljust(inner_w)

        header_attr = self.colors.get("black_on_cyan", curses.A_REVERSE)
        self.add(header_y, x + 1, slice_virtual(header), header_attr, inner_w)
        if not rows:
            self.scroll[key] = 0
            self.add(data_y, x + 1, slice_virtual(empty_text), empty_attr, inner_w)
        else:
            max_scroll = max(0, len(rows) - data_h)
            scroll = max(0, min(max_scroll, self.scroll.get(key, 0)))
            self.scroll[key] = scroll
            for idx, (row_text, attr) in enumerate(rows[scroll : scroll + data_h], start=scroll):
                self.add(data_y + idx - scroll, x + 1, slice_virtual(row_text), attr, inner_w)

        indicators = []
        if len(rows) > data_h and data_h > 0:
            scroll = self.scroll.get(key, 0)
            indicators.append("%d-%d/%d" % (scroll + 1, min(len(rows), scroll + data_h), len(rows)))
        if max_hscroll > 0:
            indicators.append("cols %d-%d/%d" % (hscroll + 1, min(total_w, hscroll + inner_w), total_w))
        if indicators:
            indicator = " | ".join(indicators)
            self.add(y + height - 1, max(x + 1, x + width - len(indicator) - 2), indicator, curses.A_BOLD, len(indicator))

    def resource_missing_panel_rows(self, data: ResourceRiskData) -> Tuple[str, List[Tuple[str, int]], str, int]:
        """Build missing request/limit panel rows. / Формирует строки панели отсутствующих requests/limits."""
        header = "%-4s %-14s %-52s %-8s %s" % ("KIND", "NAMESPACE", "POD/CONTAINER", "MISSING", "OWNER")
        rows: List[Tuple[str, int]] = []
        for kind, source_rows in (("REQ", data.missing_requests), ("LIM", data.missing_limits)):
            for pod, container, missing, owner in source_rows:
                ident = "%s/%s" % (pod.name, container.name)
                line = "%-4s %-14s %-52s %-8s %s" % (
                    kind,
                    truncate(pod.namespace, 14),
                    truncate(ident, 52),
                    missing,
                    owner,
                )
                attr = self.colors.get("red", 0) if missing == "cpu,mem" else self.colors.get("yellow", 0)
                rows.append((line, attr))
        return header, rows, "No missing CPU/MEM requests or limits found.", self.colors.get("green", 0)

    def resource_ratio_panel_rows(self, data: ResourceRiskData) -> Tuple[str, List[Tuple[str, int]], str, int]:
        """Build high ratio panel rows. / Формирует строки панели высоких ratios."""
        header = "%-4s %-7s %-10s %-52s %-9s %s" % ("RES", "RATIO", "TYPE", "POD/CONTAINER", "BAR", "USE/BASE")
        if not data.metrics_available:
            return header, [], "Live metrics unavailable; ratio checks need usage data.", self.colors.get("yellow", 0)
        rows: List[Tuple[str, int]] = []
        for score, resource, base_name, pod, container, used, base_value in data.ratio_findings:
            ident = "%s/%s" % (pod.name, container.name)
            line = "%-4s %5.0f%% %-10s %-52s %-9s %s/%s" % (
                resource,
                score * 100.0,
                base_name,
                truncate(ident, 52),
                self.bar(7, min(score, 1.0)),
                used,
                base_value,
            )
            attr = self.colors.get("red", 0) if score >= 1.0 else self.colors.get("yellow", 0)
            rows.append((line, attr))
        return header, rows, "No high usage/request or usage/limit ratios found.", self.colors.get("green", 0)

    def resource_top_panel_rows(self, data: ResourceRiskData) -> Tuple[str, List[Tuple[str, int]], str, int]:
        """Build top consumer panel rows. / Формирует строки панели top consumers."""
        columns = [
            ("NAMESPACE CPU", sorted(data.namespace_totals, key=lambda item: item[1], reverse=True), False),
            ("NAMESPACE MEM", sorted(data.namespace_totals, key=lambda item: item[2], reverse=True), True),
            ("WORKLOAD CPU", sorted(data.workload_totals, key=lambda item: item[1], reverse=True), False),
            ("WORKLOAD MEM", sorted(data.workload_totals, key=lambda item: item[2], reverse=True), True),
        ]
        section_w = 46
        header = "  ".join(title.ljust(section_w) for title, _, _ in columns)
        count = max([0] + [len(items) for _, items, _ in columns])
        rows: List[Tuple[str, int]] = []
        for idx in range(count):
            parts = []
            for _, items, by_mem in columns:
                if idx >= len(items):
                    parts.append(" " * section_w)
                    continue
                label, cpu_value, mem_value = items[idx]
                value = format_bytes(mem_value) if by_mem else format_mcpu(cpu_value)
                label_w = max(1, section_w - len(value) - 1)
                parts.append(("%-*s %s" % (label_w, truncate(label, label_w), value)).ljust(section_w))
            rows.append(("  ".join(parts), self.colors.get("green", 0)))
        return header, rows, "No pods loaded.", self.colors.get("yellow", 0)

    def resource_panel_rows(self, key: str, data: ResourceRiskData) -> Tuple[str, List[Tuple[str, int]], str, int]:
        """Return rows for the requested Resource Risk panel. / Возвращает строки выбранной панели Resource Risk."""
        if key == "resource_ratios":
            return self.resource_ratio_panel_rows(data)
        if key == "resource_top":
            return self.resource_top_panel_rows(data)
        return self.resource_missing_panel_rows(data)

    def resource_panel_row_count(self, key: str, data: Optional[ResourceRiskData]) -> int:
        """Return scrollable row count for a Resource Risk panel. / Возвращает число строк панели Resource Risk."""
        if not data:
            return 0
        _, rows, _, _ = self.resource_panel_rows(key, data)
        return len(rows)

    def draw_resource_missing_panel(self, y: int, x: int, height: int, width: int, data: ResourceRiskData) -> None:
        """Draw missing requests/limits panel. / Рисует панель отсутствующих requests/limits."""
        header, rows, empty_text, empty_attr = self.resource_missing_panel_rows(data)
        self.draw_resource_rows_panel(y, x, height, width, "Missing Requests / Limits", "resource_missing", header, rows, empty_text, empty_attr)

    def draw_resource_ratio_panel(self, y: int, x: int, height: int, width: int, data: ResourceRiskData) -> None:
        """Draw high usage ratio panel. / Рисует панель высоких usage ratios."""
        header, rows, empty_text, empty_attr = self.resource_ratio_panel_rows(data)
        self.draw_resource_rows_panel(y, x, height, width, "High Usage Ratios", "resource_ratios", header, rows, empty_text, empty_attr)

    def draw_resource_top_consumers(self, y: int, x: int, height: int, width: int, data: ResourceRiskData) -> None:
        """Draw Resource Risk top consumers panel. / Рисует панель top consumers."""
        header, rows, empty_text, empty_attr = self.resource_top_panel_rows(data)
        self.draw_resource_rows_panel(y, x, height, width, "Top Consumers", "resource_top", header, rows, empty_text, empty_attr)

    def draw_resource_risk_compact(self, y: int, x: int, height: int, width: int, data: ResourceRiskData) -> None:
        """Draw compact Resource Risk fallback. / Рисует компактный fallback Resource Risk."""
        self.box(y, x, height, width, "Resource Risk", focused=True)
        lines = self.resource_risk_lines()
        area_h = max(0, height - 2)
        for idx, line in enumerate(lines[:area_h]):
            attr = self.colors.get("yellow", 0) if "missing" in line.lower() or "%" in line else 0
            self.add(y + 1 + idx, x + 2, line, attr, width - 4)

    def draw_resource_risk(self, y: int, x: int, height: int, width: int) -> None:
        """Draw styled Resource Risk screen. / Рисует стилизованный экран Resource Risk."""
        data = self.resource_risk_data()
        if not data:
            self.box(y, x, height, width, "Resource Risk", focused=True)
            self.add(y + 2, x + 2, "No cluster data loaded yet.", self.colors.get("yellow", 0), width - 4)
            return
        if height < 20 or width < 100:
            self.draw_resource_risk_compact(y, x, height, width, data)
            return

        self.box(y, x, height, width, "Resource Risk", focused=True)
        inner_x = x + 1
        inner_w = width - 2
        self.add(
            y + 1,
            inner_x + 1,
            "Loaded: %s | Metrics: %s | Top values: %s"
            % (data.loaded_at, data.metrics_status, "live usage with request fallback" if data.metrics_available else "requests fallback"),
            self.colors.get("yellow", 0),
            inner_w - 2,
        )

        summary_y = y + 2
        summary_h = 5
        gap = 1
        card_w = max(12, (inner_w - 3 * gap) // 4)
        top_namespace = sorted(data.namespace_totals, key=lambda item: item[1] + item[2], reverse=True)
        top_label = top_namespace[0][0] if top_namespace else "-"
        top_subtitle = "cpu=%s mem=%s" % (format_mcpu(top_namespace[0][1]), format_bytes(top_namespace[0][2])) if top_namespace else "no pods"
        request_cpu, request_mem = self.resource_missing_counts(data.missing_requests)
        limit_cpu, limit_mem = self.resource_missing_counts(data.missing_limits)
        cards = [
            ("Requests", "cpu: %d\nmem: %d" % (request_cpu, request_mem), "", self.resource_risk_attr(max(request_cpu, request_mem))),
            ("Limits", "cpu: %d\nmem: %d" % (limit_cpu, limit_mem), "", self.resource_risk_attr(max(limit_cpu, limit_mem))),
            ("Ratios", str(len(data.ratio_findings)), ">=80% request / >=90% limit", self.resource_risk_attr(len(data.ratio_findings))),
            ("Top Namespace", truncate(top_label, 22), top_subtitle, self.colors.get("green", 0)),
        ]
        for idx, (title, value, subtitle, attr) in enumerate(cards):
            card_x = inner_x + idx * (card_w + gap)
            card_width = max(12, x + width - 1 - card_x) if idx == len(cards) - 1 else card_w
            self.draw_resource_summary_card(summary_y, card_x, summary_h, card_width, title, value, subtitle, attr)

        bottom_h = max(7, min(11, height // 3))
        bottom_y = y + height - bottom_h - 1
        middle_y = summary_y + summary_h
        middle_h = max(6, bottom_y - middle_y)
        left_w = max(40, (inner_w - gap) // 2)
        right_x = inner_x + left_w + gap
        right_w = max(20, x + width - 1 - right_x)
        self.draw_resource_missing_panel(middle_y, inner_x, middle_h, left_w, data)
        self.draw_resource_ratio_panel(middle_y, right_x, middle_h, right_w, data)
        self.draw_resource_top_consumers(bottom_y, inner_x, bottom_h, inner_w, data)

    def workload_for(self, kind: str, namespace: str, name: str) -> Optional[WorkloadRow]:
        if not self.snapshot:
            return None
        return self.snapshot.workloads.get((kind, namespace, name))

    def pods_for_workload(self, kind: str, namespace: str, name: str) -> List[PodRow]:
        if not self.snapshot:
            return []
        return [
            pod
            for pod in self.snapshot.pods
            if pod.namespace == namespace and (kind, name) in pod.owner_chain
        ]

    def owner_lines(self) -> List[str]:
        """Build Workload / Owner page lines. / Формирует строки страницы Workload / Owner.

        Returns:
            Human-readable owner details for the current pod.
        """
        pod = self.find_pod(self.current_pod)
        if not pod:
            return ["Pod not found."]
        lines = [
            "Pod: %s/%s" % (pod.namespace, pod.name),
            "Owner chain: Pod/%s%s" % (pod.name, " > " + owner_chain_text(pod.owner_chain) if pod.owner_chain else ""),
            "",
        ]
        if not pod.owner_chain:
            lines.append("No ownerReferences found. This may be a static pod, mirror pod, or manually created pod.")
            return lines

        for kind, name in pod.owner_chain:
            workload = self.workload_for(kind, pod.namespace, name)
            lines.append("%s %s/%s" % (kind, pod.namespace, name))
            if workload:
                owner = "%s/%s" % (workload.owner_kind, workload.owner_name) if workload.owner_kind else "-"
                lines.append(
                    "  Status: %s | desired=%d ready=%d updated=%d available=%d"
                    % (workload.status, workload.desired, workload.ready, workload.updated, workload.available)
                )
                lines.append("  Strategy: %s" % workload.strategy)
                lines.append("  Selector: %s" % workload.selector)
                lines.append("  Owner: %s" % owner)
                controlled = self.pods_for_workload(kind, pod.namespace, name)
                if controlled:
                    lines.append("  Pods:")
                    for item in sorted(controlled, key=lambda value: value.name)[:20]:
                        lines.append(
                            "    %-42s %-14s ready=%d/%d restarts=%d cpu=%s mem=%s"
                            % (
                                truncate(item.name, 42),
                                item.status,
                                item.ready,
                                item.total,
                                item.restarts,
                                format_mcpu(item.usage_cpu_m or item.requested_cpu_m),
                                format_bytes(item.usage_mem_b or item.requested_mem_b),
                            )
                        )
                    if len(controlled) > 20:
                        lines.append("    ... %d more pod(s)" % (len(controlled) - 20))
                events = self.events_for(kind, name, pod.namespace)
                if events:
                    lines.append("  Events:")
                    for event in events[:8]:
                        lines.append("    %-8s %-14s %s" % (human_age(event.timestamp), event.reason or event.event_type, truncate(event.message, 90)))
            else:
                lines.append("  Object was not loaded. RBAC may block this resource or it may have been deleted.")
            lines.append("")
        return lines

    def namespace_rows(self) -> List[str]:
        """Return namespace picker rows. / Возвращает строки namespace picker.

        Returns:
            ``(all)`` plus filtered namespace names.
        """
        if not self.snapshot:
            return ["(all)"]
        names = list(self.snapshot.namespaces)
        if not names:
            names = sorted(set(pod.namespace for pod in self.snapshot.pods if pod.namespace))
        rows = ["(all)"] + [name for name in names if name]
        query = self.filters.get("namespace_picker", "").lower()
        if query:
            rows = [row for row in rows if query in row.lower()]
        return rows or ["(all)"]

    def draw_namespace_picker(self, y: int, x: int, height: int, width: int) -> None:
        title = "Namespaces"
        if self.filters["namespace_picker"] or self.editing_filter == "namespace_picker":
            title += " filter:%s" % self.filter_display("namespace_picker", "")
        self.box(y, x, height, width, title, focused=True)
        rows = self.namespace_rows()
        data_h = max(0, height - 3)
        selected = min(self.selected.get("namespaces", 0), max(0, len(rows) - 1))
        self.selected["namespaces"] = selected
        scroll = self.adjust_scroll("namespaces", selected, data_h, len(rows))
        current = self.filters.get("namespace", "")
        for idx, value in enumerate(rows[scroll : scroll + data_h], start=scroll):
            is_current = (value == "(all)" and not current) or value == current
            prefix = "* " if is_current else "  "
            attr = curses.A_REVERSE if idx == selected else self.colors.get("green", 0) if is_current else 0
            self.add(y + 2 + idx - scroll, x + 2, prefix + value, attr, width - 4)
        self.add(y + 1, x + 2, "Enter select | / filter | ESC back", self.colors.get("yellow", 0), width - 4)

    def choose_namespace(self) -> None:
        rows = self.namespace_rows()
        if not rows:
            return
        value = rows[min(self.selected.get("namespaces", 0), len(rows) - 1)]
        self.filters["namespace"] = "" if value == "(all)" else value
        self.filters["namespace_picker"] = ""
        self.reset_selections()
        self.flash("namespace: %s" % (value if value != "(all)" else "(all)"))
        self.pop_page()

    def active_search_query(self, key: str) -> str:
        """Return committed or live viewer/log search text. / Возвращает сохраненный или live search-текст.

        Args:
            key: ``logs`` or ``viewer``.
        Returns:
            Current query; while editing, the input buffer is used.
        """
        if getattr(self, "editing_filter", None) == key:
            return getattr(self, "filter_buffer", "")
        return getattr(self, "filters", {}).get(key, "")

    def query_error(self, query: str) -> str:
        """Validate a safe regex query for search fallback. / Проверяет безопасный regex query.

        Args:
            query: User-entered search expression.
        Returns:
            Empty string for a usable regex; otherwise a fallback reason.
        """
        if not query:
            return ""
        if len(query) > MAX_SEARCH_REGEX_LENGTH:
            return "regex too long (%d > %d)" % (len(query), MAX_SEARCH_REGEX_LENGTH)
        if _REGEX_NESTED_REPEAT_RE.search(query):
            return "potentially expensive nested repeat"
        if _REGEX_REPEATED_ALT_RE.search(query):
            return "potentially expensive repeated alternation"
        try:
            re.compile(query, re.IGNORECASE)
        except re.error as exc:
            return str(exc)
        return ""

    def text_view_lines(self, source: Sequence[str], width: int, wrap: bool, preserve_whitespace: bool) -> List[str]:
        """Prepare unfiltered text for a viewport. / Готовит полный текст для viewport без фильтрации.

        Args:
            source: Original text lines.
            width: Visible text width.
            wrap: Whether to wrap long lines.
            preserve_whitespace: Keep whitespace exactly when wrapping.
        Returns:
            Renderable viewport lines.
        """
        width = max(1, width)
        if not wrap:
            return [truncate(line, width) for line in source]
        wrapped: List[str] = []
        wrap_width = max(20, width)
        for line in source:
            safe_line = sanitize_terminal_text(line)
            wrapped.extend(
                textwrap.wrap(
                    safe_line,
                    wrap_width,
                    replace_whitespace=not preserve_whitespace,
                    drop_whitespace=not preserve_whitespace,
                )
                or [""]
            )
        return wrapped

    def query_match_spans(self, text: str, query: str, filter_error: str = "") -> List[Tuple[int, int]]:
        """Find all highlight spans for a query. / Находит все диапазоны подсветки для query.

        Args:
            text: Visible text line.
            query: Regex query or substring fallback.
            filter_error: Existing regex error; forces substring fallback.
        Returns:
            Non-empty match spans in character offsets.
        """
        if not query:
            return []
        if not filter_error:
            try:
                pattern = re.compile(query, re.IGNORECASE)
                return [(start, end) for start, end in (match.span() for match in pattern.finditer(text)) if end > start]
            except re.error as exc:
                filter_error = str(exc)
        lowered_text = text.lower()
        lowered_query = query.lower()
        if not lowered_query:
            return []
        spans: List[Tuple[int, int]] = []
        start = 0
        while True:
            idx = lowered_text.find(lowered_query, start)
            if idx < 0:
                break
            end = idx + len(query)
            spans.append((idx, end))
            start = end
        return spans

    def search_match_lines(self, lines: Sequence[str], query: str, filter_error: str = "") -> List[int]:
        """Return line indexes containing search matches. / Возвращает индексы строк с совпадениями."""
        if not query:
            return []
        effective_error = filter_error or self.query_error(query)
        return [idx for idx, line in enumerate(lines) if self.query_match_spans(line, query, effective_error)]

    def sync_search_query(self, key: str, query: str) -> None:
        """Reset match position when the query changes. / Сбрасывает позицию совпадения при смене query.

        Args:
            key: ``logs`` or ``viewer``.
            query: Active query text.
        """
        cache = getattr(self, "search_query_cache", {})
        match_index = getattr(self, "search_match_index", {})
        if cache.get(key, "") != query:
            cache[key] = query
            match_index[key] = 0
            self.search_query_cache = cache
            self.search_match_index = match_index
            if query:
                self.scroll[key] = 0

    def ensure_search_visible(self, key: str, lines: Sequence[str], area_h: int, filter_error: str = "") -> None:
        """Scroll to the selected search match if needed. / Скроллит к выбранному совпадению при необходимости.

        Args:
            key: ``logs`` or ``viewer`` scroll key.
            lines: Renderable text lines.
            area_h: Visible row count.
            filter_error: Regex error; enables substring fallback.
        """
        query = self.active_search_query(key)
        self.sync_search_query(key, query)
        matches = self.search_match_lines(lines, query, filter_error)
        if not matches or area_h <= 0:
            return
        match_index = getattr(self, "search_match_index", {})
        selected = max(0, min(len(matches) - 1, match_index.get(key, 0)))
        match_index[key] = selected
        self.search_match_index = match_index
        line_no = matches[selected]
        scroll = self.scroll.get(key, 0)
        if line_no < scroll:
            self.scroll[key] = line_no
        elif line_no >= scroll + area_h:
            self.scroll[key] = max(0, line_no - area_h + 1)

    def current_text_search_width(self, key: str) -> int:
        """Return current logs/viewer text width. / Возвращает текущую ширину текста logs/viewer."""
        _, width = self.stdscr.getmaxyx()
        plain = (key == "logs" and self.log_plain) or (key == "viewer" and self.viewer_plain)
        return max(1, width if plain else width - 4)

    def current_text_search_lines(self, key: str, width: Optional[int] = None) -> List[str]:
        """Return visible-source lines for search navigation. / Возвращает строки для навигации поиска."""
        text_width = width if width is not None else self.current_text_search_width(key)
        if key == "logs":
            return self.filtered_log_lines(text_width)
        return self.filtered_viewer_lines(text_width)

    def move_search_match(self, key: str, direction: int) -> bool:
        """Jump to next or previous search match. / Переходит к следующему или предыдущему совпадению.

        Args:
            key: ``logs`` or ``viewer``.
            direction: ``1`` for next, ``-1`` for previous.
        Returns:
            True if the key was handled.
        """
        query = self.active_search_query(key)
        if not query:
            return False
        if key == "logs":
            self.log_autoscroll = False
        lines = self.current_text_search_lines(key)
        filter_error = self.log_filter_error if key == "logs" else self.viewer_filter_error
        matches = self.search_match_lines(lines, query, filter_error)
        if not matches:
            self.flash("no matches")
            return True
        self.sync_search_query(key, query)
        match_index = getattr(self, "search_match_index", {})
        selected = match_index.get(key, 0)
        if selected < 0 or selected >= len(matches):
            current_scroll = self.scroll.get(key, 0)
            selected = 0
            for idx, line_no in enumerate(matches):
                if line_no >= current_scroll:
                    selected = idx
                    break
        selected = (selected + direction) % len(matches)
        match_index[key] = selected
        self.search_match_index = match_index
        self.scroll[key] = matches[selected]
        self.flash("match %d/%d" % (selected + 1, len(matches)), ttl=1.5)
        return True

    def draw_logs(self, y: int, x: int, height: int, width: int) -> None:
        """Draw framed logs view. / Рисует обычный logs view с рамками.

        Args:
            y: Top row.
            x: Left column.
            height: View height.
            width: View width.
        """
        ns, pod_name = self.current_pod or ("-", "-")
        title = "Container Logs: %s/%s/%s" % (ns, pod_name, self.current_container or "-")
        self.box(y, x, height, width, title, focused=True)
        controls = "s stream:%s | p previous:%s | n/p match | c/[] container | t ts:%s | w wrap:%s | f plain:%s | m more:%d | / search:%s | b bottom:%s"
        controls = controls % (
            "on" if self.log_stream else "off",
            "on" if self.log_previous else "off",
            "on" if self.log_timestamps else "off",
            "on" if self.log_wrap else "off",
            "on" if self.log_plain else "off",
            self.log_tail,
            self.filter_display("logs", ""),
            "on" if self.log_autoscroll else "locked",
        )
        self.add(y + 1, x + 2, controls, self.colors.get("yellow", 0), width - 4)
        lines = self.filtered_log_lines(width - 4)
        area_h = max(0, height - 4)
        query = self.active_search_query("logs")
        if query and getattr(self, "editing_filter", None) == "logs":
            self.ensure_search_visible("logs", lines, area_h, self.log_filter_error)
        elif not query and self.log_autoscroll and area_h > 0:
            self.scroll["logs"] = max(0, len(lines) - area_h)
        scroll = self.adjust_scroll("logs", self.scroll.get("logs", 0), area_h, len(lines), selection_is_scroll=True)
        if self.log_filter_error:
            self.add(y + 2, x + 2, "Regex fallback to substring: %s" % truncate(self.log_filter_error, width - 36), self.colors.get("red", 0), width - 4)
        for idx, line in enumerate(lines[scroll : scroll + area_h]):
            self.add_highlighted(y + 3 + idx, x + 2, line, query, width - 4, self.log_filter_error)
        if len(lines) > area_h and area_h > 0:
            indicator = "%d-%d/%d" % (scroll + 1, min(len(lines), scroll + area_h), len(lines))
            self.add(y + height - 1, max(x + 1, x + width - len(indicator) - 2), indicator, curses.A_BOLD, len(indicator))

    def draw_logs_plain(self, y: int, x: int, height: int, width: int) -> None:
        """Draw copy-friendly logs view. / Рисует copy-friendly logs view без рамок.

        Args:
            y: Top row.
            x: Left column.
            height: View height.
            width: View width.
        """
        lines = self.filtered_log_lines(width)
        area_h = max(0, height)
        query = self.active_search_query("logs")
        if query and getattr(self, "editing_filter", None) == "logs":
            self.ensure_search_visible("logs", lines, area_h, self.log_filter_error)
        elif not query and self.log_autoscroll and area_h > 0:
            self.scroll["logs"] = max(0, len(lines) - area_h)
        scroll = self.adjust_scroll("logs", self.scroll.get("logs", 0), area_h, len(lines), selection_is_scroll=True)
        for idx, line in enumerate(lines[scroll : scroll + area_h]):
            self.add_highlighted(y + idx, x, line, query, width, self.log_filter_error)

    def filtered_viewer_lines(self, width: int) -> List[str]:
        """Prepare describe/YAML viewer lines without filtering. / Готовит строки describe/YAML без фильтрации.

        Args:
            width: Visible text width.
        Returns:
            Lines ready for the viewer viewport.
        """
        query = self.active_search_query("viewer")
        self.viewer_filter_error = self.query_error(query)
        return self.text_view_lines(self.viewer_lines, width, self.viewer_wrap, preserve_whitespace=True)

    def draw_viewer(self, y: int, x: int, height: int, width: int) -> None:
        """Draw framed describe/YAML viewer. / Рисует viewer describe/YAML с рамками."""
        title = self.viewer_title or "Object Viewer"
        self.box(y, x, height, width, title, focused=True)
        controls = "d describe | y yaml | r reload | w wrap:%s | f plain:%s | / search:%s | n/p match | g/b top/bottom"
        controls = controls % (
            "on" if self.viewer_wrap else "off",
            "on" if self.viewer_plain else "off",
            self.filter_display("viewer", ""),
        )
        self.add(y + 1, x + 2, controls, self.colors.get("yellow", 0), width - 4)
        lines = self.filtered_viewer_lines(width - 4)
        area_h = max(0, height - 4)
        query = self.active_search_query("viewer")
        if query and getattr(self, "editing_filter", None) == "viewer":
            self.ensure_search_visible("viewer", lines, area_h, self.viewer_filter_error)
        scroll = self.adjust_scroll("viewer", self.scroll.get("viewer", 0), area_h, len(lines), selection_is_scroll=True)
        if self.viewer_filter_error:
            self.add(y + 2, x + 2, "Regex fallback to substring: %s" % truncate(self.viewer_filter_error, width - 36), self.colors.get("red", 0), width - 4)
        for idx, line in enumerate(lines[scroll : scroll + area_h]):
            self.add_highlighted(y + 3 + idx, x + 2, line, query, width - 4, self.viewer_filter_error)
        if len(lines) > area_h and area_h > 0:
            indicator = "%d-%d/%d" % (scroll + 1, min(len(lines), scroll + area_h), len(lines))
            self.add(y + height - 1, max(x + 1, x + width - len(indicator) - 2), indicator, curses.A_BOLD, len(indicator))

    def draw_viewer_plain(self, y: int, x: int, height: int, width: int) -> None:
        """Draw copy-friendly describe/YAML viewer. / Рисует copy-friendly describe/YAML viewer."""
        lines = self.filtered_viewer_lines(width)
        area_h = max(0, height)
        query = self.active_search_query("viewer")
        if query and getattr(self, "editing_filter", None) == "viewer":
            self.ensure_search_visible("viewer", lines, area_h, self.viewer_filter_error)
        scroll = self.adjust_scroll("viewer", self.scroll.get("viewer", 0), area_h, len(lines), selection_is_scroll=True)
        for idx, line in enumerate(lines[scroll : scroll + area_h]):
            self.add_highlighted(y + idx, x, line, query, width, self.viewer_filter_error)

    def add_highlighted(self, y: int, x: int, text: str, query: str, width: int, filter_error: str = "") -> None:
        """Draw text with all query matches highlighted. / Рисует текст с подсветкой всех совпадений.

        Args:
            y: Row.
            x: Column.
            text: Source text.
            query: Regex query.
            width: Maximum width.
            filter_error: Regex error; enables substring fallback when set.
        """
        value = truncate(text, width)
        spans = self.query_match_spans(value, query, filter_error)
        if not spans:
            self.add(y, x, value, 0, width)
            return
        pos = 0
        for start, end in spans:
            if start > pos:
                self.add(y, x + pos, value[pos:start], 0, start - pos)
            self.add(y, x + start, value[start:end], self.colors.get("black_on_yellow", curses.A_REVERSE), end - start)
            pos = end
        if pos < len(value):
            self.add(y, x + pos, value[pos:], 0, max(0, width - pos))

    def draw_text_page(self, y: int, x: int, height: int, width: int, title: str, lines: Sequence[str], key: str) -> None:
        self.box(y, x, height, width, title, focused=True)
        area_h = max(0, height - 2)
        scroll = self.adjust_scroll(key, self.scroll.get(key, 0), area_h, len(lines), selection_is_scroll=True)
        for idx, line in enumerate(lines[scroll : scroll + area_h]):
            self.add(y + 1 + idx, x + 2, line, 0, width - 4)

    def draw_footer(self, y: int, x: int, height: int, width: int) -> None:
        if height <= 0:
            return
        hint_y = y + height - 1
        if height > 1 and self.message and time.time() < self.message_until:
            self.add(y, x, truncate(self.message, width).ljust(width), self.colors.get("red", 0) if self.message.startswith("ERROR:") else self.colors.get("yellow", 0), width)
        if self.page == "overview":
            text = "Tab focus | ←/→ columns | g nodes/namespaces | j cronjobs | h health | z resources | d/y view | 2 namespace | / filter | ESC/q"
        elif self.page == "node":
            text = "↑/↓ select pod | ←/→ columns | d describe | y yaml | Enter pod detail | ESC back | r/u refresh | ? help"
        elif self.page == "namespace":
            text = "↑/↓ select pod | ←/→ columns | d describe | y yaml | Enter pod detail | / filter pods | ESC back | r/u refresh"
        elif self.page == "pod":
            text = "↑/↓ select container | ←/→ columns | d describe | y yaml | Enter/l logs | o owner | n node | ESC back | r/u refresh"
        elif self.page == "cronjobs":
            text = "↑/↓ select CronJob | ←/→ columns | Enter detail | d describe | y yaml | / filter | r/u refresh | ESC"
        elif self.page == "cronjob":
            text = "↑/↓ select related pod | ←/→ columns | Enter pod detail | d describe | y yaml | ESC back | r/u refresh"
        elif self.page == "logs":
            text = "d/y view | s stream | p previous(no search) | n/p matches | c/[/] container | t timestamps | w wrap | f plain | / search | ESC"
        elif self.page == "viewer":
            text = "d describe | y yaml | r reload | w wrap | f plain | / search | n/p matches | g/b top/bottom | ESC back"
        elif self.page == "diagnostics":
            text = "arrows/PgUp/PgDn scroll | r rerun diagnostics | ESC back | q quit"
        elif self.page == "health":
            text = "Health | Tab/Shift+Tab panel | ↑/↓ scroll | ←/→ columns | r/u refresh | ESC/q"
        elif self.page == "resources":
            text = "Resource Risk | Tab/Shift+Tab panel | ↑/↓ scroll | ←/→ columns | r/u refresh | ESC/q"
        elif self.page == "namespaces":
            text = "arrows select | Enter apply | / filter | ESC back | q quit"
        else:
            text = "arrows/PgUp/PgDn scroll | ESC back | q quit"
        self.add(hint_y, x, truncate(text, width).ljust(width), self.colors.get("yellow", 0), width)

    def current_nodes(self) -> List[NodeRow]:
        """Return filtered and sorted nodes. / Возвращает отфильтрованные и отсортированные nodes."""
        if not self.snapshot:
            return []
        nodes = [node for node in self.snapshot.nodes if match_text(node_filter_values(node), self.filters["nodes"])]
        return sort_nodes(nodes, self.node_sort[0], self.node_sort[1])

    def all_namespace_rows(self) -> List[NamespaceRow]:
        """Build namespace aggregates from the current snapshot. / Строит namespace aggregates из текущего snapshot.

        Returns:
            One row for every loaded namespace, including namespaces without pods.
        """
        if not self.snapshot:
            return []
        snap = self.snapshot
        names = set(snap.namespaces or [])
        names.update(pod.namespace for pod in snap.pods if pod.namespace)
        cpu_total = sum(node.alloc_cpu_m for node in snap.nodes)
        mem_total = sum(node.alloc_mem_b for node in snap.nodes)
        rows: List[NamespaceRow] = []
        bad_statuses = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "Pending", "Failed", "Evicted", "Error", "Unknown", "Terminating", "NotReady"}
        for name in sorted(names):
            pods = [pod for pod in snap.pods if pod.namespace == name]
            cpu_current = sum(self.display_usage(pod.usage_cpu_m, pod.requested_cpu_m, pod.cpu_history) for pod in pods)
            mem_current = sum(self.display_usage(pod.usage_mem_b, pod.requested_mem_b, pod.mem_history) for pod in pods)
            rows.append(
                NamespaceRow(
                    name=name,
                    status=snap.namespace_statuses.get(name, "Active"),
                    pods_count=len(pods),
                    running_pods=sum(1 for pod in pods if pod.status == "Running"),
                    ready=sum(pod.ready for pod in pods),
                    total=sum(pod.total for pod in pods),
                    restarts=sum(pod.restarts for pod in pods),
                    failures=sum(1 for pod in pods if pod.status in bad_statuses),
                    requested_cpu_m=sum(pod.requested_cpu_m for pod in pods),
                    requested_mem_b=sum(pod.requested_mem_b for pod in pods),
                    usage_cpu_m=cpu_current,
                    usage_mem_b=mem_current,
                    net_rx_bps=sum(pod.net_rx_bps for pod in pods),
                    net_tx_bps=sum(pod.net_tx_bps for pod in pods),
                    fs_read_bps=sum(pod.fs_read_bps for pod in pods),
                    fs_write_bps=sum(pod.fs_write_bps for pod in pods),
                    cpu_total_m=cpu_total,
                    mem_total_b=mem_total,
                    cpu_history=aggregate_histories([pod.cpu_history for pod in pods]),
                    mem_history=aggregate_histories([pod.mem_history for pod in pods]),
                    net_history=aggregate_histories([pod.net_history for pod in pods]),
                    net_rx_history=aggregate_histories([pod.net_rx_history for pod in pods]),
                    net_tx_history=aggregate_histories([pod.net_tx_history for pod in pods]),
                    io_history=aggregate_histories([pod.io_history for pod in pods]),
                    fs_read_history=aggregate_histories([pod.fs_read_history for pod in pods]),
                    fs_write_history=aggregate_histories([pod.fs_write_history for pod in pods]),
                )
            )
        return rows

    def current_namespace_rows(self) -> List[NamespaceRow]:
        """Return filtered and sorted namespace rows. / Возвращает отфильтрованные и отсортированные namespace rows."""
        rows = [row for row in self.all_namespace_rows() if match_text(namespace_filter_values(row), self.filters["overview_namespaces"])]
        return sort_namespaces(rows, self.namespace_sort[0], self.namespace_sort[1])

    def current_pods(self, ignore_namespace_filter: bool = False) -> List[PodRow]:
        """Return filtered and sorted pods. / Возвращает отфильтрованные и отсортированные pods.

        Args:
            ignore_namespace_filter: Whether to ignore the namespace UI filter.
        Returns:
            Pod rows for the current UI context.
        """
        if not self.snapshot:
            return []
        pods = list(self.snapshot.pods)
        ns_filter = "" if ignore_namespace_filter else self.filters["namespace"]
        if ns_filter:
            if ns_filter in (self.snapshot.namespaces or []):
                pods = [pod for pod in pods if pod.namespace == ns_filter]
            else:
                pods = [pod for pod in pods if ns_filter.lower() in pod.namespace.lower()]
        pods = [pod for pod in pods if match_text(pod_filter_values(pod), self.filters["pods"])]
        return sort_pods(pods, self.pod_sort[0], self.pod_sort[1])

    def current_namespace_pods(self, namespace: str) -> List[PodRow]:
        """Return pods for one namespace with pod text filter. / Возвращает pods одного namespace с фильтром pod."""
        if not self.snapshot:
            return []
        pods = [pod for pod in self.snapshot.pods if pod.namespace == namespace and match_text(pod_filter_values(pod), self.filters["pods"])]
        return sort_pods(pods, self.pod_sort[0], self.pod_sort[1])

    def all_cronjob_rows(self) -> List[CronJobRow]:
        """Return all CronJob diagnostic rows. / Возвращает все строки диагностики CronJob."""
        if not self.snapshot:
            return []
        return build_cronjob_rows(self.snapshot)

    def current_cronjobs(self) -> List[CronJobRow]:
        """Return filtered and sorted CronJob rows. / Возвращает filtered/sorted CronJob rows."""
        rows = [row for row in self.all_cronjob_rows() if match_text(cronjob_filter_values(row), self.filters["cronjobs"])]
        return sort_cronjobs(rows, self.cronjob_sort[0], self.cronjob_sort[1])

    def cronjob_runs(self, row: CronJobRow) -> List[CronJobRunRow]:
        """Return Job runs for one CronJob. / Возвращает Job-запуски одного CronJob."""
        if not self.snapshot:
            return []
        runs = []
        for workload in self.snapshot.workloads.values():
            run = job_run_from_workload(workload)
            if run and run.namespace == row.namespace and run.cronjob == row.name:
                runs.append(run)
        runs.sort(key=lambda item: item.start_time or item.completion_time or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
        return runs

    def find_cronjob(self, key: Optional[Tuple[str, str]]) -> Optional[CronJobRow]:
        """Find a CronJob diagnostic row by namespace/name. / Ищет CronJob по namespace/name."""
        if not key:
            return None
        namespace, name = key
        for row in self.all_cronjob_rows():
            if row.namespace == namespace and row.name == name:
                return row
        return None

    def cronjob_related_pods(self, row: CronJobRow) -> List[PodRow]:
        """Return pods owned by a CronJob or its Jobs. / Возвращает pod'ы CronJob или его Job."""
        if not self.snapshot:
            return []
        job_names = {run.name for run in self.cronjob_runs(row)}
        related = []
        for pod in self.snapshot.pods:
            if pod.namespace != row.namespace:
                continue
            chain = pod.owner_chain or pod.owners
            if ("CronJob", row.name) in chain or any(kind == "Job" and name in job_names for kind, name in chain):
                related.append(pod)
        return sort_pods(related, self.pod_sort[0], self.pod_sort[1])

    def cronjob_events(self, row: CronJobRow) -> List[EventInfo]:
        """Return events related to a CronJob, its Jobs, or its pods. / Возвращает связанные events."""
        if not self.snapshot:
            return []
        job_names = {run.name for run in self.cronjob_runs(row)}
        pod_names = {pod.name for pod in self.cronjob_related_pods(row)}
        related = []
        for event in self.snapshot.events:
            if event.namespace != row.namespace:
                continue
            if (event.kind == "CronJob" and event.name == row.name) or (event.kind == "Job" and event.name in job_names) or (event.kind == "Pod" and event.name in pod_names):
                related.append(event)
        return related

    def find_node(self, name: Optional[str]) -> Optional[NodeRow]:
        if not self.snapshot or not name:
            return None
        for node in self.snapshot.nodes:
            if node.name == name:
                return node
        return None

    def find_pod(self, key: Optional[Tuple[str, str]]) -> Optional[PodRow]:
        if not self.snapshot or not key:
            return None
        namespace, name = key
        for pod in self.snapshot.pods:
            if pod.namespace == namespace and pod.name == name:
                return pod
        return None

    def find_namespace(self, name: Optional[str]) -> Optional[NamespaceRow]:
        if not name:
            return None
        for namespace in self.all_namespace_rows():
            if namespace.name == name:
                return namespace
        return None

    def selected_object_target(self) -> Optional[ObjectTarget]:
        """Resolve the object targeted by describe/YAML hotkeys. / Определяет объект для describe/YAML hotkeys.

        Returns:
            ObjectTarget for the current page/selection, or None when no object is selected.
        """
        if self.page == "overview":
            if self.focus == "nodes":
                rows = self.current_nodes()
                if rows:
                    node = rows[min(self.selected.get("nodes", 0), len(rows) - 1)]
                    return ObjectTarget("node", "", node.name, "Node/%s" % node.name)
            if self.focus == "overview_namespaces":
                rows = self.current_namespace_rows()
                if rows:
                    namespace = rows[min(self.selected.get("overview_namespaces", 0), len(rows) - 1)]
                    return ObjectTarget("namespace", "", namespace.name, "Namespace/%s" % namespace.name)
            if self.focus == "pods":
                rows = self.current_pods()
                if rows:
                    pod = rows[min(self.selected.get("pods", 0), len(rows) - 1)]
                    return ObjectTarget("pod", pod.namespace, pod.name, "Pod/%s/%s" % (pod.namespace, pod.name))
        elif self.page == "node":
            node = self.find_node(self.current_node)
            rows = [pod for pod in self.current_pods(ignore_namespace_filter=True) if node and pod.node == node.name]
            if rows:
                pod = rows[min(self.selected.get("node_pods", 0), len(rows) - 1)]
                return ObjectTarget("pod", pod.namespace, pod.name, "Pod/%s/%s" % (pod.namespace, pod.name))
            if node:
                return ObjectTarget("node", "", node.name, "Node/%s" % node.name)
        elif self.page == "namespace":
            namespace = self.find_namespace(self.current_namespace)
            rows = self.current_namespace_pods(namespace.name) if namespace else []
            if rows:
                pod = rows[min(self.selected.get("namespace_pods", 0), len(rows) - 1)]
                return ObjectTarget("pod", pod.namespace, pod.name, "Pod/%s/%s" % (pod.namespace, pod.name))
            if namespace:
                return ObjectTarget("namespace", "", namespace.name, "Namespace/%s" % namespace.name)
        elif self.page in ("pod", "logs"):
            pod = self.find_pod(self.current_pod)
            if pod:
                container = ""
                if self.page == "pod" and pod.containers:
                    idx = min(self.selected.get("containers", 0), len(pod.containers) - 1)
                    container = pod.containers[idx].name
                elif self.page == "logs":
                    container = self.current_container or ""
                suffix = " container/%s" % container if container else ""
                return ObjectTarget("pod", pod.namespace, pod.name, "Pod/%s/%s%s" % (pod.namespace, pod.name, suffix), container)
        elif self.page == "owner":
            pod = self.find_pod(self.current_pod)
            if pod and pod.owner_chain:
                kind, name = pod.owner_chain[-1]
                return ObjectTarget(kind, pod.namespace, name, "%s/%s/%s" % (kind, pod.namespace, name))
            if pod:
                return ObjectTarget("pod", pod.namespace, pod.name, "Pod/%s/%s" % (pod.namespace, pod.name))
        elif self.page == "cronjobs":
            rows = self.current_cronjobs()
            if rows:
                row = rows[min(self.selected.get("cronjobs", 0), len(rows) - 1)]
                return ObjectTarget("cronjob", row.namespace, row.name, "CronJob/%s/%s" % (row.namespace, row.name))
        elif self.page == "cronjob":
            row = self.find_cronjob(self.current_cronjob)
            if row:
                return ObjectTarget("cronjob", row.namespace, row.name, "CronJob/%s/%s" % (row.namespace, row.name))
        elif self.page == "namespaces":
            rows = self.namespace_rows()
            if rows:
                name = rows[min(self.selected.get("namespaces", 0), len(rows) - 1)]
                if name != "(all)":
                    return ObjectTarget("namespace", "", name, "Namespace/%s" % name)
        return None

    def open_object_viewer(self, mode: str, target: Optional[ObjectTarget] = None, push: bool = True) -> None:
        """Open describe/YAML viewer for a selected object. / Открывает viewer describe/YAML для объекта.

        Args:
            mode: ``describe`` or ``yaml``.
            target: Optional explicit object target.
            push: Whether to push a new navigation page.
        """
        target = target or self.selected_object_target()
        if not target:
            self.flash("no object selected", error=True)
            return
        self.viewer_mode = "yaml" if mode == "yaml" else "describe"
        self.viewer_target = target
        self.viewer_title = "%s: %s" % ("YAML" if self.viewer_mode == "yaml" else "Describe", target.label)
        try:
            if self.viewer_mode == "yaml":
                self.viewer_lines = self.client.yaml_object(target.kind, target.namespace, target.name)
            else:
                self.viewer_lines = self.client.describe_object(target.kind, target.namespace, target.name)
            if target.container:
                self.viewer_lines = ["# selected container: %s" % target.container, ""] + self.viewer_lines
        except DataError as exc:
            self.viewer_lines = ["ERROR: %s" % exc]
            self.flash(str(exc), error=True, ttl=6.0)
        self.viewer_filter_error = ""
        self.scroll["viewer"] = 0
        if push and self.page != "viewer":
            self.push_page("viewer")

    def reload_viewer(self) -> None:
        """Reload current describe/YAML viewer. / Перезагружает текущий describe/YAML viewer."""
        if not self.viewer_target:
            self.flash("no viewer target", error=True)
            return
        self.open_object_viewer(self.viewer_mode or "describe", self.viewer_target, push=False)

    def events_for(self, kind: str, name: str, namespace: str) -> List[EventInfo]:
        if not self.snapshot:
            return []
        return [
            event
            for event in self.snapshot.events
            if event.kind == kind and event.name == name and (not namespace or event.namespace == namespace)
        ]

    def filtered_log_lines(self, width: int) -> List[str]:
        """Prepare loaded log lines without filtering. / Готовит log lines без фильтрации.

        Args:
            width: Visible text width.
        Returns:
            Lines ready for log viewport rendering.
        """
        query = self.active_search_query("logs")
        self.log_filter_error = self.query_error(query)
        return self.text_view_lines(self.log_lines, width, self.log_wrap, preserve_whitespace=False)

    def handle_key(self, ch: Any) -> bool:
        """Dispatch one input key. / Обрабатывает одну нажатую клавишу.

        Args:
            ch: Raw curses key.
        Returns:
            True when the application should quit.
        """
        if self.editing_filter:
            self.handle_filter_key(ch)
            return False
        key = hotkey(ch)
        if key == "q" or is_ctrl_c(ch):
            return True
        if is_escape_key(ch):
            return self.handle_escape()
        if is_tab_key(ch) or ch == curses.KEY_BTAB:
            self.handle_tab(reverse=(ch == curses.KEY_BTAB))
            return False
        if ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME, curses.KEY_END):
            self.handle_motion(ch)
            return False
        if is_enter_key(ch):
            self.handle_enter()
            return False
        if key == "/":
            self.start_filter()
            return False
        if key == "2":
            self.open_namespace_picker()
            return False
        if key == "j" and self.page != "cronjobs":
            self.push_page("cronjobs")
            return False
        if key == "!" or key == "h":
            self.push_page("health")
            return False
        if key == "z":
            self.push_page("resources")
            return False
        if key == "x":
            self.open_diagnostics()
            return False
        if key == "?":
            self.push_page("help")
            return False
        if key in ("d", "y"):
            target = self.viewer_target if self.page == "viewer" else None
            self.open_object_viewer("yaml" if key == "y" else "describe", target=target, push=self.page != "viewer")
            return False
        if key == "r" and self.page == "diagnostics":
            self.open_diagnostics()
            return False
        if self.page == "viewer" and key == "r":
            self.reload_viewer()
            return False
        if key == "u" or (key == "r" and self.page not in ("overview", "logs")):
            self.refresh_snapshot(force=True)
            return False
        if self.page == "overview" and self.handle_overview_char(ch):
            return False
        if self.page == "overview":
            return False
        if self.page == "cronjobs" and self.handle_cronjobs_char(ch):
            return False
        if self.page == "pod" and key == "n":
            pod = self.find_pod(self.current_pod)
            if pod and pod.node and pod.node != "-":
                self.push_page("node", node_name=pod.node)
        elif self.page == "pod" and key == "o":
            self.push_page("owner")
        elif self.page == "pod" and key == "l":
            self.handle_enter()
        elif self.page == "logs":
            self.handle_logs_char(ch)
        elif self.page == "viewer":
            self.handle_viewer_char(ch)
        return False

    def handle_filter_key(self, ch: Any) -> None:
        """Edit an active filter field. / Редактирует активное поле фильтра.

        Args:
            ch: Raw curses key.
        """
        if is_escape_key(ch):
            self.editing_filter = None
            self.filter_buffer = ""
            return
        if is_enter_key(ch):
            key = self.editing_filter
            if key:
                self.filters[key] = self.filter_buffer
            self.editing_filter = None
            self.filter_buffer = ""
            if key in ("logs", "viewer"):
                self.sync_search_query(key, self.filters.get(key, ""))
                return
            self.reset_selections()
            return
        if is_backspace_key(ch):
            self.filter_buffer = self.filter_buffer[:-1]
            if self.editing_filter in ("logs", "viewer"):
                self.sync_search_query(self.editing_filter, self.filter_buffer)
                if self.editing_filter == "logs" and self.filter_buffer:
                    self.log_autoscroll = False
            return
        char = key_char(ch)
        if char and char.isprintable():
            self.filter_buffer += char
            if self.editing_filter in ("logs", "viewer"):
                self.sync_search_query(self.editing_filter, self.filter_buffer)
                if self.editing_filter == "logs":
                    self.log_autoscroll = False

    def handle_escape(self) -> bool:
        """Handle ESC navigation and quit confirmation. / Обрабатывает ESC-навигацию и подтверждение выхода.

        Returns:
            True when ESC should quit the app.
        """
        if self.page != "overview":
            self.pop_page()
            return False
        filter_key = self.focus if self.focus in self.filters else ""
        if filter_key and self.filters[filter_key]:
            self.filters[filter_key] = ""
            self.reset_selections()
            return False
        if self.filters["namespace"]:
            self.filters["namespace"] = ""
            self.reset_selections()
            return False
        now = time.time()
        if now - self.pending_esc_at < 2.0:
            return True
        self.pending_esc_at = now
        self.flash("Press ESC again to quit")
        return False

    def handle_tab(self, reverse: bool = False) -> None:
        if self.page == "health":
            idx = HEALTH_PANEL_KEYS.index(self.health_focus) if self.health_focus in HEALTH_PANEL_KEYS else 0
            idx = (idx - 1 if reverse else idx + 1) % len(HEALTH_PANEL_KEYS)
            self.health_focus = HEALTH_PANEL_KEYS[idx]
            return
        if self.page == "resources":
            idx = RESOURCE_PANEL_KEYS.index(self.resource_focus) if self.resource_focus in RESOURCE_PANEL_KEYS else 0
            idx = (idx - 1 if reverse else idx + 1) % len(RESOURCE_PANEL_KEYS)
            self.resource_focus = RESOURCE_PANEL_KEYS[idx]
            return
        if self.page != "overview":
            return
        order = ["overview_namespaces", "pods"] if self.overview_mode == "namespaces" else ["nodes", "pods"]
        idx = order.index(self.focus) if self.focus in order else 0
        idx = (idx - 1 if reverse else idx + 1) % len(order)
        self.focus = order[idx]

    def handle_motion(self, ch: int) -> None:
        """Handle arrow/page/home/end movement. / Обрабатывает перемещение arrows/page/home/end.

        Args:
            ch: curses movement key.
        """
        amount = 1
        if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            self.move_hscroll(self.current_table_key(), -8 if ch == curses.KEY_LEFT else 8)
            return
        if ch == curses.KEY_PPAGE:
            amount = -10
        elif ch == curses.KEY_NPAGE:
            amount = 10
        elif ch == curses.KEY_UP:
            amount = -1
        elif ch == curses.KEY_DOWN:
            amount = 1
        if self.page == "overview":
            key = self.focus if self.focus in ("nodes", "overview_namespaces", "pods") else "nodes"
            if key == "nodes":
                count = len(self.current_nodes())
            elif key == "overview_namespaces":
                count = len(self.current_namespace_rows())
            else:
                count = len(self.current_pods())
            self.move_selected(key, ch, amount, count)
        elif self.page == "node":
            node = self.find_node(self.current_node)
            count = len([pod for pod in self.current_pods(ignore_namespace_filter=True) if node and pod.node == node.name])
            self.move_selected("node_pods", ch, amount, count)
        elif self.page == "namespace":
            namespace = self.find_namespace(self.current_namespace)
            count = len(self.current_namespace_pods(namespace.name)) if namespace else 0
            self.move_selected("namespace_pods", ch, amount, count)
        elif self.page == "pod":
            pod = self.find_pod(self.current_pod)
            count = len(pod.containers) if pod else 0
            self.move_selected("containers", ch, amount, count)
        elif self.page == "cronjobs":
            self.move_selected("cronjobs", ch, amount, len(self.current_cronjobs()))
        elif self.page == "cronjob":
            row = self.find_cronjob(self.current_cronjob)
            count = len(self.cronjob_related_pods(row)) if row else 0
            self.move_selected("cronjob_pods", ch, amount, count)
        elif self.page == "logs":
            lines = self.filtered_log_lines(self.stdscr.getmaxyx()[1] - 4)
            self.log_autoscroll = ch == curses.KEY_END
            self.move_scroll("logs", ch, amount, len(lines))
        elif self.page == "viewer":
            lines = self.filtered_viewer_lines(self.stdscr.getmaxyx()[1] - 4)
            self.move_scroll("viewer", ch, amount, len(lines))
        elif self.page == "resources":
            self.move_resource_scroll(self.resource_focus, ch, amount, self.resource_panel_row_count(self.resource_focus, self.resource_risk_data()))
        elif self.page == "health":
            self.move_health_scroll(self.health_focus, ch, amount, self.health_panel_row_count(self.health_focus, self.health_data()))
        elif self.page == "namespaces":
            self.move_selected("namespaces", ch, amount, len(self.namespace_rows()))
        elif self.page in ("help", "health", "owner", "diagnostics"):
            if self.page == "help":
                lines = help_lines()
            elif self.page == "health":
                lines = self.health_lines()
            elif self.page == "owner":
                lines = self.owner_lines()
            else:
                lines = self.diagnostics_cache
            self.move_scroll(self.page, ch, amount, len(lines))

    def move_selected(self, key: str, ch: int, amount: int, count: int) -> None:
        if count <= 0:
            self.selected[key] = 0
            return
        if ch == curses.KEY_HOME:
            self.selected[key] = 0
        elif ch == curses.KEY_END:
            self.selected[key] = count - 1
        else:
            self.selected[key] = max(0, min(count - 1, self.selected.get(key, 0) + amount))

    def move_scroll(self, key: str, ch: int, amount: int, count: int) -> None:
        if count <= 0:
            self.scroll[key] = 0
            return
        if ch == curses.KEY_HOME:
            self.scroll[key] = 0
        elif ch == curses.KEY_END:
            self.scroll[key] = count - 1
        else:
            self.scroll[key] = max(0, min(count - 1, self.scroll.get(key, 0) + amount))

    def move_resource_scroll(self, key: str, ch: int, amount: int, count: int) -> None:
        """Move Resource Risk panel scroll. / Сдвигает scroll панели Resource Risk.

        Args:
            key: Resource panel state key.
            ch: curses movement key.
            amount: Signed row movement.
            count: Number of rows in the focused panel.
        """
        page_size = max(1, self.resource_panel_visible.get(key, 1))
        max_scroll = max(0, count - page_size)
        if count <= 0:
            self.scroll[key] = 0
            return
        if ch == curses.KEY_HOME:
            self.scroll[key] = 0
        elif ch == curses.KEY_END:
            self.scroll[key] = max_scroll
        else:
            self.scroll[key] = max(0, min(max_scroll, self.scroll.get(key, 0) + amount))

    def move_health_scroll(self, key: str, ch: int, amount: int, count: int) -> None:
        """Move Problems / Health panel scroll. / Сдвигает scroll панели Problems / Health.

        Args:
            key: Health panel state key.
            ch: curses movement key.
            amount: Signed row movement.
            count: Number of rows in the focused panel.
        """
        page_size = max(1, self.health_panel_visible.get(key, 1))
        max_scroll = max(0, count - page_size)
        if count <= 0:
            self.scroll[key] = 0
            return
        if ch == curses.KEY_HOME:
            self.scroll[key] = 0
        elif ch == curses.KEY_END:
            self.scroll[key] = max_scroll
        else:
            self.scroll[key] = max(0, min(max_scroll, self.scroll.get(key, 0) + amount))

    def current_table_key(self) -> str:
        """Return table state key for horizontal movement. / Возвращает ключ таблицы для горизонтального сдвига."""
        if self.page == "overview":
            if self.focus in ("nodes", "overview_namespaces", "pods"):
                return self.focus
            return "nodes"
        if self.page == "node":
            return "node_pods"
        if self.page == "namespace":
            return "namespace_pods"
        if self.page == "pod":
            return "containers"
        if self.page == "cronjobs":
            return "cronjobs"
        if self.page == "cronjob":
            return "cronjob_pods"
        if self.page == "resources":
            return self.resource_focus
        if self.page == "health":
            return self.health_focus
        return ""

    def move_hscroll(self, key: str, amount: int) -> None:
        """Move horizontal table scroll. / Сдвигает горизонтальный scroll таблицы."""
        if not key:
            return
        self.hscroll[key] = max(0, self.hscroll.get(key, 0) + amount)

    def handle_enter(self) -> None:
        """Open the selected row or apply namespace choice. / Открывает выбранную строку или применяет namespace."""
        if self.page == "overview":
            if self.focus == "nodes":
                rows = self.current_nodes()
                if rows:
                    self.push_page("node", node_name=rows[min(self.selected["nodes"], len(rows) - 1)].name)
            elif self.focus == "overview_namespaces":
                rows = self.current_namespace_rows()
                if rows:
                    namespace = rows[min(self.selected["overview_namespaces"], len(rows) - 1)]
                    self.push_page("namespace", namespace_name=namespace.name)
            elif self.focus == "pods":
                rows = self.current_pods()
                if rows:
                    pod = rows[min(self.selected["pods"], len(rows) - 1)]
                    self.push_page("pod", pod_key=(pod.namespace, pod.name))
        elif self.page == "node":
            node = self.find_node(self.current_node)
            rows = [pod for pod in self.current_pods(ignore_namespace_filter=True) if node and pod.node == node.name]
            if rows:
                pod = rows[min(self.selected["node_pods"], len(rows) - 1)]
                self.push_page("pod", pod_key=(pod.namespace, pod.name))
        elif self.page == "namespace":
            namespace = self.find_namespace(self.current_namespace)
            rows = self.current_namespace_pods(namespace.name) if namespace else []
            if rows:
                pod = rows[min(self.selected["namespace_pods"], len(rows) - 1)]
                self.push_page("pod", pod_key=(pod.namespace, pod.name))
        elif self.page == "pod":
            pod = self.find_pod(self.current_pod)
            if pod and pod.containers:
                container = pod.containers[min(self.selected["containers"], len(pod.containers) - 1)]
                self.push_page("logs", container_name=container.name)
                self.load_logs()
        elif self.page == "cronjobs":
            rows = self.current_cronjobs()
            if rows:
                row = rows[min(self.selected["cronjobs"], len(rows) - 1)]
                self.push_page("cronjob", cronjob_key=(row.namespace, row.name))
        elif self.page == "cronjob":
            row = self.find_cronjob(self.current_cronjob)
            rows = self.cronjob_related_pods(row) if row else []
            if rows:
                pod = rows[min(self.selected["cronjob_pods"], len(rows) - 1)]
                self.push_page("pod", pod_key=(pod.namespace, pod.name))
        elif self.page == "namespaces":
            self.choose_namespace()

    def handle_overview_char(self, ch: Any) -> bool:
        key = hotkey(ch)
        if key == "g":
            self.toggle_overview_mode()
            return True
        if self.focus == "nodes" and key in NODE_SORT_KEYS:
            column = NODE_SORT_KEYS[key]
            if column in normalize_columns(self.args.node_columns, NODE_COLUMNS, NODE_DEFAULT_COLUMNS):
                self.node_sort = (column, not self.node_sort[1]) if self.node_sort[0] == column else (column, True)
                self.selected["nodes"] = 0
                return True
        elif self.focus == "overview_namespaces" and key in NAMESPACE_SORT_KEYS:
            column = NAMESPACE_SORT_KEYS[key]
            if column in NAMESPACE_COLUMNS:
                self.namespace_sort = (column, not self.namespace_sort[1]) if self.namespace_sort[0] == column else (column, True)
                self.selected["overview_namespaces"] = 0
                return True
        elif self.focus == "pods" and key in POD_SORT_KEYS:
            column = POD_SORT_KEYS[key]
            if column in normalize_columns(self.args.pod_columns, POD_COLUMNS):
                self.pod_sort = (column, not self.pod_sort[1]) if self.pod_sort[0] == column else (column, True)
                self.selected["pods"] = 0
                return True
        return False

    def handle_cronjobs_char(self, ch: Any) -> bool:
        """Handle CronJob list hotkeys. / Обрабатывает hotkeys списка CronJob."""
        key = hotkey(ch)
        if key in CRONJOB_SORT_KEYS:
            column = CRONJOB_SORT_KEYS[key]
            self.cronjob_sort = (column, not self.cronjob_sort[1]) if self.cronjob_sort[0] == column else (column, True)
            self.selected["cronjobs"] = 0
            return True
        return False

    def toggle_overview_mode(self) -> None:
        """Toggle overview primary table between nodes and namespaces. / Переключает верхнюю таблицу overview."""
        if self.overview_mode == "namespaces":
            self.overview_mode = "nodes"
            if self.focus == "overview_namespaces":
                self.focus = "nodes"
        else:
            self.overview_mode = "namespaces"
            if self.focus == "nodes":
                self.focus = "overview_namespaces"
        self.flash("overview: %s" % self.overview_mode)

    def handle_viewer_char(self, ch: Any) -> None:
        """Handle describe/YAML viewer hotkeys. / Обрабатывает hotkeys describe/YAML viewer.

        Args:
            ch: Raw curses key.
        """
        key = hotkey(ch)
        if key == "w":
            self.viewer_wrap = not self.viewer_wrap
            self.scroll["viewer"] = 0
        elif key == "f":
            self.viewer_plain = not self.viewer_plain
            self.flash("plain viewer %s" % ("on" if self.viewer_plain else "off"))
        elif key == "n":
            self.move_search_match("viewer", 1)
        elif key == "p":
            self.move_search_match("viewer", -1)
        elif key == "g":
            self.scroll["viewer"] = 0
        elif key == "b":
            lines = self.filtered_viewer_lines(self.stdscr.getmaxyx()[1] - 4)
            self.scroll["viewer"] = max(0, len(lines) - 1)

    def handle_logs_char(self, ch: Any) -> None:
        """Handle logs page hotkeys. / Обрабатывает hotkeys страницы logs.

        Args:
            ch: Raw curses key.
        """
        key = hotkey(ch)
        if key == "s":
            self.log_stream = not self.log_stream
            self.flash("log streaming %s" % ("on" if self.log_stream else "off"))
        elif key == "n":
            self.move_search_match("logs", 1)
        elif key == "p":
            if not self.move_search_match("logs", -1):
                self.log_previous = not self.log_previous
                self.log_autoscroll = True
                self.load_logs()
                self.flash("logs source: %s" % ("previous" if self.log_previous else "current"))
        elif key in ("]", "c"):
            self.cycle_log_container(1)
        elif key == "[":
            self.cycle_log_container(-1)
        elif key == "t":
            self.log_timestamps = not self.log_timestamps
            self.log_autoscroll = True
            self.load_logs()
        elif key == "w":
            self.log_wrap = not self.log_wrap
        elif key == "f":
            self.log_plain = not self.log_plain
            self.flash("plain logs %s" % ("on" if self.log_plain else "off"))
        elif key == "m":
            self.log_tail += 100
            self.log_autoscroll = True
            self.load_logs()
        elif key == "g":
            self.log_autoscroll = False
            self.scroll["logs"] = 0
        elif key == "b":
            self.log_autoscroll = True
            self.scroll["logs"] = max(0, len(self.filtered_log_lines(self.stdscr.getmaxyx()[1] - 4)) - 1)
        elif key == "r":
            self.load_logs()

    def start_filter(self, forced_key: Optional[str] = None) -> None:
        """Start editing a context-aware filter. / Запускает редактирование контекстного фильтра.

        Args:
            forced_key: Optional explicit filter key.
        """
        if forced_key:
            key = forced_key
        elif self.page == "overview":
            if self.focus in ("nodes", "overview_namespaces", "pods"):
                key = self.focus
            else:
                key = "pods"
        elif self.page == "namespace":
            key = "pods"
        elif self.page == "cronjobs":
            key = "cronjobs"
        elif self.page == "logs":
            key = "logs"
        elif self.page == "viewer":
            key = "viewer"
        elif self.page == "namespaces":
            key = "namespace_picker"
        else:
            return
        self.editing_filter = key
        self.filter_buffer = self.filters.get(key, "")

    def reset_selections(self) -> None:
        for key in self.selected:
            self.selected[key] = 0
        for key in self.scroll:
            self.scroll[key] = 0
        for key in self.hscroll:
            self.hscroll[key] = 0

    def push_page(
        self,
        page: str,
        node_name: Optional[str] = None,
        namespace_name: Optional[str] = None,
        pod_key: Optional[Tuple[str, str]] = None,
        cronjob_key: Optional[Tuple[str, str]] = None,
        container_name: Optional[str] = None,
    ) -> None:
        """Push a new page onto navigation stack. / Открывает страницу через navigation stack.

        Args:
            page: Target page name.
            node_name: Optional current node.
            namespace_name: Optional current namespace.
            pod_key: Optional current pod key.
            cronjob_key: Optional current CronJob key.
            container_name: Optional current container.
        """
        self.stack.append((self.page, self.current_node, self.current_pod, self.current_container, self.current_cronjob))
        self.page = page
        if node_name:
            self.current_node = node_name
        if namespace_name:
            self.current_namespace = namespace_name
        if pod_key:
            self.current_pod = pod_key
        if cronjob_key:
            self.current_cronjob = cronjob_key
        if container_name:
            self.current_container = container_name
        if page == "logs":
            self.scroll["logs"] = 0
        elif page == "cronjobs":
            self.scroll["cronjobs"] = 0
            self.hscroll["cronjobs"] = 0
        elif page == "cronjob":
            self.scroll["cronjob_pods"] = 0
            self.hscroll["cronjob_pods"] = 0
        elif page == "health":
            self.scroll["health"] = 0
            self.health_focus = HEALTH_PANEL_KEYS[0]
            for key in HEALTH_PANEL_KEYS:
                self.scroll[key] = 0
                self.hscroll[key] = 0
        elif page == "resources":
            self.scroll["resources"] = 0
            self.resource_focus = RESOURCE_PANEL_KEYS[0]
            for key in RESOURCE_PANEL_KEYS:
                self.scroll[key] = 0
                self.hscroll[key] = 0
        elif page in ("help", "health", "resources", "owner", "diagnostics", "viewer"):
            self.scroll[page] = 0

    def pop_page(self) -> None:
        if self.stack:
            self.page, self.current_node, self.current_pod, self.current_container, self.current_cronjob = self.stack.pop()
        else:
            self.page = "overview"

    def open_namespace_picker(self) -> None:
        if self.page != "namespaces":
            self.push_page("namespaces")
        rows = self.namespace_rows()
        current = self.filters.get("namespace", "") or "(all)"
        if current in rows:
            self.selected["namespaces"] = rows.index(current)
        else:
            self.selected["namespaces"] = 0
        self.scroll["namespaces"] = 0

    def open_diagnostics(self) -> None:
        self.diagnostics_cache = ["Running diagnostics..."]
        if self.page != "diagnostics":
            self.push_page("diagnostics")
        try:
            self.diagnostics_cache = self.client.diagnostics_lines()
        except DataError as exc:
            self.diagnostics_cache = ["Metrics / RBAC diagnostics", "", "FAIL   diagnostics %s" % exc]
        self.scroll["diagnostics"] = 0

    def cycle_log_container(self, direction: int) -> None:
        pod = self.find_pod(self.current_pod)
        if not pod or not pod.containers:
            return
        names = [container.name for container in pod.containers]
        current = self.current_container if self.current_container in names else names[0]
        idx = names.index(current)
        idx = (idx + direction) % len(names)
        self.current_container = names[idx]
        self.selected["containers"] = idx
        self.log_lines = []
        self.scroll["logs"] = 0
        self.log_autoscroll = True
        self.load_logs()
        self.flash("container: %s" % self.current_container)

    def load_logs(self) -> None:
        """Refresh current log buffer. / Обновляет текущий буфер logs."""
        pod = self.find_pod(self.current_pod)
        if not pod or not self.current_container:
            return
        try:
            self.log_lines = self.client.get_logs(
                pod.namespace,
                pod.name,
                self.current_container,
                self.log_tail,
                self.log_timestamps,
                previous=self.log_previous,
            )
            self.last_log_refresh = time.time()
        except DataError as exc:
            self.log_lines = ["ERROR: %s" % exc]
            self.last_log_refresh = time.time()

    def adjust_scroll(self, key: str, selected: int, page_size: int, count: int, selection_is_scroll: bool = False) -> int:
        """Keep scroll offset inside visible range. / Удерживает scroll offset в видимом диапазоне.

        Args:
            key: Scroll state key.
            selected: Selected row index.
            page_size: Visible row count.
            count: Total row count.
            selection_is_scroll: Whether selected is already a scroll position.
        Returns:
            New scroll offset.
        """
        if count <= 0 or page_size <= 0:
            self.scroll[key] = 0
            return 0
        current = self.scroll.get(key, 0)
        if selection_is_scroll:
            current = max(0, min(count - 1, current))
        else:
            if selected < current:
                current = selected
            elif selected >= current + page_size:
                current = selected - page_size + 1
            current = max(0, min(max(0, count - page_size), current))
        self.scroll[key] = current
        return current

    def status_attr(self, status: str) -> int:
        if status in ("OK", "Active", "Ready", "Running", "Completed", "Complete", "True"):
            return self.colors.get("green", 0)
        if status in ("Pending", "NotReady", "Terminating", "ContainerCreating", "Waiting", "Suspended", "Slow", "LongRunning"):
            return self.colors.get("yellow", 0)
        if status in ("Failed", "Missed", "Error", "CrashLoopBackOff", "Unknown", "False"):
            return self.colors.get("red", 0)
        return 0

    def resource_attr(self, value_ratio: float) -> int:
        if value_ratio >= 0.9:
            return self.colors.get("red", 0)
        if value_ratio >= 0.5:
            return self.colors.get("yellow", 0)
        return self.colors.get("green", 0)

    def bar(self, width: int, value_ratio: float) -> str:
        width = max(3, width)
        fill = int(round(max(0.0, min(1.0, value_ratio)) * width))
        return "[" + (self.graph_bar_char() * fill).ljust(width) + "]"

    def trend_or_bar(self, history: Sequence[float], value_ratio: float, width: int = 10, total: float = 0.0) -> str:
        clean = [float(value or 0.0) for value in history if math.isfinite(float(value or 0.0))]
        if clean:
            current = clean[-1]
            scale_total = total if total > 0 else current / value_ratio if value_ratio > 0 and current > 0 else 1.0
            return "[" + self.graph_line(clean, current, width, scale_total) + "]"
        return self.bar(width, value_ratio)

    def history_arrow(self, history: Sequence[float]) -> str:
        clean = [float(value or 0.0) for value in history if math.isfinite(float(value or 0.0))]
        if len(clean) < 2:
            return " "
        delta = clean[-1] - clean[-2]
        baseline = max(abs(clean[-2]), 1.0)
        if abs(delta) / baseline < 0.02:
            return " "
        return "↑" if delta > 0 else "↓"

    def display_usage(self, usage: float, fallback: float, history: Sequence[float]) -> float:
        if history:
            return float(usage or 0.0)
        return float(usage or fallback or 0.0)

    def trend_value(self, history: Sequence[float], value: float, formatter: Any, width: int = 6) -> str:
        del width
        return "%s %s" % (formatter(value), self.history_arrow(history))

    def graph_uses_unicode(self) -> bool:
        return getattr(self.args, "graph_style", DEFAULT_GRAPH_STYLE) == "unicode"

    def graph_bar_char(self) -> str:
        return "▁" if self.graph_uses_unicode() else "_"

    def graph_fill_char(self) -> str:
        return "█" if self.graph_uses_unicode() else "#"

    def graph_levels(self) -> str:
        return "▁▂▃▄▅▆▇█" if self.graph_uses_unicode() else "._:-=+*#"

    def graph_level_char(self, units: int) -> str:
        if units <= 0:
            return " "
        levels = self.graph_levels()
        return levels[min(len(levels), units) - 1]

    def graph_scale_high(self, values: Sequence[float], total: float, sample_count: int, plot_h: int) -> float:
        """Choose graph scale ceiling. / Выбирает верхнюю границу масштаба графика.

        Args:
            values: Values to render.
            total: Fixed capacity scale, if available.
            sample_count: Count of real samples before padding.
            plot_h: Graph height in terminal rows.
        Returns:
            Positive scale denominator.
        """
        high = max(max(values), 1.0) if values else 1.0
        if total > 0:
            return max(total, 1.0)
        if sample_count <= 1:
            return max(high * max(1, plot_h), 1.0)
        return high

    def draw_graph_rows(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        history: Sequence[float],
        current: float,
        total: float,
        attr: Optional[int] = None,
    ) -> None:
        """Draw a multi-row block graph. / Рисует многострочный block-график.

        Args:
            y: Top row.
            x: Left column.
            height: Graph height.
            width: Graph width.
            history: Retained values.
            current: Current value.
            total: Fixed capacity scale, if available.
            attr: Optional forced curses attribute.
        """
        height = max(1, int(height))
        width = max(1, int(width))
        sample_count = len([value for value in history if math.isfinite(float(value or 0.0))])
        values = self.chart_values(history, current, width)
        if not values:
            return
        high = self.graph_scale_high(values, total, sample_count, height)
        levels_count = len(self.graph_levels())
        max_units = max(1, height * levels_count)
        actual_count = self.chart_sample_count(history, current, width)
        # Padding cells should stay blank for "unknown past", but real zero
        # samples are rendered as a low baseline.
        # Padding слева означает неизвестное прошлое; реальные нули рисуем baseline.
        actual_start = max(0, width - actual_count)
        for col, value in enumerate(values[-width:]):
            is_padding = col < actual_start
            units = int(round((max(0.0, value) / high) * max_units))
            if value > 0:
                units = max(1, units)
            elif not is_padding:
                units = 1
            cell_attr = attr if attr is not None else self.chart_attr(value, total)
            for row in range(height):
                row_from_bottom = height - row - 1
                row_units = max(0, min(levels_count, units - row_from_bottom * levels_count))
                char = self.graph_level_char(row_units)
                if char != " ":
                    self.add(y + row, x + col, char, cell_attr, 1)

    def graph_line(self, history: Sequence[float], current: float, width: int, total: float = 0.0) -> str:
        """Render an inline sparkline/bar segment. / Рендерит inline sparkline/bar сегмент.

        Args:
            history: Retained values.
            current: Current value used when history is empty.
            width: Output width.
            total: Fixed capacity scale, if available.
        Returns:
            Graph text with exactly width characters.
        """
        width = max(1, int(width))
        values = self.chart_values(history, current, width)
        if not values:
            return " " * width
        high = self.graph_scale_high(values, total, len(history), 1)
        levels = self.graph_levels()
        scale = float(len(levels) - 1) / high
        max_index = len(levels) - 1
        return "".join(levels[max(0, min(max_index, int(round(max(0.0, value) * scale))))] for value in values[-width:])

    def box(self, y: int, x: int, height: int, width: int, title: str = "", focused: bool = False) -> None:
        if height <= 0 or width <= 0:
            return
        attr = self.colors.get("cyan", 0) if focused else 0
        horizontal = "─" * max(0, width - 2)
        self.add(y, x, "┌" + horizontal + "┐", attr, width)
        for row in range(1, height - 1):
            self.add(y + row, x, "│", attr, 1)
            self.add(y + row, x + width - 1, "│", attr, 1)
        if height > 1:
            self.add(y + height - 1, x, "└" + horizontal + "┘", attr, width)
        if title:
            self.add(y, x + 2, " %s " % truncate(title, max(1, width - 4)), 0, width - 4)

    def add(self, y: int, x: int, text: Any, attr: int = 0, width: Optional[int] = None) -> None:
        max_y, max_x = self.stdscr.getmaxyx()
        if y < 0 or y >= max_y or x < 0 or x >= max_x:
            return
        if width is None:
            width = max_x - x
        width = max(0, min(width, max_x - x))
        if width <= 0:
            return
        value = truncate(text, width)
        try:
            self.stdscr.addstr(y, x, value, attr)
        except curses.error:
            pass


def help_lines() -> List[str]:
    """Return TUI help text. / Возвращает текст справки TUI.

    Returns:
        Lines shown on the help page.
    """
    return [
        "ktop-py.py controls",
        "Latin hotkeys also accept CapsLock and Russian ЙЦУКЕН letters on the same physical keys.",
        "For Russian layout, the physical / key is accepted as . or , for filters.",
        "",
        "Overview:",
        "  Tab / Shift-Tab   cycle focus between primary table and pods",
        "  Left / Right      scroll focused table horizontally",
        "  g                 toggle primary table: nodes / namespaces",
        "  j                 open CronJob diagnostics",
        "  2                 choose namespace from a list",
        "  /                 edit row filter in the focused table",
        "  Enter             drill down into selected node, namespace, or pod",
        "  d / y             describe / YAML for selected object",
        "  h or !            open Problems / Health",
        "  z                 open Resource Risk",
        "  x                 open Metrics / RBAC diagnostics",
        "  u                 refresh cluster data",
        "  n/a/r/i/p/t/s/v/k/c/m/e/o sort node table by visible column letters",
        "  n/s/p/a/r/f/c/m/e/o sort namespace table by visible column letters",
        "  n/p/r/s/t/a/v/i/o/c/m sort pod table by visible column letters",
        "  ESC ESC or q      quit",
        "",
        "CronJobs:",
        "  j                 open CronJob list from any page",
        "  /                 filter CronJobs by namespace/name/status/hint",
        "  Enter             open CronJob detail with SLA, jobs, events, and related pods",
        "  d / y             describe / YAML for selected CronJob",
        "  n/j/s/l/x/a/o/f/p sort CronJob table by visible column letters",
        "",
        "Details:",
        "  ESC               go back",
        "  Left / Right      scroll focused detail table horizontally",
        "  d / y             describe / YAML for selected object",
        "  Enter             node/namespace detail -> pod detail, pod detail -> container logs",
        "  l                 pod detail -> container logs",
        "  n                 pod detail -> node detail",
        "  o                 pod detail -> workload/owner view",
        "  r or u            refresh cluster data",
        "",
        "Describe / YAML viewer:",
        "  d / y             switch between describe and YAML for the same object",
        "  r                 reload selected object",
        "  w                 toggle wrapping",
        "  f                 toggle plain copy mode without frames/header/footer",
        "  /                 live regex search and highlight; invalid regex falls back to substring",
        "  n / p             next / previous match",
        "  g / b             top / bottom",
        "",
        "Logs:",
        "  s                 toggle periodic log refresh",
        "  p                 toggle kubectl logs --previous when no search query is active",
        "  c / [ / ]         switch container",
        "  t                 toggle kubectl --timestamps",
        "  w                 toggle wrapping",
        "  f                 toggle plain copy mode without frames/header/footer",
        "  m                 load 100 more lines",
        "  /                 live regex search and highlight; invalid regex falls back to substring",
        "  n / p             next / previous match while search is active",
        "  g / b             top / bottom",
        "",
        "Diagnostics:",
        "  r                 rerun checks",
        "",
        "Health:",
        "  h or !            open Problems / Health",
        "  Tab / Shift+Tab   switch focused health panel",
        "  ↑ / ↓             scroll focused panel",
        "  ← / →             horizontal scroll in focused panel",
        "  r or u            refresh cluster data",
        "",
        "Resource Risk:",
        "  z                 open missing requests/limits and top resource consumers",
        "  Tab / Shift+Tab   switch focused risk panel",
        "  ↑ / ↓             scroll focused panel",
        "  ← / →             horizontal scroll in focused panel",
        "  r or u            refresh cluster data",
        "",
        "Namespaces:",
        "  2                 open namespace picker",
        "  /                 filter namespace list",
        "  Enter             apply selected namespace, (all) clears filter",
    ]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser. / Создает CLI argument parser.

    Returns:
        Configured argparse parser.
    """
    parser = argparse.ArgumentParser(
        prog="ktop-py.py",
        description="Single-file Python 3.8 Kubernetes top-like TUI inspired by ktop.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--kubeconfig", help="Path to kubeconfig passed to kubectl")
    parser.add_argument("--context", help="Kubeconfig context passed to kubectl")
    parser.add_argument("-n", "--namespace", default=None, help="Namespace to display")
    parser.add_argument(
        "-A",
        "--all-namespaces",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Display all accessible namespaces; this is the default when --namespace is omitted",
    )
    parser.add_argument("--metrics-source", default="prometheus", choices=["prometheus", "prom", "metrics-server", "none"], help="Metrics source mode")
    parser.add_argument("--prometheus-scrape-interval", type=parse_duration_seconds, default=DEFAULT_PROMETHEUS_SCRAPE_SECONDS, help="Direct scrape interval, accepts seconds or 15s/5m/1h suffixes")
    parser.add_argument("--prometheus-retention", type=parse_duration_seconds, default=DEFAULT_PROMETHEUS_RETENTION_SECONDS, help="In-memory metrics retention, accepts seconds or 15s/5m/1h suffixes")
    parser.add_argument("--prometheus-max-samples", type=int, default=DEFAULT_PROMETHEUS_MAX_SAMPLES, help="Maximum retained samples per metric series")
    parser.add_argument("--prometheus-components", default="kubelet,cadvisor", help="Comma-separated direct scrape components: kubelet,cadvisor")
    parser.add_argument("--graph-style", choices=["unicode", "ascii"], default=DEFAULT_GRAPH_STYLE, help="Graph glyph style; use ascii as a fallback for terminals without block/sparkline glyphs")
    parser.add_argument("--node-columns", default="", help="Comma-separated node columns to display")
    parser.add_argument("--pod-columns", default="", help="Comma-separated pod columns to display")
    parser.add_argument("--show-all-columns", action="store_true", default=True, help="Compatibility flag; all columns are shown unless column lists are provided")
    parser.add_argument("--refresh-interval", type=float, default=DEFAULT_REFRESH_SECONDS, help="TUI refresh interval in seconds")
    parser.add_argument("--request-timeout", default="8s", help="kubectl --request-timeout value")
    parser.add_argument("--command-timeout", type=float, default=12.0, help="subprocess timeout for kubectl commands")
    parser.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"), help="kubectl executable path")
    parser.add_argument("--log-tail", type=int, default=200, help="Initial kubectl logs --tail value")
    parser.add_argument("--demo", action="store_true", help="Run with synthetic data and no kubectl")
    parser.add_argument("--dump", action="store_true", help="Print one snapshot and exit")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format for --dump")
    parser.add_argument("--include-raw", action="store_true", help="Include raw Kubernetes node/pod objects in JSON dump")
    parser.add_argument("--dump-pods", choices=["all", "none", "problems", "top-cpu", "top-mem"], default="all", help="Pod set to include in --dump output")
    parser.add_argument("--dump-pod-filter", default="", help="Case-insensitive substring filter for dumped pods")
    parser.add_argument("--dump-pod-namespaces", default="", help="Comma-separated exact namespaces to include in dumped pods")
    parser.add_argument("--dump-pod-limit", type=parse_nonnegative_int, default=0, help="Maximum dumped pod rows; 0 means no limit")
    parser.add_argument("--dump-graph-width", type=parse_positive_int, default=DEFAULT_DUMP_GRAPH_WIDTH, help="Default sample window for dump max values")
    parser.add_argument("--dump-max-interval", type=parse_duration_seconds, default=0.0, help="Max-value window duration for --dump, e.g. 30s/5m; 0 uses --dump-graph-width samples without extra collection")
    parser.add_argument("--diagnostics", action="store_true", help="Run Metrics/RBAC diagnostics and exit")
    parser.add_argument("--self-test", action="store_true", help="Run built-in tests that do not require Kubernetes")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    return parser


def normalize_display_scope(args: argparse.Namespace, parser: Optional[argparse.ArgumentParser] = None) -> argparse.Namespace:
    """Normalize namespace/all-namespaces scope. / Нормализует namespace/all-namespaces scope.

    Args:
        args: Parsed CLI args.
        parser: Optional parser used to report CLI errors.
    Returns:
        The same args object with ``all_namespaces`` populated.
    Raises:
        argparse.ArgumentTypeError: If mutually exclusive scope flags conflict.
    """
    explicit_all_namespaces = getattr(args, "all_namespaces", None) is True
    if explicit_all_namespaces and args.namespace:
        message = "--namespace and --all-namespaces are mutually exclusive for display scope"
        if parser is not None:
            parser.error(message)
        raise argparse.ArgumentTypeError(message)
    args.all_namespaces = explicit_all_namespaces or not bool(args.namespace)
    return args


def make_client(args: argparse.Namespace) -> Any:
    """Create the selected data client. / Создает выбранный data client.

    Args:
        args: Parsed CLI args.
    Returns:
        DemoClient or KubectlClient.
    Raises:
        DataError: If kubectl is required but unavailable.
    """
    normalize_display_scope(args)
    if args.demo:
        return DemoClient(args)
    client = KubectlClient(args)
    client.ensure_available()
    return client


def load_dump_snapshot(client: Any, args: argparse.Namespace) -> ClusterSnapshot:
    """Load snapshot for dump mode. / Загружает snapshot для режима dump.

    Args:
        client: Data client.
        args: Parsed CLI args.
    Returns:
        Final snapshot; with ``--dump-max-interval`` this includes collected history.
    """
    interval = float(getattr(args, "dump_max_interval", 0.0) or 0.0)
    if interval <= 0:
        return client.load_snapshot()
    samples = max(1, dump_sample_count(args))
    refresh = max(0.001, float(getattr(args, "refresh_interval", DEFAULT_REFRESH_SECONDS) or DEFAULT_REFRESH_SECONDS))
    snapshot: Optional[ClusterSnapshot] = None
    # An explicit interval turns one-shot dump into a small sampling run so max
    # values can cover the requested time window.
    # Явный interval превращает dump в короткий сбор samples для max-значений.
    for index in range(samples):
        snapshot = client.load_snapshot()
        if index < samples - 1:
            time.sleep(refresh)
    if snapshot is None:
        return client.load_snapshot()
    return snapshot


def run_self_test() -> int:
    """Run built-in offline tests. / Запускает встроенные offline-тесты.

    Returns:
        Process exit code, 0 on success.
    Raises:
        AssertionError: If an invariant fails.
    """
    assert parse_cpu_millis("250m") == 250.0
    assert parse_cpu_millis("2") == 2000.0
    assert round(parse_cpu_millis("500u"), 3) == 0.5
    assert parse_bytes("1Gi") == 1024.0 ** 3
    assert parse_bytes("128Mi") == 128.0 * 1024.0 ** 2
    assert parse_duration_seconds("1500ms") == 1.5
    assert parse_duration_seconds("2m") == 120.0
    assert parse_duration_seconds("1h") == 3600.0
    assert sanitize_terminal_text("a\x1bb\r\nc\t\x7f\x85") == "a^[b^M c ^?\\x85"
    assert truncate("a\x1bb", 10) == "a^[b"
    assert len(render_sparkline([1, 2, 3], 6)) == 6
    assert render_sparkline([5, 5, 5], 4) == SPARKLINE_LEVELS[0] * 4
    assert aggregate_histories([[1.0, 2.0, 3.0], [10.0]]) == [1.0, 2.0, 13.0]
    cron_reference = dt.datetime(2026, 6, 14, 12, 7, tzinfo=dt.timezone.utc)
    cron_next, cron_warning = cron_next_after("*/15 * * * *", cron_reference, "UTC")
    assert cron_warning == ""
    assert cron_next == dt.datetime(2026, 6, 14, 12, 15, tzinfo=dt.timezone.utc)
    assert cron_next_after("0/15 * * * *", cron_reference, "UTC")[0] == dt.datetime(2026, 6, 14, 12, 15, tzinfo=dt.timezone.utc)
    assert parse_cron_schedule("@hourly").minutes == {0}
    assert percentile([180.0, 120.0], 50.0) == 120.0
    assert percentile([180.0, 120.0], 95.0) == 180.0
    chart_app = object.__new__(KtopApp)
    chart_app.rate_chart_peaks = {}
    assert chart_app.chart_values([5.0], 5.0, 4) == [0.0, 0.0, 0.0, 5.0]
    assert chart_app.chart_values([2.0, 3.0], 3.0, 5) == [0.0, 0.0, 0.0, 2.0, 3.0]
    assert chart_app.rate_chart_scale(("cluster", "net"), [10.0], 20.0) == RATE_CHART_MIN_BYTES_PER_SECOND
    assert chart_app.rate_chart_scale(("cluster", "net"), [1024.0 * 1024.0], 20.0) == 1024.0 * 1024.0
    assert chart_app.rate_scale_title(1024.0) == "max:1Ki/s"
    chart_app.args = argparse.Namespace(graph_style="unicode")
    assert chart_app.trend_or_bar([20.0, 40.0], 0.2, 4) == "[▁▁▂▂]"
    assert chart_app.trend_or_bar([], 0.25, 4) == "[▁   ]"
    assert chart_app.trend_or_bar([0.0, 133.0, 0.0], 0.0, 4, total=2000.0) == "[▁▁▁▁]"
    assert chart_app.graph_line([10.0, 200.0], 10.0, 4, 100.0) == "▁▁▂█"
    assert chart_app.chart_sample_count([0.0, 0.0], 0.0, 4) == 2

    class FakeScreen:
        def __init__(self, rows: int = 5, cols: int = 10) -> None:
            self.rows = rows
            self.cols = cols
            self.writes: List[Tuple[int, int, str, int]] = []

        def getmaxyx(self) -> Tuple[int, int]:
            return self.rows, self.cols

        def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
            self.writes.append((y, x, text, attr))

    fake_screen = FakeScreen()
    chart_app.stdscr = fake_screen
    chart_app.draw_graph_rows(0, 0, 1, 4, [0.0, 0.0], 0.0, 100.0, 0)
    assert [(y, x, text) for y, x, text, _ in fake_screen.writes] == [(0, 2, "▁"), (0, 3, "▁")]
    assert hotkey("c") == "c"
    assert hotkey("C") == "c"
    assert hotkey("с") == "c"
    assert hotkey("С") == "c"
    assert hotkey("к") == "r"
    assert hotkey("К") == "r"
    assert hotkey("з") == "p"
    assert hotkey("З") == "p"
    assert is_upper_key("З")
    assert hotkey("2") == "2"
    assert hotkey(".") == "/"
    assert hotkey(",") == "/"
    for lower, upper, expected in [
        ("й", "Й", "q"),
        ("ы", "Ы", "s"),
        ("р", "Р", "h"),
        ("ч", "Ч", "x"),
        ("г", "Г", "u"),
        ("т", "Т", "n"),
        ("д", "Д", "l"),
        ("щ", "Щ", "o"),
        ("к", "К", "r"),
        ("с", "С", "c"),
        ("е", "Е", "t"),
        ("ц", "Ц", "w"),
        ("а", "А", "f"),
        ("ь", "Ь", "m"),
        ("п", "П", "g"),
        ("и", "И", "b"),
        ("х", "Х", "["),
        ("ъ", "Ъ", "]"),
    ]:
        assert hotkey(lower) == expected
        assert hotkey(upper) == expected
        assert hotkey(expected.upper()) == expected
    top_node = parse_top_nodes("minikube 239m 4% 1502Mi 9%\n")["minikube"]
    assert top_node.cpu_m == 239.0
    assert top_node.mem_b == parse_bytes("1502Mi")
    pods_top = parse_top_pods("default web 126m 180Mi\n", "default", True)
    assert pods_top[("default", "web")].cpu_m == 126.0
    assert pods_top[("default", "web")].mem_b == parse_bytes("180Mi")
    metrics_nodes = parse_metrics_server_nodes(
        {
            "items": [
                {
                    "metadata": {"name": "node-a"},
                    "usage": {"cpu": "123456789n", "memory": "256Mi"},
                }
            ]
        }
    )
    assert round(metrics_nodes["node-a"].cpu_m, 3) == 123.457
    assert metrics_nodes["node-a"].mem_b == parse_bytes("256Mi")
    metrics_pods, metrics_containers = parse_metrics_server_pods(
        {
            "items": [
                {
                    "metadata": {"namespace": "default", "name": "web"},
                    "containers": [
                        {"name": "app", "usage": {"cpu": "25m", "memory": "64Mi"}},
                        {"name": "sidecar", "usage": {"cpu": "75000000n", "memory": "32Mi"}},
                    ],
                }
            ]
        }
    )
    assert round(metrics_pods[("default", "web")].cpu_m) == 100
    assert metrics_pods[("default", "web")].mem_b == parse_bytes("96Mi")
    assert round(metrics_containers[("default", "web", "sidecar")].cpu_m) == 75
    assert metrics_containers[("default", "web", "app")].mem_b == parse_bytes("64Mi")
    prom_text_a = "\n".join(
        [
            'container_cpu_usage_seconds_total{id="/"} 10',
            'container_memory_working_set_bytes{id="/"} 1048576',
            'container_cpu_usage_seconds_total{namespace="default",pod="web",container="app",id="/kubepods/a"} 2',
            'container_memory_working_set_bytes{namespace="default",pod="web",container="app",id="/kubepods/a"} 2097152',
            'container_network_receive_bytes_total{namespace="default",pod="web",interface="eth0"} 100',
            'container_network_transmit_bytes_total{namespace="default",pod="web",interface="eth0"} 200',
            'container_fs_reads_bytes_total{namespace="default",pod="web",container="app",device="/dev/sda"} 300',
            'container_fs_writes_bytes_total{namespace="default",pod="web",container="app",device="/dev/sda"} 500',
        ]
    )
    prom_text_b = "\n".join(
        [
            'container_cpu_usage_seconds_total{id="/"} 20',
            'container_memory_working_set_bytes{id="/"} 1048576',
            'container_cpu_usage_seconds_total{namespace="default",pod="web",container="app",id="/kubepods/a"} 7',
            'container_memory_working_set_bytes{namespace="default",pod="web",container="app",id="/kubepods/a"} 2097152',
            'container_network_receive_bytes_total{namespace="default",pod="web",interface="eth0"} 200',
            'container_network_transmit_bytes_total{namespace="default",pod="web",interface="eth0"} 260',
            'container_fs_reads_bytes_total{namespace="default",pod="web",container="app",device="/dev/sda"} 500',
            'container_fs_writes_bytes_total{namespace="default",pod="web",container="app",device="/dev/sda"} 650',
        ]
    )
    assert len(parse_prometheus_samples(prom_text_a)) == 8
    prom_args = build_arg_parser().parse_args(["--kubectl", "kubectl"])
    prom_client = KubectlClient(prom_args)
    hist_args = build_arg_parser().parse_args(["--prometheus-retention", "2s", "--prometheus-max-samples", "2"])
    hist_client = KubectlClient(hist_args)
    hist_key = history_key_node("node-a", "cpu")
    hist_client.add_history_sample(hist_key, 100.0, 1.0)
    hist_client.add_history_sample(hist_key, 101.0, 2.0)
    hist_client.add_history_sample(hist_key, 102.0, 3.0)
    assert history_values(hist_client.metric_history, hist_key) == [2.0, 3.0]
    gauge_key = history_key_pod("default", "web", "mem")
    hist_client.add_gauge_history_sample(gauge_key, 103.0, 0.0)
    assert gauge_key not in hist_client.metric_history
    hist_client.add_gauge_history_sample(gauge_key, 104.0, parse_bytes("64Mi"))
    assert history_values(hist_client.metric_history, gauge_key) == [parse_bytes("64Mi")]
    node_metrics_a: Dict[str, ResourceUsage] = {}
    pod_metrics_a: Dict[Tuple[str, str], ResourceUsage] = {}
    container_metrics_a: Dict[Tuple[str, str, str], ResourceUsage] = {}
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_a, 100.0, node_metrics_a, pod_metrics_a, container_metrics_a)
    node_metrics_b: Dict[str, ResourceUsage] = {}
    pod_metrics_b: Dict[Tuple[str, str], ResourceUsage] = {}
    container_metrics_b: Dict[Tuple[str, str, str], ResourceUsage] = {}
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_b, 110.0, node_metrics_b, pod_metrics_b, container_metrics_b)
    assert round(node_metrics_b["node-a"].cpu_m) == 1000
    assert round(pod_metrics_b[("default", "web")].cpu_m) == 500
    assert pod_metrics_b[("default", "web")].mem_b == 2097152
    assert round(pod_metrics_b[("default", "web")].net_rx_bps) == 10
    assert round(container_metrics_b[("default", "web", "app")].fs_read_bps) == 20
    prom_text_cpu_a = "\n".join(
        [
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="total"} 1',
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="0"} 100',
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="1"} 100',
        ]
    )
    prom_text_cpu_b = "\n".join(
        [
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="total"} 3',
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="0"} 200',
            'container_cpu_usage_seconds_total{namespace="default",pod="percpu",container="app",cpu="1"} 200',
        ]
    )
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_cpu_a, 120.0, {}, {}, {})
    per_cpu_nodes: Dict[str, ResourceUsage] = {}
    per_cpu_pods: Dict[Tuple[str, str], ResourceUsage] = {}
    per_cpu_containers: Dict[Tuple[str, str, str], ResourceUsage] = {}
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_cpu_b, 130.0, per_cpu_nodes, per_cpu_pods, per_cpu_containers)
    assert round(per_cpu_pods[("default", "percpu")].cpu_m) == 200
    assert round(per_cpu_containers[("default", "percpu", "app")].cpu_m) == 200
    prom_text_aggregate_a = "\n".join(
        [
            'container_cpu_usage_seconds_total{namespace="kube-system",pod="static",container="",cpu="total"} 4',
            'container_cpu_usage_seconds_total{namespace="kube-system",pod="static",container="POD",cpu="total"} 100',
            'container_cpu_usage_seconds_total{namespace="kube-system",pod="static",container="",image="registry.k8s.io/pause:3.10",name="pausehash",cpu="total"} 1000',
            'container_memory_working_set_bytes{namespace="kube-system",pod="static",container=""} 3145728',
            'container_memory_working_set_bytes{namespace="kube-system",pod="static",container="POD"} 999999999',
            'container_memory_working_set_bytes{namespace="kube-system",pod="static",container="",image="registry.k8s.io/pause:3.10",name="pausehash"} 888888888',
        ]
    )
    prom_text_aggregate_b = (
        prom_text_aggregate_a
        .replace('container="",cpu="total"} 4', 'container="",cpu="total"} 10')
        .replace('container="POD",cpu="total"} 100', 'container="POD",cpu="total"} 200')
        .replace('name="pausehash",cpu="total"} 1000', 'name="pausehash",cpu="total"} 2000')
    )
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_aggregate_a, 140.0, {}, {}, {})
    aggregate_nodes: Dict[str, ResourceUsage] = {}
    aggregate_pods: Dict[Tuple[str, str], ResourceUsage] = {}
    aggregate_containers: Dict[Tuple[str, str, str], ResourceUsage] = {}
    prom_client.process_cadvisor_prometheus_samples("node-a", prom_text_aggregate_b, 150.0, aggregate_nodes, aggregate_pods, aggregate_containers)
    assert round(aggregate_pods[("kube-system", "static")].cpu_m) == 600
    assert aggregate_pods[("kube-system", "static")].mem_b == 3145728
    assert ("kube-system", "static", "") in aggregate_containers
    static_infos = make_container_infos(
        {"spec": {"containers": [{"name": "static", "image": "static:demo"}]}, "status": {"containerStatuses": []}},
        {"": aggregate_containers[("kube-system", "static", "")]},
        {"": ([600.0, 610.0], [3145728.0, 4194304.0])},
    )
    assert round(static_infos[0].usage_cpu_m) == 600
    assert static_infos[0].usage_mem_b == 3145728
    assert static_infos[0].cpu_history == [600.0, 610.0]
    assert static_infos[0].mem_history == [3145728.0, 4194304.0]
    args = normalize_display_scope(build_arg_parser().parse_args(["--demo"]))
    assert args.all_namespaces
    namespace_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "-n", "kube-system"]))
    assert not namespace_args.all_namespaces
    assert namespace_args.namespace == "kube-system"
    snapshot = DemoClient(args).load_snapshot()
    assert len(snapshot.nodes) == 2
    assert len(snapshot.pods) >= 5
    assert snapshot.deployments_ready == 3
    assert snapshot.namespaces == ["default", "kube-system", "monitoring", "storage"]
    cron_rows = build_cronjob_rows(snapshot)
    assert len(cron_rows) == 1
    assert cron_rows[0].name == "nightly-backup"
    assert cron_rows[0].status in ("OK", "Active")
    assert cron_rows[0].succeeded == 2
    assert cron_rows[0].p50_s == 120.0
    cron_app = object.__new__(KtopApp)
    cron_app.snapshot = snapshot
    cron_app.filters = {"cronjobs": ""}
    cron_app.cronjob_sort = ("STATUS", True)
    cron_app.pod_sort = ("NAMESPACE", True)
    assert cron_app.current_cronjobs()[0].name == "nightly-backup"
    cron_app.current_cronjob = ("default", "nightly-backup")
    assert cron_app.find_cronjob(cron_app.current_cronjob).name == "nightly-backup"
    assert cron_app.cronjob_related_pods(cron_rows[0])[0].name == "nightly-backup-001-pod"
    namespace_app = object.__new__(KtopApp)
    namespace_app.snapshot = snapshot
    namespace_app.namespace_sort = ("NAMESPACE", True)
    namespace_app.filters = {"namespace": "", "nodes": "", "overview_namespaces": "kube", "pods": "", "logs": "", "namespace_picker": ""}
    namespace_rows = namespace_app.current_namespace_rows()
    assert [row.name for row in namespace_rows] == ["kube-system"]
    assert namespace_rows[0].pods_count == len([pod for pod in snapshot.pods if pod.namespace == "kube-system"])
    resource_app = object.__new__(KtopApp)
    resource_app.snapshot = snapshot
    resource_lines = resource_app.resource_risk_lines()
    assert resource_lines[0] == "Resource Risk"
    assert any("Top Namespaces by CPU" in line for line in resource_lines)
    assert snapshot.workloads[("Deployment", "default", "web")].status == "Ready"
    dump_args = normalize_display_scope(
        build_arg_parser().parse_args(
            [
                "--demo",
                "--dump",
                "--output",
                "json",
                "--dump-pod-namespaces",
                "default",
                "--dump-pod-limit",
                "1",
            ]
        )
    )
    dump_payload = json.loads(dump_snapshot_json(snapshot, dump_args))
    assert dump_payload["version"] == __VERSION__
    assert dump_payload["metrics_status"] == "demo metrics"
    assert dump_payload["dump"]["pod_count"] == 1
    assert dump_payload["dump"]["pod_total"] == len(snapshot.pods)
    assert dump_payload["pods"][0]["namespace"] == "default"
    assert dump_payload["cronjobs"][0]["name"] == "nightly-backup"
    assert dump_payload["cronjobs"][0]["duration_percentiles_seconds"]["p95"] == 180
    assert "max" in dump_payload["nodes"][0]["usage"]["cpu_m"]
    assert "containers" in dump_payload["pods"][0]
    namespace_dump_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "-n", "kube-system", "--dump", "--output", "json"]))
    namespace_dump_payload = json.loads(dump_snapshot_json(snapshot, namespace_dump_args))
    assert namespace_dump_payload["dump"]["pod_namespaces"] == ["kube-system"]
    assert all(pod["namespace"] == "kube-system" for pod in namespace_dump_payload["pods"])
    none_dump_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "--dump", "--output", "json", "--dump-pods", "none"]))
    assert json.loads(dump_snapshot_json(snapshot, none_dump_args))["pods"] == []
    top_dump_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "--dump", "--output", "json", "--dump-pods", "top-cpu", "--dump-pod-limit", "1"]))
    assert json.loads(dump_snapshot_json(snapshot, top_dump_args))["pods"][0]["name"] == "api-7bf6b99795-pnn5q"
    interval_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "--dump-max-interval", "11s", "--refresh-interval", "5"]))
    assert dump_sample_count(interval_args) == 3
    width_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "--dump-graph-width", "2"]))
    assert dump_metric_max([1.0, 5.0, 2.0], 3.0, width_args) == 5.0
    assert "max=" in dump_snapshot(snapshot, width_args)
    quick_dump_args = normalize_display_scope(build_arg_parser().parse_args(["--demo", "--dump-max-interval", "2ms", "--refresh-interval", "0.001"]))

    class CountingClient:
        def __init__(self, value: ClusterSnapshot) -> None:
            self.value = value
            self.calls = 0

        def load_snapshot(self) -> ClusterSnapshot:
            self.calls += 1
            return self.value

    counting_client = CountingClient(snapshot)
    assert load_dump_snapshot(counting_client, quick_dump_args) is snapshot
    assert counting_client.calls == 2
    web_pod = next(pod for pod in snapshot.pods if pod.name == "web-5d77b679d9-xbzqs")
    assert web_pod.owner_chain == [("ReplicaSet", "web-5d77b679d9"), ("Deployment", "web")]
    viewer_app = object.__new__(KtopApp)
    viewer_app.snapshot = snapshot
    viewer_app.page = "overview"
    viewer_app.focus = "pods"
    viewer_app.selected = {"pods": 0}
    viewer_app.filters = {"namespace": "", "nodes": "", "overview_namespaces": "", "pods": "api", "logs": "", "namespace_picker": "", "viewer": ""}
    viewer_app.pod_sort = ("NAMESPACE", True)
    viewer_target = viewer_app.selected_object_target()
    assert viewer_target and viewer_target.kind == "pod" and viewer_target.namespace == "default"
    demo_client = DemoClient(args)
    assert any("Kind:" in line for line in demo_client.describe_object("pod", "default", "api-7bf6b99795-pnn5q"))
    assert any(line == "kind: Pod" for line in demo_client.yaml_object("pod", "default", "api-7bf6b99795-pnn5q"))
    picker_app = object.__new__(KtopApp)
    picker_app.snapshot = snapshot
    picker_app.filters = {"namespace": "", "nodes": "", "overview_namespaces": "", "pods": "", "logs": "", "namespace_picker": "kube", "viewer": ""}
    assert picker_app.namespace_rows() == ["kube-system"]

    log_app = object.__new__(KtopApp)
    log_screen = FakeScreen()
    log_app.stdscr = log_screen
    log_app.log_lines = ["alpha", "beta"]
    log_app.log_wrap = False
    log_app.log_autoscroll = False
    log_app.filters = {"logs": "", "namespace": "", "nodes": "", "overview_namespaces": "", "pods": "", "namespace_picker": "", "viewer": ""}
    log_app.scroll = {"logs": 0}
    log_app.log_filter_error = ""
    log_app.draw_logs_plain(0, 0, 2, 20)
    assert [write[2] for write in log_screen.writes] == ["alpha", "beta"]
    log_app.filters["logs"] = "alpha"
    assert log_app.filtered_log_lines(20) == ["alpha", "beta"]
    assert log_app.search_match_lines(log_app.filtered_log_lines(20), "alpha", log_app.log_filter_error) == [0]
    assert log_app.query_match_spans("alpha alpha", "alpha") == [(0, 5), (6, 11)]
    assert log_app.query_match_spans("use [literal]", "[", "unterminated character set") == [(4, 5)]
    assert log_app.query_error("(a+)+$") == "potentially expensive nested repeat"
    assert log_app.search_match_lines(["literal (a+)+$ pattern"], "(a+)+$") == [0]
    assert log_app.query_error("x" * (MAX_SEARCH_REGEX_LENGTH + 1)).startswith("regex too long")

    viewer_screen = FakeScreen(cols=40)
    viewer_app.stdscr = viewer_screen
    viewer_app.viewer_lines = ["kind: Pod", "metadata:", "  name: api"]
    viewer_app.viewer_wrap = False
    viewer_app.viewer_title = "YAML: Pod/default/api"
    viewer_app.viewer_filter_error = ""
    viewer_app.filters["viewer"] = "kind"
    viewer_app.scroll = {"viewer": 0}
    viewer_app.colors = {"cyan": 0, "yellow": 0, "red": 0, "black_on_yellow": 0}
    viewer_app.draw_viewer_plain(0, 0, 3, 40)
    viewer_rows: Dict[int, str] = {}
    for row, _, text, _ in viewer_screen.writes:
        viewer_rows[row] = viewer_rows.get(row, "") + text
    assert [viewer_rows[idx] for idx in sorted(viewer_rows)] == ["kind: Pod", "metadata:", "  name: api"]
    assert sort_nodes(snapshot.nodes, "CPU", False)[0].name == "worker-a"
    assert any(match_text(pod_filter_values(pod), "api") for pod in snapshot.pods)
    assert "Overview" in "\n".join(help_lines()) or help_lines()
    print("self-test: ok")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Program entrypoint. / Точка входа программы.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.
    Returns:
        Process exit code.
    """
    parser = build_arg_parser()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw_argv)
    args.metrics_source_explicit = any(item == "--metrics-source" or item.startswith("--metrics-source=") for item in raw_argv)
    if args.version:
        print("ktop-py.py v%s" % __VERSION__)
        return 0
    if args.self_test:
        return run_self_test()
    normalize_display_scope(args, parser)
    try:
        client = make_client(args)
        if args.diagnostics:
            print("\n".join(client.diagnostics_lines()))
            return 0
        if args.dump:
            snapshot = load_dump_snapshot(client, args)
            if args.output == "json":
                print(dump_snapshot_json(snapshot, args))
            else:
                print(dump_snapshot(snapshot, args))
            return 0
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        curses.wrapper(lambda stdscr: KtopApp(stdscr, args, client).run())
        return 0
    except KeyboardInterrupt:
        return 130
    except DataError as exc:
        print("ktop-py.py: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
