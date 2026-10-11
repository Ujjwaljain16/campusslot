"""Tests of the parts of scripts/gameday.py that need no cluster: the statistics, the verdicts, and the load with its
check for lost writes, against a small fake service that can have an outage and can lose bookings.

    python3 -m unittest discover -s scripts/tests -v
"""

import importlib.util
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

SCRIPTS =Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("gameday", SCRIPTS / "gameday.py")
gameday = importlib.util.module_from_spec(spec)
sys.modules["gameday"] = gameday
spec.loader.exec_module(gameday)


class FakeService:
    """GET /api/rooms, POST /api/bookings and GET /api/bookings/<id>, with the faults of a failure."""

    def __init__(self):
        self.outage = None  # (from_second, to_second) of the service, during which reads answer 503
        self.lost_ids: set[int] = set()
        self.next_id = 1
        self.started = time.time()
        self.lock = threading.Lock()
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=b"{}"):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _down(self):
                if service.outage:
                    t = time.time() - service.started
                    return service.outage[0] <= t < service.outage[1]
                return False

            def do_GET(self):
                if self.path == "/api/rooms":
                    self._send(503 if self._down() else 200, b"[]")
                elif self.path.startswith("/api/bookings/"):
                    booking_id = int(self.path.rsplit("/", 1)[1])
                    self._send(404 if booking_id in service.lost_ids else 200)
                else:
                    self._send(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                if self._down():
                    self._send(503)
                    return
                with service.lock:
                    booking_id = service.next_id
                    service.next_id += 1
                self._send(201, json.dumps({"id": booking_id}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class StatisticsTests(unittest.TestCase):
    def test_the_longest_gap_is_the_longest_stretch_without_an_answer(self):
        self.assertAlmostEqual(gameday.longest_gap([1, 2, 3, 8, 9], 0, 10), 5.0)

    def test_the_start_and_the_end_of_the_window_count(self):
        self.assertAlmostEqual(gameday.longest_gap([5], 0, 6), 5.0)
        self.assertAlmostEqual(gameday.longest_gap([1], 0, 10), 9.0)

    def test_no_answers_at_all_is_one_gap_as_long_as_the_window(self):
        self.assertAlmostEqual(gameday.longest_gap([], 0, 7), 7.0)

    def test_percentages_of_a_run(self):
        o = gameday.Observed(reads=200, failed=10, slow=19)
        self.assertAlmostEqual(o.failed_pct, 5.0)
        self.assertAlmostEqual(o.slow_pct, 10.0)  # of the 190 that were answered

    def test_percentile(self):
        self.assertEqual(gameday.percentile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertEqual(gameday.percentile([], 0.5), 0.0)


class VerdictTests(unittest.TestCase):
    H = gameday.Hypothesis(max_failed_pct=0.5, max_outage_s=3, max_lost_writes=0, max_recovery_s=90, max_backend_restarts=0)

    def observed(self, **changes):
        base = dict(reads=600, failed=0, outage_s=0.5, lost_writes=0, recovery_s=40.0, backend_restarts=0)
        base.update(changes)
        return gameday.Observed(**base)

    def test_everything_inside_the_limits_holds(self):
        checks = gameday.evaluate(self.H, self.observed())
        self.assertTrue(all(ok for _, ok, _ in checks))
        self.assertEqual(len(checks), 5)

    def test_one_number_over_its_limit_is_a_failure_that_names_it(self):
        checks = gameday.evaluate(self.H, self.observed(failed=12))
        failed = [what for what, ok, _ in checks if not ok]
        self.assertEqual(failed, ["failed reads"])

    def test_a_lost_write_is_a_failure(self):
        checks = gameday.evaluate(self.H, self.observed(lost_writes=1))
        self.assertIn("acknowledged writes lost", [what for what, ok, _ in checks if not ok])

    def test_a_system_that_never_recovered_fails_the_recovery_limit(self):
        checks = gameday.evaluate(self.H, self.observed(recovery_s=None))
        failed = {what: detail for what, ok, detail in checks if not ok}
        self.assertIn("time to recover", failed)
        self.assertIn("not measured", failed["time to recover"])

    def test_a_limit_that_is_not_set_is_not_judged(self):
        checks = gameday.evaluate(gameday.Hypothesis(max_lost_writes=0), self.observed(failed=300))
        self.assertEqual([what for what, _, _ in checks], ["acknowledged writes lost"])

    def test_an_aborted_scenario_is_never_a_pass(self):
        checks = gameday.evaluate(self.H, self.observed(aborted="stopped to protect the system"))
        self.assertFalse(all(ok for _, ok, _ in checks))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()

    def tearDown(self):
        self.service.close()

    def run_load(self, seconds):
        load = gameday.Load(self.service.base, read_rate=40, write_rate=10)
        load.start()
        time.sleep(seconds)
        load.stop()
        observed = gameday.Observed()
        load.summarize(observed)
        return load, observed

    def test_a_healthy_service_shows_no_failures_and_no_gap(self):
        load, o = self.run_load(1.5)
        self.assertGreater(o.reads, 30)
        self.assertEqual(o.failed, 0)
        self.assertGreater(o.writes_acknowledged, 8)
        self.assertLess(o.outage_s, 0.5)
        self.assertEqual(gameday.count_lost(self.service.base, load.acknowledged), 0)

    def test_an_outage_is_seen_as_failures_and_as_a_gap_of_about_its_length(self):
        self.service.started = time.time()
        self.service.outage = (0.5, 1.5)
        _, o = self.run_load(3.0)
        self.assertGreater(o.failed, 20)
        self.assertGreater(o.outage_s, 0.8)
        self.assertLess(o.outage_s, 1.6)

    def test_writes_that_are_gone_afterwards_are_counted_as_lost(self):
        load, _ = self.run_load(1.5)
        self.service.lost_ids = set(load.acknowledged[:3])
        self.assertEqual(gameday.count_lost(self.service.base, load.acknowledged), 3)

    def test_a_service_that_cannot_be_asked_counts_every_write_as_lost(self):
        self.service.close()
        self.assertEqual(gameday.count_lost("http://127.0.0.1:1", [1, 2], attempts=1), 2)
        self.service = FakeService()  # so that tearDown has something to close


class OverheadTests(unittest.TestCase):
    def runs(self, p95s):
        return [{"rps": 100.0, "p50": 5.0, "p95": p} for p in p95s]

    def test_a_difference_inside_the_noise_is_not_called_a_cost(self):
        lines = gameday.summarize_overhead(
            {"off": self.runs([20.0, 24.0, 22.0]), "ratio 1": self.runs([23.0, 21.0, 22.5])}
        )
        self.assertTrue(any("not distinguishable from the noise" in line for line in lines), lines)

    def test_a_difference_above_the_noise_is_called_a_cost(self):
        lines = gameday.summarize_overhead(
            {"off": self.runs([20.0, 20.5, 20.2]), "ratio 1": self.runs([30.0, 31.0, 30.5])}
        )
        self.assertTrue(any("a cost" in line for line in lines), lines)

    def test_the_noise_of_the_runs_with_tracing_off_is_reported(self):
        lines = gameday.summarize_overhead({"off": self.runs([20.0, 22.0]), "ratio 1": self.runs([21.0, 21.0])})
        self.assertTrue(any("noise of this measurement" in line for line in lines))


class OrchestrationTests(unittest.TestCase):
    """run_scenario from the start of the load to the verdict, with a made-up failure and the cluster calls stubbed."""

    def setUp(self):
        self.service = FakeService()
        self.ctx = gameday.Context(base=self.service.base)
        self.patches = [
            mock.patch.object(gameday, "backend_restarts", return_value=0),
            mock.patch.object(gameday, "prometheus_alerts", return_value=[]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.service.close()

    def scenario(self, inject, recovered, hypothesis):
        return gameday.Scenario(
            name="made-up", title="A made-up failure", hypothesis=hypothesis, why="test",
            applicable=lambda ctx: (True, ""), inject=inject, recovered=recovered,
            inject_at_s=1, tail_s=1, recovery_limit_s=15,
        )

    def test_a_short_outage_that_ends_is_recovered_and_judged_by_its_numbers(self):
        def inject(ctx):
            now = time.time() - self.service.started
            self.service.outage = (now, now + 1.5)

        def recovered(ctx):
            return self.service.outage is not None and time.time() - self.service.started > self.service.outage[1]

        s = self.scenario(inject, recovered, gameday.Hypothesis(max_outage_s=3, max_lost_writes=0, max_recovery_s=10))
        observed, checks = gameday.run_scenario(self.ctx, s, first_slot=0)
        self.assertIsNotNone(observed.recovery_s)
        self.assertGreater(observed.failed, 5)
        self.assertEqual(observed.lost_writes, 0)
        self.assertTrue(all(ok for _, ok, _ in checks), checks)

    def test_a_write_that_vanishes_during_the_failure_makes_the_scenario_fail(self):
        def inject(ctx):
            self.service.lost_ids = {1, 2}  # the first two acknowledged bookings are gone

        s = self.scenario(inject, lambda ctx: True, gameday.Hypothesis(max_lost_writes=0))
        observed, checks = gameday.run_scenario(self.ctx, s, first_slot=0)
        self.assertEqual(observed.lost_writes, 2)
        self.assertEqual([what for what, ok, _ in checks if not ok], ["acknowledged writes lost"])

    def test_a_system_that_does_not_come_back_in_time_fails_the_recovery_limit(self):
        s = self.scenario(lambda ctx: None, lambda ctx: False, gameday.Hypothesis(max_recovery_s=5))
        s.recovery_limit_s = 3
        observed, checks = gameday.run_scenario(self.ctx, s, first_slot=0)
        self.assertIsNone(observed.recovery_s)
        self.assertIn("time to recover", [what for what, ok, _ in checks if not ok])

    def test_a_failing_injection_is_reported_and_never_a_pass(self):
        def inject(ctx):
            raise RuntimeError("helm upgrade failed")

        s = self.scenario(inject, lambda ctx: True, gameday.Hypothesis(max_lost_writes=0))
        observed, checks = gameday.run_scenario(self.ctx, s, first_slot=0)
        self.assertIn("injection failed", observed.aborted)
        self.assertFalse(all(ok for _, ok, _ in checks))


class ScenarioTests(unittest.TestCase):
    def test_every_scenario_has_a_hypothesis_with_something_to_judge(self):
        for s in gameday.SCENARIOS:
            limits = [v for k, v in s.hypothesis.__dict__.items() if v is not None]
            self.assertTrue(limits, s.name)
            self.assertTrue(s.why, s.name)

    def test_the_scenarios_that_need_a_particular_setup_say_why_they_do_not_apply(self):
        ctx = gameday.Context(has_rollout=False, has_operator=False, nodes=1)
        reasons = {s.name: s.applicable(ctx) for s in gameday.SCENARIOS}
        self.assertFalse(reasons["bad-release"][0])
        self.assertFalse(reasons["database-primary-failover"][0])
        self.assertFalse(reasons["node-drain"][0])
        self.assertTrue(reasons["backend-pod-kill"][0])
        self.assertTrue(reasons["database-pod-restart"][0])
        for name in ("bad-release", "database-primary-failover", "node-drain"):
            self.assertTrue(reasons[name][1], name)

    def test_the_report_names_every_scenario_and_marks_a_failure(self):
        s = gameday.SCENARIOS[0]
        passing = gameday.Observed(reads=100, outage_s=0.5, lost_writes=0, recovery_s=30.0, backend_restarts=0)
        failing = gameday.Observed(reads=100, failed=20, outage_s=9.0, lost_writes=2, recovery_s=30.0, backend_restarts=0)
        rows = [
            {"name": "a", "scenario": s, "skipped": "", "observed": passing, "checks": gameday.evaluate(s.hypothesis, passing)},
            {"name": "b", "scenario": s, "skipped": "", "observed": failing, "checks": gameday.evaluate(s.hypothesis, failing)},
            {"name": "c", "scenario": s, "skipped": "one node", "observed": gameday.Observed(), "checks": []},
        ]
        report = gameday.render_report(rows, gameday.Context())
        self.assertIn("| `a` | PASS |", report)
        self.assertIn("| `b` | **FAIL** |", report)
        self.assertIn("| `c` | skipped |", report)


if __name__ == "__main__":
    unittest.main()
