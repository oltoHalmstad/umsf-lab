"""The LLM layer is tested with a fake client object (no network, no SDK needed)."""

import json
import os
import unittest
from types import SimpleNamespace as NS

from helpers import read_json, read_jsonl, read_text, scenario_dir, tmpdir
from umsf_agent import llm
from umsf_agent.agent import Agent


def tool_use(i, name):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input={})


def text(t):
    return NS(type="text", text=t)


class FakeMessages:
    def __init__(self, script, raise_exc=None):
        self.script = list(script)
        self.calls = []
        self.raise_exc = raise_exc

    def create(self, **kw):
        # snapshot the messages list as it was at call time
        self.calls.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        if self.raise_exc:
            raise self.raise_exc
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script, raise_exc=None):
        self.beta = NS(messages=FakeMessages(script, raise_exc))


class TestLLMLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = tmpdir()
        cls.agent = Agent(scenario_dir(), out)
        cls.res = cls.agent.assess_and_plan(cls.agent.dataset.time_bounds()[1])
        cls.pk = cls.agent.build_packages(cls.res)
        cls.outputs = llm.build_tool_outputs(cls.res, cls.pk)

    def _good_text(self):
        q = self.outputs["get_continuity_proposal"]["Q_pct"]
        return (f"# Оперативна довідка (згенеровано ШІ)\n\nСтатус сервісів: оптимальний, Q = {q} %. "
                "Зона Z3: доступ невідомий, запит SOS від stationary_node залишається відкритим.\n\n"
                "## Рішення, що очікують затвердження\n- координатор рятувальних робіт")

    def test_tool_loop_and_request_shape(self):
        names = [t["name"] for t in llm.TOOLS]
        script = [NS(stop_reason="tool_use", content=[text("Перевіряю."), *[tool_use(i, n) for i, n in enumerate(names)]]),
                  NS(stop_reason="end_turn", content=[text(self._good_text())])]
        client = FakeClient(script)
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy, client=client)
        self.assertEqual(out["source"], "llm", out)
        self.assertIn(llm.AI_LABEL, out["text"])
        self.assertEqual(out["tool_calls"], names)
        calls = client.beta.messages.calls
        self.assertEqual(len(calls), 2)
        c = calls[0]
        self.assertEqual(c["model"], os.environ.get("UMSF_LLM_MODEL", "claude-opus-5-5"))
        self.assertEqual(c["max_tokens"], 16000)
        self.assertEqual(c["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(c["fallbacks"], "default")
        self.assertEqual(c["output_config"], {"effort": "medium"})
        for forbidden in ("thinking", "temperature", "tool_choice"):
            self.assertNotIn(forbidden, c)
        # second call: assistant content appended, then ONE user message with all tool_result blocks
        msgs = calls[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        results = msgs[2]["content"]
        self.assertEqual(len(results), 5)
        self.assertTrue(all(r["type"] == "tool_result" for r in results))
        payload = json.loads(results[1]["content"])
        self.assertIn("assignments", payload)

    def test_tools_are_minimised(self):
        blob = json.dumps(self.outputs, ensure_ascii=False)
        for raw in ("hr_bpm", "skin_temp_c", "motion_rms_g", "spo2"):
            self.assertNotIn(raw, blob)
        for t in llm.TOOLS:
            self.assertEqual(t["input_schema"]["properties"], {})

    def test_model_env_override(self):
        os.environ["UMSF_LLM_MODEL"] = "claude-test-model"
        try:
            client = FakeClient([NS(stop_reason="end_turn", content=[text(self._good_text())])])
            out = llm.generate_briefing(self.res, self.pk, self.agent.policy, client=client)
            self.assertEqual(client.beta.messages.calls[0]["model"], "claude-test-model")
            self.assertEqual(out["model"], "claude-test-model")
        finally:
            del os.environ["UMSF_LLM_MODEL"]

    def test_refusal_falls_back(self):
        client = FakeClient([NS(stop_reason="refusal", content=[])])
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy, client=client)
        self.assertEqual(out["source"], "deterministic_fallback")
        self.assertEqual(out["fallback_reason"], "model refusal")
        self.assertIn("Оперативна довідка", out["text"])

    def test_pause_turn_is_resumed(self):
        script = [NS(stop_reason="pause_turn", content=[text("…")]),
                  NS(stop_reason="end_turn", content=[text(self._good_text())])]
        client = FakeClient(script)
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy, client=client)
        self.assertEqual(out["source"], "llm")
        self.assertEqual([m["role"] for m in client.beta.messages.calls[1]["messages"]], ["user", "assistant"])

    def test_forbidden_claim_rejected(self):
        bad = self._good_text() + "\nРакетний удар підтверджено, є загиблі."
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy,
                                    client=FakeClient([NS(stop_reason="end_turn", content=[text(bad)])]))
        self.assertEqual(out["source"], "deterministic_fallback")
        self.assertTrue(out["post_check"]["forbidden_phrases"])

    def test_unsupported_number_rejected(self):
        bad = self._good_text() + "\nОцінка: 4737 осіб у зоні."
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy,
                                    client=FakeClient([NS(stop_reason="end_turn", content=[text(bad)])]))
        self.assertEqual(out["source"], "deterministic_fallback")
        self.assertIn("4737", out["post_check"]["unsupported_numbers"])

    def test_api_error_falls_back(self):
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy,
                                    client=FakeClient([], raise_exc=ConnectionError("offline")))
        self.assertEqual(out["source"], "deterministic_fallback")
        self.assertIn("ConnectionError", out["fallback_reason"])

    def test_max_tokens_truncation_falls_back(self):
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy,
                                    client=FakeClient([NS(stop_reason="max_tokens", content=[text("# Оперативна")])]))
        self.assertEqual(out["source"], "deterministic_fallback")

    def test_unknown_tool_returns_error_result(self):
        script = [NS(stop_reason="tool_use", content=[tool_use(0, "actuate_valve")]),
                  NS(stop_reason="end_turn", content=[text(self._good_text())])]
        client = FakeClient(script)
        llm.generate_briefing(self.res, self.pk, self.agent.policy, client=client)
        res = client.beta.messages.calls[1]["messages"][2]["content"][0]
        self.assertTrue(res["is_error"])

    def test_no_sdk_offline_fallback(self):
        try:
            import anthropic  # noqa: F401
            self.skipTest("anthropic installed; offline path not exercised")
        except ImportError:
            pass
        out = llm.generate_briefing(self.res, self.pk, self.agent.policy)
        self.assertEqual(out["source"], "deterministic_fallback")
        self.assertIn("not installed", out["fallback_reason"])

    def test_agent_writes_labelled_ai_briefing(self):
        out = tmpdir()
        client = FakeClient([NS(stop_reason="end_turn", content=[text(self._good_text())])])
        Agent(scenario_dir(), out, use_llm=True, llm_client=client).run()
        txt = read_text(os.path.join(out, "ai_briefing.md"))
        self.assertIn("AI-generated summary — verify against deterministic outputs", txt)
        entries = read_jsonl(os.path.join(out, "audit.jsonl"))
        s = [e for e in entries if e["entry_type"] == "llm_summary"][0]["payload"]
        self.assertTrue(s["accepted"])


if __name__ == "__main__":
    unittest.main()
