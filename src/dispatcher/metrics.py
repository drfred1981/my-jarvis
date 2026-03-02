"""Prometheus metrics for the Jarvis dispatcher.

All metrics are defined here as module-level singletons.
Other modules import what they need.
"""

from prometheus_client import Counter, Gauge, Histogram

# --- Counters ---

MESSAGES_TOTAL = Counter(
    "jarvis_messages_total",
    "Total messages processed by Jarvis",
    ["channel", "status"],
)

NOTIFICATIONS_TOTAL = Counter(
    "jarvis_notifications_total",
    "Total notifications sent by the notifier",
    ["channel", "status"],
)

MONITOR_CHECKS_TOTAL = Counter(
    "jarvis_monitor_checks_total",
    "Total monitor check executions",
    ["check", "result"],
)

MONITOR_ALERTS_ACKNOWLEDGED_TOTAL = Counter(
    "jarvis_monitor_alerts_acknowledged_total",
    "Total alert acknowledgments",
    ["check"],
)

# --- Histograms ---

MESSAGE_DURATION_SECONDS = Histogram(
    "jarvis_message_duration_seconds",
    "Claude processing time per message",
    ["channel"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

MONITOR_CHECK_DURATION_SECONDS = Histogram(
    "jarvis_monitor_check_duration_seconds",
    "Monitor check execution time",
    ["check"],
    buckets=[5, 10, 30, 60, 120, 300],
)

# --- Gauges ---

WEBSOCKET_CONNECTIONS = Gauge(
    "jarvis_websocket_connections",
    "Number of active WebSocket connections",
)

ACTIVE_SESSIONS = Gauge(
    "jarvis_active_sessions",
    "Number of active Claude conversation sessions",
)

MONITOR_CHECK_PAUSED = Gauge(
    "jarvis_monitor_check_paused",
    "Whether a monitor check is paused (1) or running (0)",
    ["check"],
)

SERVICES_AVAILABLE = Gauge(
    "jarvis_services_available",
    "Whether a service is available (1) or not (0)",
    ["service"],
)
