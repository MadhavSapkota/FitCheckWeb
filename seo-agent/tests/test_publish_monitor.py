"""Watchdog decisions, history records and DST handling. Offline; no GitHub calls."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from seo_agent import publish_monitor as pm

CT = ZoneInfo("America/Chicago")
DAY = date(2026, 11, 19)


def at(h, m=0, day=DAY):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=CT)


def run(h, m=0, conclusion="success", status="completed"):
    return {"created": at(h, m), "status": status, "conclusion": conclusion}


def row(outcome, decision="", day=DAY):
    return {"date": str(day), "outcome": outcome, "decision": decision, "recorded_at": "x", "run_id": "1"}


def test_published_day_is_ok():
    assert pm.decide(DAY, at(23), [row("published")], [run(18)])["action"] == "ok"


def test_before_grace_does_nothing():
    assert pm.decide(DAY, at(18, 10), [], [])["action"] == "none"


def test_missed_primary_dispatches_once_after_grace():
    assert pm.decide(DAY, at(18, 31), [], [])["action"] == "dispatch"


def test_running_run_waits():
    assert pm.decide(DAY, at(18, 40), [], [run(18, 0, None, "in_progress")])["action"] == "wait"


def test_no_candidate_waits_then_retries_then_alerts():
    skip = [row("skipped_no_candidate", "skip: no candidate passed planning + quality gate today")]
    assert pm.decide(DAY, at(19), skip, [run(18)])["action"] == "none"            # no alert at 6 PM: a retry is planned
    d = pm.decide(DAY, at(20, 5), skip, [run(18)])
    assert d["action"] == "dispatch" and d["attempt"] == 2
    assert pm.decide(DAY, at(21), skip, [run(18), run(20)])["action"] == "none"
    assert pm.decide(DAY, at(22, 5), skip, [run(18), run(20)])["action"] == "dispatch"
    final = pm.decide(DAY, at(22, 40), skip, [run(18), run(20), run(22)])
    assert final["action"] == "alert" and "no article published" in final["reason"]


def test_failed_run_is_retried_without_history_row():
    d = pm.decide(DAY, at(20, 1), [], [run(18, conclusion="failure")])
    assert d["action"] == "dispatch"


def test_owner_attention_alerts_immediately():
    skip = [row("skipped_other", "skip: Google Ads Keyword Planner unavailable (GoogleAdsException)")]
    assert pm.decide(DAY, at(19), skip, [run(18)])["action"] == "alert"


def test_yesterday_missed_alerts_never_dispatches():
    y = date(2026, 11, 18)
    assert pm.decide(y, at(1, day=DAY), [], [])["action"] == "alert"


def test_limit_message_without_article_is_an_anomaly_alert():
    d = pm.decide(DAY, at(19), [row("skipped_limit", "skip: daily article limit already reached today")], [run(18)])
    assert d["action"] == "alert"


def test_dst_chicago_6pm_maps_to_both_utc_offsets():
    # 18:00 Chicago is 00:00 UTC in winter (CST) and 23:00 UTC in summer (CDT): the logic uses Chicago wall time, not UTC.
    win = datetime(2026, 11, 20, 0, 31, tzinfo=ZoneInfo("UTC"))
    summer = datetime(2026, 7, 15, 23, 31, tzinfo=ZoneInfo("UTC"))
    assert pm.chicago(win).hour == 18 and pm.chicago(summer).hour == 18
    assert pm.decide(date(2026, 7, 15), summer, [], [])["action"] == "dispatch"


def test_classify_and_record_published():
    state = {"runs": [{"decision": "published /blog/foo-bar/ for 'foo bar' (feature x, score 80) after 1 revision(s)"}],
             "articles": {"foo-bar": {"title": "Foo Bar Guide", "keyword": "foo bar"}}}
    r = pm.build_record(state, day="2026-11-19", run_id="9", run_url="u", job_ok=True, verify_outcome="success", commit_sha="abc1234")
    assert (r["outcome"], r["keyword"], r["title"], r["deploy"]) == ("published", "foo bar", "Foo Bar Guide", "live")
    assert r["url"].endswith("/blog/foo-bar/") and r["commit"] == "abc1234"
    bad = pm.build_record(state, day="2026-11-19", run_id="9", run_url="u", job_ok=True, verify_outcome="failure", commit_sha="a")
    assert bad["deploy"] == "NOT_LIVE"


def test_record_is_idempotent_per_run():
    h = pm.add_record([], {"date": "d", "recorded_at": "1", "run_id": "5", "outcome": "failed"})
    h = pm.add_record(h, {"date": "d", "recorded_at": "2", "run_id": "5", "outcome": "published"})
    assert len(h) == 1 and h[0]["outcome"] == "published"


def test_failed_job_is_classified_failed():
    assert pm.classify("published /blog/x/", job_ok=False) == "failed"


def test_alert_closes_only_when_published_on_or_after_its_day():
    t = "[publish-alert] 2026-11-19: no blog article published"
    assert not pm.resolvable(t, {"2026-11-18"})          # an earlier day's article must not close today's alert
    assert pm.resolvable(t, {"2026-11-19"}) and pm.resolvable(t, {"2026-11-20"})
    assert not pm.resolvable("some other issue", {"2026-11-20"})


def test_no_smtp_code_remains():
    import inspect
    src = inspect.getsource(pm)
    assert "smtplib" not in src and "SMTP" not in src


def test_loop_runs_until_day_is_final_and_stops_outside_window(monkeypatch):
    import argparse
    calls = []
    monkeypatch.setattr(pm.time_mod, "sleep", lambda s: calls.append(s))
    seq = iter([(False, 0), (False, 0), (True, 0)])
    monkeypatch.setattr(pm, "evaluate_once", lambda a, repo, now: next(seq))
    t = datetime(2026, 11, 19, 19, 0, tzinfo=CT)
    monkeypatch.setattr(pm, "datetime", type("D", (datetime,), {"now": classmethod(lambda c, tz=None: t.astimezone(tz) if tz else t)}))
    a = argparse.Namespace(now=None, loop=True, poll_seconds=180)
    assert pm.cmd_watchdog(a) == 0 and calls == [180, 180]        # polled twice, stopped once final


def test_loop_exits_immediately_in_the_morning(monkeypatch):
    import argparse
    monkeypatch.setattr(pm.time_mod, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("must not sleep")))
    monkeypatch.setattr(pm, "evaluate_once", lambda a, repo, now: (False, 0))
    t = datetime(2026, 11, 19, 9, 0, tzinfo=CT)
    monkeypatch.setattr(pm, "datetime", type("D", (datetime,), {"now": classmethod(lambda c, tz=None: t.astimezone(tz) if tz else t)}))
    assert pm.cmd_watchdog(argparse.Namespace(now=None, loop=True, poll_seconds=180)) == 0


def test_loop_stops_after_cutoff(monkeypatch):
    import argparse
    monkeypatch.setattr(pm.time_mod, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("must not sleep")))
    monkeypatch.setattr(pm, "evaluate_once", lambda a, repo, now: (False, 1))
    t = datetime(2026, 11, 19, 22, 55, tzinfo=CT)
    monkeypatch.setattr(pm, "datetime", type("D", (datetime,), {"now": classmethod(lambda c, tz=None: t.astimezone(tz) if tz else t)}))
    assert pm.cmd_watchdog(argparse.Namespace(now=None, loop=True, poll_seconds=180)) == 1
