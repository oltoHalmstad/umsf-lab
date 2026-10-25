import contextlib
import io
import json
import os
import unittest

from helpers import read_json, read_jsonl, read_text, scenario_dir, tmpdir
from umsf_agent.agent import Agent
from umsf_agent.audit import verify_chain
from umsf_agent.cli import main
from umsf_agent.util import parse_ts

TABLE9 = {
    "urgent_personnel_assistance": "rescue_coordinator",
    "rescue_task_assignment": "rescue_coordinator",
    "personnel_accounting": "incident_coordination_team",
    "structural_access_status": "qualified_assessor",
    "essential_service_preservation": "infrastructure_operator",
    "recovery_scheduling": "recovery_management",
}


def _quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


class TestAgentRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tmpdir()
        cls.agent = Agent(scenario_dir(), cls.out)
        cls.res = cls.agent.run()
        with open(os.path.join(cls.out, "decision_packages.json")) as fh:
            cls.pk = json.load(fh)["packages"]

    def test_outputs_written(self):
        for f in ("decision_packages.json", "briefing.md", "report.md", "dashboard.html", "audit.jsonl",
                  "result.json", "incident_packets.json"):
            self.assertTrue(os.path.exists(os.path.join(self.out, f)), f)
        html = read_text(os.path.join(self.out, "dashboard.html"))
        self.assertIn("<svg", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("<script src", html)

    def test_every_package_is_a_proposal_with_table9_role(self):
        doms = {p["domain"]: p for p in self.pk}
        for dom, role in TABLE9.items():
            self.assertIn(role, doms[dom]["authorising_roles"])
            self.assertTrue(doms[dom]["proposal"])
            self.assertEqual(doms[dom]["status"], "awaiting_authorisation")
            self.assertEqual(len(doms[dom]["input_sha256"]), 64)
            self.assertIn("method", doms[dom]["solver"])
        self.assertIn("incident_command", doms["structural_access_status"]["authorising_roles"])

    def test_audit_chain_and_contents(self):
        ok, problems = verify_chain(os.path.join(self.out, "audit.jsonl"))
        self.assertTrue(ok, problems)
        types = [e["entry_type"] for e in read_jsonl(os.path.join(self.out, "audit.jsonl"))]
        self.assertIn("propose", types)
        self.assertEqual(types[0], "session_start")

    def test_briefing_has_no_forbidden_conclusions(self):
        b = read_text(os.path.join(self.out, "briefing.md"))
        self.assertIn("СИНТЕТИЧНІ ДАНІ", b)
        self.assertNotIn("ракетний удар підтверджено", b)
        self.assertNotIn("безпечно для входу", b)

    def test_tamper_detected(self):
        path = os.path.join(tmpdir(), "audit.jsonl")
        with open(os.path.join(self.out, "audit.jsonl")) as src, open(path, "w") as dst:
            lines = src.readlines()
            i = next(k for k, l in enumerate(lines) if "awaiting_authorisation" in l)
            lines[i] = lines[i].replace("awaiting_authorisation", "approved", 1)
            dst.writelines(lines)
        self.assertFalse(verify_chain(path)[0])


class TestAuthorisation(unittest.TestCase):
    def setUp(self):
        self.out = tmpdir()
        self.agent = Agent(scenario_dir(), self.out)
        self.agent.run()
        self.pk = {p["domain"]: p for p in read_json(os.path.join(self.out, "decision_packages.json"))["packages"]}

    def test_cli_approve_and_reject_with_reason(self):
        pid = self.pk["essential_service_preservation"]["package_id"]
        rc, _ = _quiet(main, ["approve", "--out", self.out, "--package", pid, "--role", "infrastructure_operator",
                              "--by", "operator-1", "--reason", "capacity bounds verified"])
        self.assertEqual(rc, 0)
        pid2 = self.pk["recovery_scheduling"]["package_id"]
        rc, _ = _quiet(main, ["reject", "--out", self.out, "--package", pid2, "--role", "recovery_management",
                              "--by", "rm-1", "--reason", "loader is committed elsewhere"])
        self.assertEqual(rc, 0)
        entries = read_jsonl(os.path.join(self.out, "audit.jsonl"))
        auth = [e["payload"] for e in entries if e["entry_type"] == "authorisation"]
        self.assertEqual([(a["decision"], a["reason"]) for a in auth],
                         [("approved", "capacity bounds verified"), ("rejected", "loader is committed elsewhere")])
        self.assertTrue(verify_chain(os.path.join(self.out, "audit.jsonl"))[0])
        doc = read_json(os.path.join(self.out, "decision_packages.json"))
        st = {p["package_id"]: p["status"] for p in doc["packages"]}
        self.assertEqual((st[pid], st[pid2]), ("approved", "rejected"))

    def test_wrong_role_or_missing_reason_refused(self):
        pid = self.pk["rescue_task_assignment"]["package_id"]
        rc, err = _quiet(main, ["approve", "--out", self.out, "--package", pid, "--role", "infrastructure_operator",
                                "--by", "x", "--reason", "ok"])
        self.assertEqual(rc, 3)
        self.assertIn("not an authorising role", err)
        rc, err = _quiet(main, ["approve", "--out", self.out, "--package", pid, "--role", "rescue_coordinator",
                                "--by", "x", "--reason", "  "])
        self.assertEqual(rc, 3)

    def test_interactive_prompt(self):
        answers = iter(["r", "rescue_coordinator", "rc-1", "team RT1 reserved"] + ["d"] * 20)
        out = tmpdir()
        with contextlib.redirect_stdout(io.StringIO()):
            ag = Agent(scenario_dir(), out, interactive=True, input_fn=lambda _p: next(answers))
            ag.run()
        auth = [e["payload"] for e in read_jsonl(os.path.join(out, "audit.jsonl")) if e["entry_type"] == "authorisation"]
        self.assertEqual(len(auth), 1)
        self.assertEqual((auth[0]["decision"], auth[0]["reason"]), ("rejected", "team RT1 reserved"))


class TestSimulationAndReplay(unittest.TestCase):
    def test_auto_approve_is_marked_simulated(self):
        out = tmpdir()
        Agent(scenario_dir(), out, auto_approve=True).run()
        doc = read_json(os.path.join(out, "decision_packages.json"))
        self.assertTrue(doc["auto_approve_for_simulation"])
        for p in doc["packages"]:
            self.assertEqual(p["status"], "approved_simulation")
            self.assertEqual(p["authorisation"]["actor"], "SIMULATION-AUTO-APPROVE")
        self.assertIn("--auto-approve-for-simulation", read_text(os.path.join(out, "briefing.md")))

    def test_change_detection(self):
        out = tmpdir()
        ag = Agent(scenario_dir(), out)
        t = parse_ts("2026-10-14T08:45:00Z")
        ag.step(t)
        ag.step(t)
        self.assertEqual(ag.timeline[1]["changed_domains"], [])
        types = [e["entry_type"] for e in read_jsonl(os.path.join(out, "audit.jsonl"))]
        self.assertIn("no_change", types)

    def test_replay_reproposes_on_new_events(self):
        out = tmpdir()
        ag = Agent(scenario_dir(), out)
        ag.replay(parse_ts("2026-10-14T08:33:00Z"), parse_ts("2026-10-14T08:42:00Z"), 60)
        rows = {r["as_of"]: r for r in ag.timeline}
        self.assertIn("urgent_personnel_assistance", rows["2026-10-14T08:35:00Z"]["changed_domains"])
        self.assertEqual(rows["2026-10-14T08:37:00Z"]["continuity_status"], "INFEASIBLE")   # grid lost
        self.assertEqual(rows["2026-10-14T08:40:00Z"]["continuity_status"], "OPTIMAL")      # generator + fuel verified
        self.assertLess(sum(1 for r in ag.timeline if r["changed_domains"]), len(ag.timeline))
        sup = [e for e in read_jsonl(os.path.join(out, "audit.jsonl")) if e["entry_type"] == "supersede"]
        self.assertTrue(sup)
        self.assertTrue(os.path.exists(os.path.join(out, "timeline.json")))


class TestNoBackupPowerVariant(unittest.TestCase):
    def test_infeasible_never_relaxed(self):
        from umsf_agent.scenario import generate
        d = os.path.join(tmpdir(), "nobackup")
        generate(d, variant="no_backup_power")
        res = Agent(d, tmpdir()).run()
        c = res["continuity"]["result"]
        self.assertEqual(c["status"], "INFEASIBLE")
        self.assertIsNone(c["Q_pct"])
        self.assertTrue(any("power_kw" in r for r in c["infeasibility_reasons"]))
        self.assertEqual(set(c["y"].values()), {0})          # no partial "successful" plan is displayed
        first = res["recovery"]["restoration_order"][0]
        self.assertEqual(first["service_id"], "(capacity) power_kw")


class TestCLI(unittest.TestCase):
    def test_reproduce_paper_exit_zero(self):
        rc, out = _quiet(main, ["reproduce-paper"])
        self.assertEqual(rc, 0)
        self.assertIn("44/44 checks passed", out)

    def test_demo_offline_with_llm_flag(self):
        out = tmpdir()
        rc, txt = _quiet(main, ["demo", "--out", out, "--llm", "--step", "300"])
        self.assertEqual(rc, 0)
        ai = read_text(os.path.join(out, "run", "ai_briefing.md"))
        self.assertIn("детермінована довідка", ai)       # graceful offline fallback
        rc, _ = _quiet(main, ["verify-audit", "--audit", os.path.join(out, "run", "audit.jsonl")])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
