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

# Tokens from Claude Code JSON output (usage field).
# type: input | output | cache_read | cache_creation
TOKENS_TOTAL = Counter(
    "jarvis_tokens_total",
    "Total tokens consumed by Jarvis",
    ["type"],
)

COST_USD_TOTAL = Counter(
    "jarvis_cost_usd_total",
    "Total cumulative cost in USD across all conversations",
)

# conversation_type: user | monitor | introspection
TURNS_TOTAL = Counter(
    "jarvis_turns_total",
    "Total agentic turns completed by Claude",
    ["conversation_type"],
)

# error_type: timeout | max_turns | cli_error
SESSION_ERRORS_TOTAL = Counter(
    "jarvis_session_errors_total",
    "Total session errors by type",
    ["error_type"],
)

# depth: light | medium | deep
INTROSPECTION_CYCLES_TOTAL = Counter(
    "jarvis_introspection_cycles_total",
    "Total autonomous introspection cycles run (Track B)",
    ["depth"],
)

COACH_INTERVENTIONS_TOTAL = Counter(
    "jarvis_coach_interventions_total",
    "Total coaching interventions posted to user conversations",
)

# reason: missing | outdated
STALE_CONTEXTS_DETECTED_TOTAL = Counter(
    "jarvis_stale_contexts_detected_total",
    "Total stale memory context nudges triggered during coach pass",
    ["reason"],
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

MEMORY_FILES_COUNT = Gauge(
    "jarvis_memory_files_count",
    "Number of .md memory files on NFS storage",
)

MEMORY_TOTAL_BYTES = Gauge(
    "jarvis_memory_total_bytes",
    "Total size of all memory files in bytes",
)

# context_name: global_state | conversations_avg
CONTEXT_FILE_SIZE_BYTES = Gauge(
    "jarvis_context_file_size_bytes",
    "Size of key context files in bytes",
    ["context_name"],
)
