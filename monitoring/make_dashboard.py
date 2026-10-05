"""Generate monitoring/grafana-dashboard.json.

The dashboard is written as code so every panel query is easy to review. Run it from the
repository root:  python monitoring/make_dashboard.py
"""

import json
from pathlib import Path

NS = 'namespace="campusslot"'
DS = {"type": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}


def panel(pid, title, expr, legend, x, y, w=12, h=8, unit="short", kind="timeseries", ds=None):
    ds = ds or DS
    return {
        "id": pid,
        "type": kind,
        "title": title,
        "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 12}}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": [{"refId": "A", "datasource": ds, "expr": expr, "legendFormat": legend}],
    }


panels = [
    panel(1, "Request rate by route", f'sum by (handler) (rate(http_requests_total{{{NS}}}[1m]))', "{{handler}}", 0, 0, unit="reqps"),
    panel(
        2,
        "Latency percentiles, all routes (seconds)",
        f"histogram_quantile(0.95, sum by (le) (rate(http_request_duration_highr_seconds_bucket{{{NS}}}[1m])))",
        "p95",
        12,
        0,
        unit="s",
    ),
    panel(3, "5xx error rate", f'sum(rate(http_requests_total{{{NS},status="5xx"}}[1m])) or vector(0)', "5xx per second", 0, 8, unit="reqps"),
    panel(
        4,
        "Booking conflicts rejected (409), by layer",
        f"sum by (layer) (increase(campusslot_booking_conflicts_total{{{NS}}}[5m]))",
        "{{layer}}",
        12,
        8,
    ),
    panel(
        5,
        "Backend CPU per pod (cores)",
        f'sum by (pod) (rate(container_cpu_usage_seconds_total{{{NS},container="backend"}}[1m]))',
        "{{pod}}",
        0,
        16,
    ),
    panel(
        6,
        "HPA: current vs desired backend replicas",
        f'kube_horizontalpodautoscaler_status_current_replicas{{{NS},horizontalpodautoscaler="campusslot-backend"}}',
        "current",
        12,
        16,
    ),
]
# The high-resolution histogram has fine buckets, so p50 and p99 sit next to p95 on the same panel.
for refId, q in (("B", 0.5), ("C", 0.99)):
    panels[1]["targets"].append(
        {
            "refId": refId,
            "datasource": DS,
            "expr": f"histogram_quantile({q}, sum by (le) (rate(http_request_duration_highr_seconds_bucket{{{NS}}}[1m])))",
            "legendFormat": f"p{int(q * 100)}",
        }
    )

# Second query on the HPA panel: the replica count the autoscaler wants.
panels[5]["targets"].append(
    {
        "refId": "B",
        "datasource": DS,
        "expr": f'kube_horizontalpodautoscaler_status_desired_replicas{{{NS},horizontalpodautoscaler="campusslot-backend"}}',
        "legendFormat": "desired",
    }
)

# Log based panels. Loki reads the JSON lines that the application writes to standard output.
panels.append(
    panel(
        7,
        "Rejected bookings per layer, counted from the logs",
        'sum by (layer) (count_over_time({app="campusslot", component="backend"} | json '
        '| message="booking rejected: overlapping slot" [1m]))',
        "{{layer}}",
        0,
        24,
        ds=LOKI,
    )
)
panels.append(
    panel(
        8,
        "Application logs",
        '{app="campusslot", component="backend"} | json | message != ""',
        "",
        12,
        24,
        kind="logs",
        ds=LOKI,
    )
)
panels[-1]["options"] = {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"}

dashboard = {
    "uid": "campusslot-overview",
    "title": "CampusSlot overview",
    "tags": ["campusslot"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "panels": panels,
}

out = Path(__file__).with_name("grafana-dashboard.json")
out.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out} with {len(panels)} panels")
