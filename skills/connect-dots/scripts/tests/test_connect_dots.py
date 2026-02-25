import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REFS = SCRIPTS.parent / "references"


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr


class ConnectDotsDeterministicCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "memory").mkdir()
        # Create a fake memory file to satisfy evidence verification.
        (self.root / "memory" / "2026-02-22.md").write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        # Include a line that matches the hypothesis statement for quote-in-range verification.
        (self.root / "memory" / "2026-02-22.md").write_text("JD prefers concise communication.\n" + (self.root / "memory" / "2026-02-22.md").read_text(encoding="utf-8"), encoding="utf-8")

        self.model_path = self.root / "model.json"
        self.proposal_path = self.root / "proposal.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _proposal(self, scope="user-profile/preferences"):
        return {
            "scope": scope,
            "generatedAt": "2026-02-22T00:00:00+01:00",
            "items": {
                "confirmed_facts": [],
                "hypotheses": [],
                "open_loops": [],
                "candidate_moves": [],
            },
        }

    def test_validate_model_schema_rejects_missing_fields(self):
        bad = {"scope": "user-profile/preferences"}
        self.model_path.write_text(json.dumps(bad), encoding="utf-8")
        code, out, err = run(["python3", str(SCRIPTS / "validate_model.py"), "--model", str(self.model_path)])
        self.assertNotEqual(code, 0)

    def test_build_model_creates_skeleton_and_validates_proposal(self):
        prop = self._proposal()
        prop["items"]["hypotheses"].append(
            {
                "id": "h1",
                "statement": "JD prefers concise communication.",
                "evidence": [
                    {"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a", "ts": "2026-02-22T00:00:00+01:00"}
                ],
            }
        )
        self.proposal_path.write_text(json.dumps(prop), encoding="utf-8")
        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "build_model.py"),
                "--scope",
                "user-profile/preferences",
                "--workspace",
                str(self.root),
                "--model",
                str(self.model_path),
                "--proposal",
                str(self.proposal_path),
            ]
        )
        self.assertEqual(code, 0, msg=err)
        model = json.loads(self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(model["scope"], "user-profile/preferences")
        self.assertEqual(len(model["hypotheses"]), 1)
        self.assertIn("expires_at", model["hypotheses"][0])

    def test_do_not_store_drops_matching_statement(self):
        # Seed model with do_not_store.
        skeleton = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [{"pattern": "secret", "created_at": "now"}],
        }
        self.model_path.write_text(json.dumps(skeleton), encoding="utf-8")

        prop = self._proposal()
        prop["items"]["hypotheses"].append(
            {
                "id": "h1",
                "statement": "This contains SECRET content.",
                "evidence": [
                    {"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a", "ts": "2026-02-22T00:00:00+01:00"}
                ],
            }
        )
        self.proposal_path.write_text(json.dumps(prop), encoding="utf-8")

        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "build_model.py"),
                "--scope",
                "user-profile/preferences",
                "--workspace",
                str(self.root),
                "--model",
                str(self.model_path),
                "--proposal",
                str(self.proposal_path),
            ]
        )
        self.assertEqual(code, 0, msg=err)
        model = json.loads(self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(len(model["hypotheses"]), 0)

    def test_consent_dont_store_adds_rule(self):
        # Create a minimal valid model.
        model = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        self.model_path.write_text(json.dumps(model), encoding="utf-8")
        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "consent_mutations.py"),
                "--model",
                str(self.model_path),
                "--op",
                "dont-store",
                "--pattern",
                "foo",
            ]
        )
        self.assertEqual(code, 0, msg=err)
        m2 = json.loads(self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(m2["do_not_store"][0]["pattern"], "foo")

    def test_consent_forget_retracts_by_id(self):
        model = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [
                {
                    "id": "h1",
                    "statement": "A hypothesis",
                    "confidence": 0.9,
                    "first_seen": "t",
                    "last_seen": "t",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "status": "active",
                    "evidence": [{"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a"}],
                }
            ],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        self.model_path.write_text(json.dumps(model), encoding="utf-8")
        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "consent_mutations.py"),
                "--model",
                str(self.model_path),
                "--op",
                "forget",
                "--id",
                "h1",
            ]
        )
        self.assertEqual(code, 0, msg=err)
        m2 = json.loads(self.model_path.read_text(encoding="utf-8"))
        # hypotheses list drops retracted
        self.assertEqual(len(m2["hypotheses"]), 0)

    def test_confirm_promotes_hypothesis_to_fact(self):
        model = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [
                {
                    "id": "h1",
                    "statement": "JD prefers concise communication.",
                    "confidence": 0.8,
                    "first_seen": "t",
                    "last_seen": "t",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "status": "active",
                    "evidence": [{"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a"}],
                }
            ],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        self.model_path.write_text(json.dumps(model), encoding="utf-8")
        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "consent_mutations.py"),
                "--model",
                str(self.model_path),
                "--op",
                "confirm",
                "--id",
                "h1",
                "--fact",
                "Communication style",
                "--value",
                "concise",
            ]
        )
        self.assertEqual(code, 0, msg=err)
        m2 = json.loads(self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(len(m2["hypotheses"]), 0)
        self.assertEqual(len(m2["confirmed_facts"]), 1)
        self.assertEqual(m2["confirmed_facts"][0]["value"], "concise")

    def test_expired_item_moves_to_stale_when_not_refreshed(self):
        # Seed an expired hypothesis.
        model = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [
                {
                    "id": "h-exp",
                    "statement": "Old hypothesis",
                    "confidence": 0.9,
                    "first_seen": "2026-01-01T00:00:00+00:00",
                    "last_seen": "2026-01-01T00:00:00+00:00",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                    "status": "active",
                    "evidence": [{"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a"}],
                }
            ],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        self.model_path.write_text(json.dumps(model), encoding="utf-8")
        # Proposal does not mention h-exp (not refreshed)
        prop = self._proposal()
        self.proposal_path.write_text(json.dumps(prop), encoding="utf-8")

        code, out, err = run(
            [
                "python3",
                str(SCRIPTS / "build_model.py"),
                "--scope",
                "user-profile/preferences",
                "--workspace",
                str(self.root),
                "--model",
                str(self.model_path),
                "--proposal",
                str(self.proposal_path),
            ]
        )
        self.assertEqual(code, 0, msg=err)
        m2 = json.loads(self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(len(m2["hypotheses"]), 0)
        self.assertTrue(any(it.get("id") == "h-exp" for it in m2["stale_items"]))

    def test_model_diff_outputs_diff_lines(self):
        prev = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [
                {
                    "id": "h1",
                    "statement": "Old",
                    "confidence": 0.5,
                    "first_seen": "t",
                    "last_seen": "t",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "status": "active",
                    "evidence": [{"path": "memory/2026-02-22.md", "lines": "L1-L2", "quote": "a"}],
                }
            ],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        cur = json.loads(json.dumps(prev))
        cur["hypotheses"][0]["statement"] = "New"

        p1 = self.root / "prev.json"
        p2 = self.root / "cur.json"
        p1.write_text(json.dumps(prev), encoding="utf-8")
        p2.write_text(json.dumps(cur), encoding="utf-8")

        code, out, err = run(["python3", str(SCRIPTS / "model_diff.py"), "--prev", str(p1), "--cur", str(p2)])
        self.assertEqual(code, 0)
        self.assertIn("~", out)

    def test_render_assumptions_is_single_message(self):
        model = {
            "scope": "user-profile/preferences",
            "updatedAt": "now",
            "meta": {},
            "confirmed_facts": [],
            "hypotheses": [],
            "stale_items": [],
            "open_loops": [],
            "candidate_moves": [],
            "do_not_store": [],
        }
        self.model_path.write_text(json.dumps(model), encoding="utf-8")
        code, out, err = run(["python3", str(SCRIPTS / "render_assumptions.py"), "--model", str(self.model_path)])
        self.assertEqual(code, 0)
        self.assertIn("Assumptions snapshot", out)
        # sanity: output is one block
        self.assertLess(out.count("\n\n\n"), 2)

    def test_nightly_run_patches_runtime_routing_fact_with_workspace_snapshot(self):
        # Build a minimal workspace layout.
        ws = self.root
        (ws / "tmp" / "connect-dots" / "runs").mkdir(parents=True, exist_ok=True)

        run_id = "t-0001"
        scope_dir = ws / "tmp" / "connect-dots" / "runs" / run_id / "openclaw-runtime" / "ops"
        scope_dir.mkdir(parents=True, exist_ok=True)

        # Provide a fake OpenClaw config outside the workspace and point the script to it.
        cfg = {
            "agents": {
                "defaults": {
                    "model": {
                        "primary": "openai-codex/gpt-5.2",
                        "fallbacks": [
                            "openrouter/openai/gpt-5.2",
                            "openai-codex/gpt-5.1-codex-mini",
                        ],
                    },
                    "heartbeat": {"model": "openrouter/google/gemini-2.0-flash-lite-001"},
                }
            }
        }
        cfg_path = ws / "fake-openclaw.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        # Proposal includes a stale routing fact; nightly_run should rewrite it to cite runtime-routing.txt
        # and filter out OpenRouter OpenAI/Anthropic fallbacks.
        proposal = {
            "scope": "openclaw-runtime/ops",
            "generatedAt": "2026-02-22T00:00:00+01:00",
            "items": {
                "confirmed_facts": [
                    {
                        "id": "ops-routing-routine-check",
                        "fact": "model.routing_routine_check",
                        "value": "stale",
                        "domain": "openclaw",
                        "ttl_days": 120,
                        "evidence": [
                            {
                                "path": "memory/does-not-matter.md",
                                "lines": "L1-L1",
                                "quote": "stale",
                                "ts": "2026-02-22T00:00:00+01:00",
                            }
                        ],
                    }
                ],
                "hypotheses": [],
                "open_loops": [],
                "candidate_moves": [],
            },
        }
        (scope_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")

        old = os.environ.get("OPENCLAW_CONFIG_PATH")
        os.environ["OPENCLAW_CONFIG_PATH"] = str(cfg_path)
        try:
            code, out, err = run(
                [
                    "python3",
                    str(SCRIPTS / "nightly_run.py"),
                    "--workspace",
                    str(ws),
                    "--phase",
                    "1",
                    "--scopes",
                    "openclaw-runtime/ops",
                    "--run-id",
                    run_id,
                ],
                cwd=str(ws),
            )
        finally:
            if old is None:
                os.environ.pop("OPENCLAW_CONFIG_PATH", None)
            else:
                os.environ["OPENCLAW_CONFIG_PATH"] = old

        self.assertEqual(code, 0, msg=err)

        snap = scope_dir / "runtime-routing.txt"
        self.assertTrue(snap.exists())

        patched = json.loads((scope_dir / "proposal.json").read_text(encoding="utf-8"))
        facts = patched["items"]["confirmed_facts"]
        self.assertEqual(len(facts), 1)
        v = facts[0]["value"]
        self.assertIn("primary=openai-codex/gpt-5.2", v)
        self.assertIn("openai-codex/gpt-5.1-codex-mini", v)
        self.assertNotIn("openrouter/openai", v)

        # Evidence must point to the workspace snapshot file.
        ev = facts[0]["evidence"][0]
        self.assertTrue(ev["path"].startswith("tmp/connect-dots/runs/"))
        self.assertIn("runtime-routing.txt", ev["path"])


if __name__ == "__main__":
    unittest.main()
