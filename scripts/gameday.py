#!/usr/bin/env python3
"""A game day: break the system on purpose, one failure after another, under steady traffic, and judge each
failure against a hypothesis that was written down before it was run.

    python scripts/gameday.py list
    python scripts/gameday.py run --scenarios backend-pod-kill,bad-release --out gameday.md
    python scripts/gameday.py run --scenarios all --out gameday.md
    python scripts/gameday.py overhead --rounds 3 --seconds 45

For every scenario the tool does the same, so that the scenarios can be compared:

  1. it checks the steady state (every backend pod ready, requests answered) and refuses to break a system
     that is not healthy, because then the result would not say what the failure did
  2. it starts the load: reads and writes through the ingress, at a fixed rate, and a watcher of the alerts
  3. it injects the failure, and watches until the system has recovered (or the time for it has run out)
  4. it stops the load, and checks that every write that was acknowledged still exists
  5. it compares what it saw with the hypothesis of the scenario, and says PASS or FAIL for every number
  6. it puts the system back, and waits for the steady state again before the next scenario

The hypotheses are in SCENARIOS, next to the failures, and the numbers in them are the ones of the method documents
of the earlier phases (docs/engineering). A FAIL is a finding, and it is reported with the numbers, not hidden.

Needs the ingress on http://localhost:8080 and, for the alerts, Prometheus on http://localhost:9090. Standard library
only. Method and results: docs/engineering/game-day.md
"""

import argparse
import http.client
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import writeprobe  # noqa: E402  (the same slots and the same checks as the write probe of the database drills)

SLOW_MS = 250  # the latency objective of docs/engineering/slo.md


# ---------------------------------------------------------------------------------------------------------------
# What was observed, and how it is judged. These are plain functions of numbers, so they are tested without a cluster.
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Hypothesis:
    """What should be true after the failure. A limit that is None is not judged."""

    max_failed_pct: float | None = None  # of the reads, in percent
    max_outage_s: float | None = None  # the longest time without one answered read
    max_slow_pct: float | None = None  # of the answered reads, slower than SLOW_MS
    max_lost_writes: int | None = None  # acknowledged writes that are gone afterwards
    max_recovery_s: float | None = None  # from the injection to the recovered state
    max_backend_restarts: int | None = None  # restarts of the backend containers during the scenario


@dataclass
class Observed:
    reads: int = 0
    failed: int = 0
    slow: int = 0
    outage_s: float = 0.0
    writes_acknowledged: int = 0
    writes_failed: int = 0
    lost_writes: int | None = None
    recovery_s: float | None = None
    backend_restarts: int | None = None
    first_alert_s: float | None = None
    alerts: list[str] = field(default_factory=list)
    aborted: str = ""
    note: str = ""

    @property
    def failed_pct(self) -> float:
        return 100 * self.failed / self.reads if self.reads else 0.0

    @property
    def slow_pct(self) -> float:
        answered = self.reads - self.failed
        return 100 * self.slow / answered if answered else 0.0


def longest_gap(successes: list[float], start: float, end: float) -> float:
    """The longest stretch of the window in which no read was answered, from the times of the answered ones."""
    marks = [start] + sorted(t for t in successes if start <= t <= end) + [end]
    return max((b - a for a, b in zip(marks, marks[1:])), default=0.0)


def evaluate(h: Hypothesis, o: Observed) -> list[tuple[str, bool, str]]:
    """One line per number that the hypothesis speaks about: (what, held, the numbers)."""
    checks: list[tuple[str, bool, str]] = []

    def judge(what, limit, value, unit, ok=None):
        if limit is None:
            return
        held = (value is not None and value <= limit) if ok is None else ok
        shown = "not measured" if value is None else f"{value:.1f}{unit}" if isinstance(value, float) else f"{value}{unit}"
        checks.append((what, held, f"{shown}, limit {limit}{unit}"))

    judge("failed reads", h.max_failed_pct, o.failed_pct, " %")
    judge("longest time without an answer", h.max_outage_s, o.outage_s, " s")
    judge("slow answers", h.max_slow_pct, o.slow_pct, " %")
    judge("acknowledged writes lost", h.max_lost_writes, o.lost_writes, "")
    judge("time to recover", h.max_recovery_s, o.recovery_s, " s")
    judge("restarts of the backend", h.max_backend_restarts, o.backend_restarts, "")
    if o.aborted:
        checks.append(("the scenario ran to its end", False, o.aborted))
    return checks


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))] if ordered else 0.0


# ---------------------------------------------------------------------------------------------------------------
# The load: reads and writes at a fixed rate, with the time of every answer.
# ---------------------------------------------------------------------------------------------------------------


class Load:
    def __init__(self, base: str, read_rate: float = 10, write_rate: float = 3, first_slot: int = 0):
        self.base = base
        self.read_interval = 1 / read_rate
        self.write_interval = 1 / write_rate if write_rate else 0
        self.slot = first_slot
        self.stop_event = threading.Event()
        self.t0 = time.perf_counter()
        self.reads: list[tuple[float, bool, float]] = []  # (time, answered, milliseconds)
        self.acknowledged: list[int] = []
        self.write_failures = 0
        self._lock = threading.Lock()
        self._threads = [threading.Thread(target=self._reader, daemon=True)]
        if self.write_interval:
            self._threads.append(threading.Thread(target=self._writer, daemon=True))

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def start(self) -> None:
        self.t0 = time.perf_counter()
        for t in self._threads:
            t.start()

    def _connect(self) -> http.client.HTTPConnection:
        parts = urllib.parse.urlsplit(self.base)
        return http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=3)

    def _reader(self) -> None:
        conn = self._connect()
        nxt = time.perf_counter()
        while not self.stop_event.is_set():
            began = time.perf_counter()
            ok = False
            try:
                conn.request("GET", "/api/rooms")
                response = conn.getresponse()
                response.read()
                ok = response.status < 500
            except Exception:
                conn.close()
                conn = self._connect()
            with self._lock:
                self.reads.append((began - self.t0, ok, (time.perf_counter() - began) * 1000))
            nxt += self.read_interval
            time.sleep(max(0.0, nxt - time.perf_counter()))

    def _writer(self) -> None:
        conn = self._connect()
        nxt = time.perf_counter()
        while not self.stop_event.is_set():
            try:
                body = json.dumps(writeprobe.slot(self.slot))
                self.slot += 1
                conn.request("POST", "/api/bookings", body, {"Content-Type": "application/json"})
                response = conn.getresponse()
                payload = response.read()
                if response.status == 201:
                    with self._lock:
                        self.acknowledged.append(json.loads(payload)["id"])
                else:
                    self.write_failures += 1
            except Exception:
                self.write_failures += 1
                conn.close()
                conn = self._connect()
            nxt += self.write_interval
            time.sleep(max(0.0, nxt - time.perf_counter()))

    def recent_failed_pct(self, seconds: float) -> float:
        with self._lock:
            recent = [ok for t, ok, _ in self.reads if t >= self.now() - seconds]
        return 100 * recent.count(False) / len(recent) if len(recent) >= 10 else 0.0

    def stop(self) -> None:
        self.stop_event.set()
        for t in self._threads:
            t.join(timeout=5)

    def summarize(self, o: Observed) -> None:
        o.reads = len(self.reads)
        o.failed = sum(1 for _, ok, _ in self.reads if not ok)
        o.slow = sum(1 for _, ok, ms in self.reads if ok and ms > SLOW_MS)
        o.outage_s = longest_gap([t for t, ok, _ in self.reads if ok], 0.0, self.now())
        o.writes_acknowledged = len(self.acknowledged)
        o.writes_failed = self.write_failures


def count_lost(base: str, ids: list[int], attempts: int = 5) -> int:
    """How many of the acknowledged bookings are gone. A booking that cannot be asked about counts as lost."""
    lost = 0
    parts = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
    for booking_id in ids:
        for _ in range(attempts):  # the service may still be reconnecting for a moment
            try:
                conn.request("GET", f"/api/bookings/{booking_id}")
                response = conn.getresponse()
                response.read()
                if response.status == 404:
                    lost += 1
                break
            except Exception:
                conn.close()
                conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
                time.sleep(1)
        else:
            lost += 1
    return lost


# ---------------------------------------------------------------------------------------------------------------
# The cluster.
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Context:
    namespace: str = "campusslot"
    release: str = "campusslot"
    base: str = "http://localhost:8080"
    prometheus: str = "http://localhost:9090"
    chart: str = str(Path(__file__).resolve().parent.parent / "helm" / "campusslot")
    has_rollout: bool = False
    has_operator: bool = False
    synchronous: bool = False
    nodes: int = 1

    @property
    def backend(self) -> str:
        return f"{self.release}-backend"

    @property
    def cluster(self) -> str:
        return f"{self.release}-pg"


def sh(*args: str, timeout: float = 60) -> tuple[int, str]:
    try:
        out = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout.strip()
    except subprocess.TimeoutExpired:
        return 124, ""


def kubectl_json(ctx: Context, *args: str) -> dict:
    code, out = sh("kubectl", *args, "-n", ctx.namespace, "-o", "json")
    return json.loads(out) if code == 0 and out else {}


def backend_pods(ctx: Context) -> list[dict]:
    items = kubectl_json(ctx, "get", "pods", "-l", "app.kubernetes.io/component=backend").get("items", [])
    return [p for p in items if not p["metadata"].get("deletionTimestamp")]


def backend_ready(ctx: Context) -> tuple[int, int]:
    """(ready backend pods, the number that the workload wants)."""
    kind = "rollout" if ctx.has_rollout else "deployment"
    wanted = kubectl_json(ctx, "get", kind, ctx.backend).get("spec", {}).get("replicas", 0)
    ready = sum(
        1
        for p in backend_pods(ctx)
        if all(c.get("ready") for c in p.get("status", {}).get("containerStatuses", [{}]))
        and p.get("status", {}).get("containerStatuses")
    )
    return ready, wanted


def backend_restarts(ctx: Context) -> int:
    return sum(
        c.get("restartCount", 0)
        for p in backend_pods(ctx)
        for c in p.get("status", {}).get("containerStatuses", [])
    )


def cluster_healthy(ctx: Context) -> bool:
    status = kubectl_json(ctx, "get", "cluster", ctx.cluster).get("status", {})
    return status.get("phase") == "Cluster in healthy state" and status.get("readyInstances") == status.get("instances")


def rollout_phase(ctx: Context) -> str:
    return kubectl_json(ctx, "get", "rollout", ctx.backend).get("status", {}).get("phase", "?")


def prometheus_alerts(ctx: Context) -> list[str] | None:
    query = 'ALERTS{alertstate="firing", alertname=~"CampusSlot.*"}'
    try:
        url = f"{ctx.prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": query})
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.load(response)
        return sorted({r["metric"]["alertname"] for r in data["data"]["result"]})
    except Exception:
        return None


def steady(ctx: Context) -> tuple[bool, str]:
    ready, wanted = backend_ready(ctx)
    if wanted == 0 or ready < wanted:
        return False, f"{ready} of {wanted} backend pods are ready"
    if ctx.has_operator and not cluster_healthy(ctx):
        return False, "the database cluster is not healthy"
    if ctx.has_rollout and rollout_phase(ctx) != "Healthy":
        return False, f"the rollout is {rollout_phase(ctx)}"
    for _ in range(5):
        try:
            with urllib.request.urlopen(ctx.base + "/api/rooms", timeout=3) as response:
                response.read()
        except Exception as exc:
            return False, f"a request failed: {type(exc).__name__}"
        time.sleep(0.2)
    return True, "healthy"


def wait_until(predicate, seconds: float, interval: float = 2.0) -> float | None:
    """Seconds until the predicate holds, or None when it did not within the time."""
    start = time.time()
    while time.time() - start < seconds:
        if predicate():
            return time.time() - start
        time.sleep(interval)
    return None


def helm_set(ctx: Context, *sets: str) -> None:
    args = ["helm", "upgrade", ctx.release, ctx.chart, "--namespace", ctx.namespace, "--reuse-values"]
    for s in sets:
        args += ["--set-string", s]
    code, out = sh(*args, timeout=180)
    if code != 0:
        raise RuntimeError(f"helm upgrade failed: {out}")


# ---------------------------------------------------------------------------------------------------------------
# The scenarios. Each one: what is broken, how to tell that the system is back, and the hypothesis.
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    title: str
    hypothesis: Hypothesis
    why: str  # what is expected, and the reason, in a sentence
    applicable: callable  # (Context) -> (bool, reason)
    inject: callable  # (Context) -> None
    recovered: callable  # (Context) -> bool
    reset: callable = lambda ctx: None
    recovery_limit_s: float = 120
    inject_at_s: float = 15
    tail_s: float = 15
    abortable: bool = True  # stop early when more than half of the reads fail for 20 seconds


def _ok(_):
    return True, ""


def kill_backend_pod(ctx: Context) -> None:
    pods = backend_pods(ctx)
    sh("kubectl", "delete", "pod", pods[0]["metadata"]["name"], "-n", ctx.namespace, "--wait=false")


def kill_database_pod(ctx: Context) -> None:
    pod = f"{ctx.release}-postgres-0"
    sh("kubectl", "delete", "pod", pod, "-n", ctx.namespace, "--wait=false")


def database_pod_back(ctx: Context) -> bool:
    items = kubectl_json(ctx, "get", "pods", "-l", "app.kubernetes.io/component=postgres").get("items", [])
    return bool(items) and all(
        c.get("ready") for p in items for c in p.get("status", {}).get("containerStatuses", [{"ready": False}])
    )


def kill_primary(ctx: Context) -> None:
    code, primary = sh("kubectl", "get", "cluster", ctx.cluster, "-n", ctx.namespace, "-o", "jsonpath={.status.currentPrimary}")
    sh("kubectl", "delete", "pod", primary, "-n", ctx.namespace, "--grace-period=0", "--force", "--wait=false")


def release_with(ctx: Context, setting: str) -> None:
    helm_set(ctx, setting)


def reset_release(ctx: Context) -> None:
    helm_set(ctx, "backend.env.FAULT_ERROR_RATE=0", "backend.env.FAULT_LATENCY_MS=0")
    wait_until(lambda: rollout_phase(ctx) == "Healthy", 240)


def database_nodes(ctx: Context) -> set[str]:
    """The nodes that hold a database pod. Its volume is local to the node, so draining that node is the loss of the
    database and not a test of the backend, and it is a different scenario."""
    items = kubectl_json(ctx, "get", "pods", "-l", "app.kubernetes.io/component=postgres").get("items", [])
    items += kubectl_json(ctx, "get", "pods", "-l", "cnpg.io/cluster").get("items", [])
    return {p["spec"].get("nodeName", "") for p in items}


def drain_busiest_node(ctx: Context) -> None:
    per_node: dict[str, int] = {}
    avoid = database_nodes(ctx)
    for pod in backend_pods(ctx):
        node = pod["spec"].get("nodeName", "")
        if node not in avoid:
            per_node[node] = per_node.get(node, 0) + 1
    if not per_node:
        raise RuntimeError("every node with a backend pod also holds the database: nothing to drain without removing the database")
    node = max(per_node, key=per_node.get)
    ctx.__dict__["drained"] = node
    sh("kubectl", "drain", node, "--ignore-daemonsets", "--delete-emptydir-data", "--timeout=120s", timeout=150)


def uncordon(ctx: Context) -> None:
    node = ctx.__dict__.pop("drained", None)
    if node:
        sh("kubectl", "uncordon", node)


def aborted(ctx: Context) -> bool:
    return rollout_phase(ctx) == "Degraded"


SCENARIOS: list[Scenario] = [
    Scenario(
        name="backend-pod-kill",
        title="One backend pod is deleted",
        hypothesis=Hypothesis(max_failed_pct=0.5, max_outage_s=3, max_lost_writes=0, max_recovery_s=90, max_backend_restarts=0),
        why="The pod stays in the service for 8 seconds while it stops (preStop), the other pod serves, and a new one starts. "
        "Measured before in docs/engineering/resilience.md: 0 failed of 600.",
        applicable=_ok,
        inject=kill_backend_pod,
        recovered=lambda ctx: backend_ready(ctx)[0] == backend_ready(ctx)[1] and backend_ready(ctx)[1] > 0,
    ),
    Scenario(
        name="database-pod-restart",
        title="The only database pod is deleted",
        hypothesis=Hypothesis(max_outage_s=90, max_lost_writes=0, max_recovery_s=120, max_backend_restarts=0),
        why="Reads and writes fail while the database is away, as handled 503 answers (a liveness probe that does not depend on "
        "the database keeps the backend from restarting). The data is on the volume, so no acknowledged write is lost.",
        applicable=lambda ctx: (not ctx.has_operator, "the database is run by the operator: use database-primary-failover"),
        inject=kill_database_pod,
        recovered=database_pod_back,
        abortable=False,
    ),
    Scenario(
        name="database-primary-failover",
        title="The primary database pod is killed with no grace period",
        hypothesis=Hypothesis(max_outage_s=30, max_lost_writes=0, max_recovery_s=180, max_backend_restarts=0),
        why="The operator promotes the replica and the -rw Service follows. With asynchronous replication, the last few "
        "writes can be lost, and a loss is a finding. Synchronous replication must lose none.",
        applicable=lambda ctx: (ctx.has_operator, "the database is not run by the operator (postgres.operator.enabled)"),
        inject=kill_primary,
        recovered=cluster_healthy,
        abortable=False,
        recovery_limit_s=240,
    ),
    Scenario(
        name="bad-release",
        title="A release that is ready but fails 30 percent of its requests",
        hypothesis=Hypothesis(max_failed_pct=5, max_lost_writes=0, max_recovery_s=150),
        why="The canary receives 10 percent of the traffic, its own error ratio breaches 2 percent, and the rollout aborts. "
        "About 3 percent of the requests fail until then (docs/engineering/canary-releases.md).",
        applicable=lambda ctx: (ctx.has_rollout, "the backend is a Deployment (rollout.enabled)"),
        inject=lambda ctx: release_with(ctx, "backend.env.FAULT_ERROR_RATE=0.3"),
        recovered=aborted,
        reset=reset_release,
        recovery_limit_s=240,
    ),
    Scenario(
        name="slow-release",
        title="A release that is ready but takes 400 ms for every request",
        hypothesis=Hypothesis(max_failed_pct=1, max_slow_pct=15, max_lost_writes=0, max_recovery_s=150),
        why="The canary's share of fast requests falls under 95 percent and the rollout aborts. Only the canary's share of "
        "the traffic (10 percent, then 50 percent if it got that far) is slow.",
        applicable=lambda ctx: (ctx.has_rollout, "the backend is a Deployment (rollout.enabled)"),
        inject=lambda ctx: release_with(ctx, "backend.env.FAULT_LATENCY_MS=400"),
        recovered=aborted,
        reset=reset_release,
        recovery_limit_s=240,
    ),
    Scenario(
        name="node-drain",
        title="The node with most backend pods is drained",
        hypothesis=Hypothesis(max_failed_pct=1, max_outage_s=5, max_lost_writes=0, max_recovery_s=180),
        why="The disruption budget keeps one backend pod, the others move to another node, and the traffic follows the ready pods.",
        applicable=lambda ctx: (ctx.nodes >= 2, "the cluster has one node: a drain would remove everything"),
        inject=drain_busiest_node,
        recovered=lambda ctx: backend_ready(ctx)[0] == backend_ready(ctx)[1] and backend_ready(ctx)[1] > 0,
        reset=uncordon,
        recovery_limit_s=240,
    ),
]


def detect_context(ctx: Context) -> Context:
    ctx.has_rollout = sh("kubectl", "get", "rollout", ctx.backend, "-n", ctx.namespace)[0] == 0
    ctx.has_operator = sh("kubectl", "get", "cluster", ctx.cluster, "-n", ctx.namespace)[0] == 0
    if ctx.has_operator:
        code, out = sh("kubectl", "get", "cluster", ctx.cluster, "-n", ctx.namespace, "-o", "jsonpath={.spec.postgresql.synchronous.method}")
        ctx.synchronous = bool(out)
    code, out = sh("kubectl", "get", "nodes", "--no-headers")
    ctx.nodes = len(out.splitlines()) if code == 0 else 1
    return ctx


# ---------------------------------------------------------------------------------------------------------------
# Running a scenario.
# ---------------------------------------------------------------------------------------------------------------


def run_scenario(ctx: Context, s: Scenario, first_slot: int) -> tuple[Observed, list[tuple[str, bool, str]]]:
    o = Observed()
    hypothesis = s.hypothesis
    if s.name == "database-primary-failover" and not ctx.synchronous:
        # With asynchronous replication a few acknowledged writes may be lost. Five is the largest loss that this
        # drill accepts as "the window is small", and the number is reported either way.
        hypothesis = Hypothesis(**{**s.hypothesis.__dict__, "max_lost_writes": 5})

    restarts_before = backend_restarts(ctx)
    load = Load(ctx.base, first_slot=first_slot)
    stop_alerts = threading.Event()
    alerts_seen: dict[str, float] = {}

    def watch_alerts():
        while not stop_alerts.is_set():
            names = prometheus_alerts(ctx)
            for name in names or []:
                alerts_seen.setdefault(name, load.now())
            stop_alerts.wait(5)

    watcher = threading.Thread(target=watch_alerts, daemon=True)
    load.start()
    watcher.start()
    try:
        time.sleep(s.inject_at_s)
        injected_at = load.now()
        print(f"  +{injected_at:5.0f} s  inject: {s.title}", flush=True)
        try:
            s.inject(ctx)
        except Exception as exc:
            o.aborted = f"the injection failed: {exc}"
        if not o.aborted:
            began = time.time()
            while time.time() - began < s.recovery_limit_s:
                if s.recovered(ctx):
                    o.recovery_s = time.time() - began
                    print(f"  +{load.now():5.0f} s  recovered after {o.recovery_s:.0f} s", flush=True)
                    break
                if s.abortable and load.recent_failed_pct(20) > 50:
                    o.aborted = "more than half of the reads failed for 20 seconds: stopped to protect the system"
                    break
                time.sleep(2)
            else:
                print(f"  +{load.now():5.0f} s  not recovered within {s.recovery_limit_s:.0f} s", flush=True)
        time.sleep(s.tail_s)
    finally:
        load.stop()
        stop_alerts.set()

    load.summarize(o)
    o.backend_restarts = backend_restarts(ctx) - restarts_before
    o.alerts = sorted(alerts_seen)
    if alerts_seen:
        o.first_alert_s = min(alerts_seen.values()) - injected_at
    print("  verifying the acknowledged writes ...", flush=True)
    o.lost_writes = count_lost(ctx.base, load.acknowledged)
    return o, evaluate(hypothesis, o)


def render_report(rows: list[dict], ctx: Context) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Game day, {stamp}",
        "",
        f"Namespace `{ctx.namespace}`, {ctx.nodes} node(s). Rollout: {ctx.has_rollout}. Database operator: {ctx.has_operator}"
        + (f" (synchronous: {ctx.synchronous})." if ctx.has_operator else "."),
        "Load per scenario: 10 reads and 3 writes per second through the ingress.",
        "",
        "| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        o: Observed = r["observed"]
        if r["skipped"]:
            lines.append(f"| `{r['name']}` | skipped | | | | | {r['skipped']} |")
            continue
        verdict = "PASS" if all(ok for _, ok, _ in r["checks"]) else "**FAIL**"
        alert = f"{o.alerts[0]} after {o.first_alert_s:.0f} s" if o.alerts and o.first_alert_s is not None else "none"
        lines.append(
            f"| `{r['name']}` | {verdict} | {o.failed} of {o.reads} ({o.failed_pct:.2f} %) | {o.outage_s:.1f} s | "
            f"{o.lost_writes} of {o.writes_acknowledged} | "
            f"{'not recovered' if o.recovery_s is None else f'{o.recovery_s:.0f} s'} | {alert} |"
        )
    for r in rows:
        if r["skipped"]:
            continue
        s: Scenario = r["scenario"]
        lines += ["", f"## {s.title}", "", f"**Hypothesis.** {s.why}", ""]
        for what, held, detail in r["checks"]:
            lines.append(f"- {'PASS' if held else '**FAIL**'} {what}: {detail}")
        if r["observed"].note:
            lines.append(f"- note: {r['observed'].note}")
    return "\n".join(lines) + "\n"


def cmd_list(_args) -> int:
    for s in SCENARIOS:
        print(f"{s.name:<28} {s.title}")
    return 0


def cmd_run(args) -> int:
    ctx = detect_context(Context(namespace=args.namespace, release=args.release, base=args.base, prometheus=args.prometheus))
    wanted = [s for s in SCENARIOS if args.scenarios == "all" or s.name in args.scenarios.split(",")]
    if not wanted:
        print("no scenario matches. Known:", ", ".join(s.name for s in SCENARIOS))
        return 2
    rows = []
    slot = 10_000
    for s in wanted:
        print(f"== {s.name}: {s.title}", flush=True)
        ok, reason = s.applicable(ctx)
        if not ok:
            print(f"  skipped: {reason}")
            rows.append({"name": s.name, "scenario": s, "skipped": reason, "observed": Observed(), "checks": []})
            continue
        healthy, detail = steady(ctx)
        if not healthy:
            print(f"  skipped: the steady state does not hold ({detail}). A failure on a system that is not healthy proves nothing.")
            rows.append({"name": s.name, "scenario": s, "skipped": f"not steady: {detail}", "observed": Observed(), "checks": []})
            continue
        try:
            observed, checks = run_scenario(ctx, s, slot)
        finally:
            s.reset(ctx)
        slot += 5_000
        for what, held, detail in checks:
            print(f"  {'PASS' if held else 'FAIL'}  {what}: {detail}")
        rows.append({"name": s.name, "scenario": s, "skipped": "", "observed": observed, "checks": checks})
        print("  waiting for the steady state ...", flush=True)
        if wait_until(lambda: steady(ctx)[0], 300) is None:
            print("  the system did not return to the steady state: stopping the game day here")
            break
    report = render_report(rows, ctx)
    Path(args.out).write_text(report, encoding="utf-8", newline="\n")
    print(f"\nwrote {args.out}")
    failed = [r["name"] for r in rows if not r["skipped"] and not all(ok for _, ok, _ in r["checks"])]
    print("FAILED:", ", ".join(failed) if failed else "none")
    return 1 if failed else 0


# ---------------------------------------------------------------------------------------------------------------
# What does tracing cost? The same closed loop load, with tracing off, at a ratio of 0.1, and at 1, interleaved.
# ---------------------------------------------------------------------------------------------------------------


def closed_loop(base: str, seconds: float, threads: int, warmup: float = 10) -> dict:
    stop = time.time() + warmup + seconds
    measure_from = time.time() + warmup
    latencies: list[float] = []
    lock = threading.Lock()

    def worker():
        parts = urllib.parse.urlsplit(base)
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
        while time.time() < stop:
            began = time.time()
            try:
                conn.request("GET", "/api/rooms")
                conn.getresponse().read()
                ms = (time.time() - began) * 1000
                if began >= measure_from:
                    with lock:
                        latencies.append(ms)
            except Exception:
                conn.close()
                conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)

    pool = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    return {"n": len(latencies), "rps": len(latencies) / seconds, "p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)}


def summarize_overhead(rounds: dict[str, list[dict]]) -> list[str]:
    """Median and spread of each setting, and whether the cost of tracing can be told from the noise of the runs."""
    lines = ["| Tracing | Runs | Throughput (req/s) | p50 (ms) | p95 (ms) |", "|---|---|---|---|---|"]
    stats = {}
    for name, runs in rounds.items():
        rps = [r["rps"] for r in runs]
        p50 = [r["p50"] for r in runs]
        p95 = [r["p95"] for r in runs]
        stats[name] = {"rps": rps, "p95": p95}
        lines.append(
            f"| {name} | {len(runs)} | {statistics.median(rps):.0f} ({min(rps):.0f} to {max(rps):.0f}) | "
            f"{statistics.median(p50):.1f} | {statistics.median(p95):.1f} ({min(p95):.1f} to {max(p95):.1f}) |"
        )
    off = stats.get("off")
    if off and len(off["p95"]) >= 2:
        noise = (max(off["p95"]) - min(off["p95"])) / statistics.median(off["p95"]) * 100
        lines.append("")
        lines.append(f"The repeated runs with tracing off differ by {noise:.0f} percent in p95: that is the noise of this measurement.")
        for name in rounds:
            if name == "off":
                continue
            delta = (statistics.median(stats[name]["p95"]) / statistics.median(off["p95"]) - 1) * 100
            verdict = "not distinguishable from the noise" if abs(delta) <= noise else ("a cost" if delta > 0 else "faster than off, which is noise or a warm-up effect")
            lines.append(f"- {name}: median p95 is {delta:+.0f} percent against off, {verdict}.")
    return lines


def cmd_overhead(args) -> int:
    ctx = detect_context(Context(namespace=args.namespace, release=args.release, base=args.base))
    settings = {"off": ["tracing.enabled=false"], "ratio 0.1": ["tracing.enabled=true", "tracing.sampleRatio=0.1"], "ratio 1": ["tracing.enabled=true", "tracing.sampleRatio=1.0"]}
    names = list(settings)
    results: dict[str, list[dict]] = {n: [] for n in names}
    for round_index in range(args.rounds):
        order = names[round_index % len(names):] + names[: round_index % len(names)]  # a different order every round
        for name in order:
            args_set = []
            for item in settings[name]:
                args_set += ["--set", item] if item.startswith("tracing.enabled") else ["--set-string", item]
            code, out = sh("helm", "upgrade", ctx.release, ctx.chart, "--namespace", ctx.namespace, "--reuse-values", *args_set, timeout=180)
            if code != 0:
                print("helm upgrade failed:", out)
                return 1
            wait_until(lambda: steady(ctx)[0], 240)
            print(f"round {round_index + 1}, tracing {name} ...", flush=True)
            result = closed_loop(ctx.base, args.seconds, args.concurrency)
            print(f"  {result['rps']:.0f} req/s, p50 {result['p50']:.1f} ms, p95 {result['p95']:.1f} ms")
            results[name].append(result)
    print("\n".join(summarize_overhead(results)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    for name, func in (("run", cmd_run), ("overhead", cmd_overhead)):
        p = sub.add_parser(name)
        p.add_argument("--namespace", default="campusslot")
        p.add_argument("--release", default="campusslot")
        p.add_argument("--base", default="http://localhost:8080")
        p.set_defaults(func=func)
        if name == "run":
            p.add_argument("--prometheus", default="http://localhost:9090")
            p.add_argument("--scenarios", default="all", help="a comma separated list, or all")
            p.add_argument("--out", default="gameday.md")
        else:
            p.add_argument("--rounds", type=int, default=3)
            p.add_argument("--seconds", type=float, default=45)
            p.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
