"""state.json stays small: compact records, history only for important decisions, pruning, stable output."""
from __future__ import annotations

import json

from seo_agent import state as state_mod
from seo_agent.state import State

BIG = {"keyword": "what is my skin tone", "volume": 3600, "source": "google_ads_keyword_planner", "feature": "skin-analysis",
       "score": {"feature_relevance": 95}, "score_total": 86.2, "intent": "informational",
       "score_evidence": {"x": ["long text"] * 50}, "opportunity_evidence": ["a"] * 20, "coverage": 0.4, "covering_page": "p"}


def _st(tmp_path, monkeypatch, day="2026-11-05"):
    monkeypatch.setenv("SEO_AGENT_TODAY", day)
    return State(tmp_path / "state.json")


def test_records_are_compact(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch)
    s.record_keyword(BIG["keyword"], BIG, "candidate")
    e = s.data["keywords"][BIG["keyword"]]
    assert set(e["latest"]) <= set(state_mod.LATEST_KEYS) and "score_evidence" not in e["latest"]
    assert e["latest"]["volume"] == 3600 and e["latest"]["score_total"] == 86.2 and e["feature"] == "skin-analysis"


def test_routine_rejections_keep_no_history(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch)
    for _ in range(5):
        s.record_keyword("x outfit", {"keyword": "x outfit", "volume": 20}, "rejected_low_volume")
    assert "history" not in s.data["keywords"]["x outfit"]


def test_important_history_only_on_change_and_capped(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch)
    for _ in range(5):  # same data every day -> one history entry
        s.record_keyword("k", BIG, "candidate")
    assert len(s.data["keywords"]["k"]["history"]) == 1
    for v in range(30):
        s.record_keyword("k", {**BIG, "volume": 100 + v}, "candidate")
    assert len(s.data["keywords"]["k"]["history"]) == state_mod.MAX_HISTORY


def test_published_kept_forever_and_routine_pruned(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch, "2026-01-01")
    s.record_keyword(BIG["keyword"], BIG, "published:what-is-my-skin-tone")
    s.record_keyword("old rejected", {"keyword": "old rejected", "volume": 10}, "rejected_low_volume")
    s.record_keyword("old dup", BIG, "duplicate_intent_of_article:x")
    s.save()
    s2 = _st(tmp_path, monkeypatch, "2026-11-05")  # > 90 days later
    s2.save()
    k = json.loads((tmp_path / "state.json").read_text())["keywords"]
    assert BIG["keyword"] in k and k[BIG["keyword"]]["article"]["slug"] == "what-is-my-skin-tone"
    assert "old dup" in k and "old rejected" not in k


def test_quality_gate_cooldown_still_works(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch, "2026-11-01")
    s.record_keyword("k", BIG, "rejected_by_quality_gate: low_value_score:5")
    s.save()
    assert _st(tmp_path, monkeypatch, "2026-11-20").rejected_recently("k")
    assert not _st(tmp_path, monkeypatch, "2026-12-15").rejected_recently("k")


def test_output_is_valid_one_line_per_keyword_and_stable(tmp_path, monkeypatch):
    s = _st(tmp_path, monkeypatch)
    for i in range(50):
        s.record_keyword(f"kw {i}", {**BIG, "keyword": f"kw {i}"}, "rejected_low_volume" if i % 2 else "candidate")
    s.save()
    text = (tmp_path / "state.json").read_text()
    data = json.loads(text)
    assert len(data["keywords"]) == 50
    assert sum(1 for line in text.splitlines() if line.startswith('    "kw ')) == 50
    s2 = _st(tmp_path, monkeypatch)  # a second run with identical data rewrites nothing
    for i in range(50):
        s2.record_keyword(f"kw {i}", {**BIG, "keyword": f"kw {i}"}, "rejected_low_volume" if i % 2 else "candidate")
    s2.save()
    assert (tmp_path / "state.json").read_text() == text


def test_old_drafts_pruned(tmp_path, monkeypatch):
    from seo_agent.agents import editor_agent

    class Cfg:
        data_dir = tmp_path
    d = tmp_path / "drafts"
    d.mkdir()
    (d / "2026-09-01-old-r0.json").write_text("{}")
    (d / "2026-11-01-new-r0.json").write_text("{}")
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-11-05")
    assert editor_agent.prune_drafts(Cfg()) == 1
    assert [f.name for f in d.iterdir()] == ["2026-11-01-new-r0.json"]
