"""Publishing reliability: safe staging, rebase/push retries, recovery without regeneration, API limits, retry gate.
Uses real local git repositories; no network, no credentials."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from seo_agent import content, git_publish, main, publish_monitor as pm, recovery
from test_agent import REPO, mock_apis, site  # noqa: F401

SLUG = "how-to-match-colors-in-an-outfit"
CT = ZoneInfo("America/Chicago")


def sh(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def identity(repo):
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "t")


@pytest.fixture()
def repo(site, tmp_path, monkeypatch):
    shutil.copy(REPO / ".gitignore", site / ".gitignore")
    (site / "llms.txt").write_text("# FitCheck AI\n\n## Policies\n- [Privacy](https://fitcheck-fashion.com/privacy.html)\n")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(origin)], check=True)
    sh(site, "init", "-q", "-b", "master")
    identity(site)
    sh(site, "add", "-A")
    sh(site, "commit", "-q", "-m", "base")
    sh(site, "remote", "add", "origin", str(origin))
    sh(site, "push", "-q", "origin", "master")
    monkeypatch.setenv("SEO_PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.delenv("SEO_RECOVER_DIR", raising=False)
    mock_apis(monkeypatch)
    return site


def clone(repo, tmp_path, name):
    d = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(d)], check=True)
    identity(d)
    return d


def publish(repo):
    return git_publish.publish(main.load_config(), "master", sleep=lambda s: None)


def remote_file(repo, path):
    sh(repo, "fetch", "-q", "origin")
    return sh(repo, "show", f"origin/master:{path}")


def no_api(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a paid API was called during recovery")
    for name in ("plan", "write_article", "revise", "review"):
        monkeypatch.setattr(content, name, boom)
    monkeypatch.setattr(main.keyword_agent, "run", boom)
    monkeypatch.setattr(main.keyword_agent, "run_global", boom)


def test_every_generated_file_is_committed_including_llms_txt(repo):
    assert main.main(["run"]) == 0
    assert publish(repo)
    assert sh(repo, "status", "--porcelain") == ""
    assert sh(repo, "stash", "list") == ""  # nothing generated was treated as unexpected
    for path in ("llms.txt", "sitemap.xml", "blog/index.html"):
        assert SLUG in remote_file(repo, path)


def test_unexpected_files_are_never_committed(repo):
    assert main.main(["run"]) == 0
    (repo / ".env").write_text("KEY=1")
    (repo / "notes.txt").write_text("scratch")
    (repo / "blog" / "blog.css").write_text("changed design")
    assert publish(repo)
    tracked = sh(repo, "ls-tree", "-r", "--name-only", "origin/master")
    assert "notes.txt" not in tracked and ".env" not in tracked
    assert remote_file(repo, "blog/blog.css") != "changed design"
    assert sh(repo, "status", "--porcelain") == ""


def test_secret_in_generated_file_blocks_the_commit(repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value-123456")
    assert main.main(["run"]) == 0
    (repo / "seo-agent" / "data" / "logs" / "x.log").write_text("oops secret-value-123456")
    with pytest.raises(git_publish.PublishError, match="secret"):
        publish(repo)
    assert "state.json" not in sh(repo, "ls-tree", "-r", "--name-only", "origin/master")


def push_other(repo, tmp_path, edits):
    other = clone(repo, tmp_path, "other")
    for path, text in edits.items():
        (other / path).parent.mkdir(parents=True, exist_ok=True)
        (other / path).write_text(text)
    sh(other, "add", "-A")
    sh(other, "commit", "-q", "-m", "concurrent change")
    sh(other, "push", "-q", "origin", "master")


def test_concurrent_commit_is_rebased(repo, tmp_path):
    assert main.main(["run"]) == 0
    push_other(repo, tmp_path, {"new-page.txt": "hi"})
    assert publish(repo)
    assert remote_file(repo, "new-page.txt") == "hi" and SLUG in remote_file(repo, "llms.txt")


def test_conflicting_commit_is_rebuilt_without_api_calls(repo, tmp_path, monkeypatch):
    assert main.main(["run"]) == 0
    push_other(repo, tmp_path, {"llms.txt": "# FitCheck AI (edited)\n\n## Policies\n- x\n",
                                "sitemap.xml": "<?xml version=\"1.0\"?><urlset/>\n"})
    no_api(monkeypatch)
    assert publish(repo)
    llms = remote_file(repo, "llms.txt")
    assert "(edited)" in llms and llms.count(f"/blog/{SLUG}/") == 1
    assert SLUG in remote_file(repo, "sitemap.xml") and SLUG in remote_file(repo, "blog/index.html")


def test_second_article_for_the_day_is_never_pushed(repo, tmp_path):
    assert main.main(["run"]) == 0
    state = {"version": 1, "keywords": {}, "runs": [], "page_updates": [],
             "articles": {"other-guide": {"slug": "other-guide", "published": "2026-11-01", "modified": "2026-11-01"}}}
    push_other(repo, tmp_path, {"seo-agent/data/state.json": json.dumps(state)})
    publish(repo)
    remote = json.loads(remote_file(repo, "seo-agent/data/state.json"))
    assert list(remote["articles"]) == ["other-guide"]
    assert remote["runs"][-1]["decision"] == "skip: daily article limit already reached today"
    assert f"blog/{SLUG}/index.html" not in sh(repo, "ls-tree", "-r", "--name-only", "origin/master")


def test_temporary_push_failure_is_retried(repo, monkeypatch):
    assert main.main(["run"]) == 0
    real, failures = git_publish.git, [2]

    def flaky(root, *args, **kw):
        if args[0] == "push" and failures[0]:
            failures[0] -= 1
            return subprocess.CompletedProcess(args, 128, "", "Could not resolve host")
        return real(root, *args, **kw)
    monkeypatch.setattr(git_publish, "git", flaky)
    assert publish(repo)
    assert SLUG in remote_file(repo, "llms.txt")


def test_failed_publish_is_recovered_by_the_next_run_without_api_calls(repo, tmp_path, monkeypatch):
    assert main.main(["run"]) == 0  # article generated, then the runner dies before pushing
    assert list((tmp_path / "pending").glob("*.json"))
    fresh = clone(repo, tmp_path, "retry")
    from seo_agent import config as config_mod
    loader = config_mod.load_config
    monkeypatch.setattr(main, "load_config", lambda *a, **k: loader(root=fresh))
    monkeypatch.setenv("SEO_RECOVER_DIR", str(tmp_path / "pending"))
    monkeypatch.setenv("SEO_PENDING_DIR", str(tmp_path / "pending2"))
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-11-02")
    no_api(monkeypatch)
    assert main.main(["run"]) == 0
    state = json.loads((fresh / "seo-agent/data/state.json").read_text())
    assert state["articles"][SLUG]["published"] == "2026-11-02"
    assert state["runs"][-1]["decision"].startswith(f"published /blog/{SLUG}/ for '")
    assert git_publish.publish(main.load_config(), "master", sleep=lambda s: None)
    assert main.main(["run"]) in (0, 2)  # same day again: nothing new
    assert len(list((fresh / "blog").glob("*/index.html"))) == 1


def test_published_or_stale_bundles_are_not_republished(repo, tmp_path, monkeypatch):
    assert main.main(["run"]) == 0
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-11-20")
    assert recovery.load_pending() == []


class UsageLimit(Exception):
    status_code = 400
    body = {"error": {"message": "You have reached your specified API usage limits. You will regain access on 2026-12-01."}}


def test_usage_limit_is_reported_exactly_and_not_retried(site, monkeypatch, capsys):
    mock_apis(monkeypatch)
    calls = []

    class Client:
        class messages:
            @staticmethod
            def create(**k):
                calls.append(1)
                raise UsageLimit()
    monkeypatch.setattr(content, "_client", lambda: Client)
    monkeypatch.setattr(content, "plan", lambda cfg, *a: content._json_call("m", "s", "u"))
    assert main.main(["run"]) == 3
    assert len(calls) == 1
    run = json.loads((site / "seo-agent/data/state.json").read_text())["runs"][-1]
    assert run["decision"].startswith("blocked:") and "regain access on 2026-12-01" in run["decision"]
    assert "::error::" in capsys.readouterr().out
    assert pm.classify(run["decision"], job_ok=False) == "blocked_api"


def test_ordinary_bad_request_is_not_called_a_usage_limit():
    class Bad(Exception):
        status_code = 400
        body = {"error": {"message": "max_tokens is too large"}}
    assert content.blocked_reason(Bad()) is None


def at(h, m=0):
    return datetime(2026, 11, 19, h, m, tzinfo=CT)


def row(outcome, run_id="1", decision=""):
    return {"date": "2026-11-19", "outcome": outcome, "run_id": run_id, "decision": decision, "recorded_at": "x"}


def r(h, run_id, conclusion="success"):
    return {"created": at(h), "status": "completed", "conclusion": conclusion, "id": run_id}


def gate(history, runs, now, event="schedule", state=None):
    return pm.gate(state or {}, history, event=event, now=now, runs=lambda: runs)[0]


def test_gate_blocks_any_run_after_publication():
    state = {"articles": {"a": {"published": "2026-11-19"}}}
    for event in ("schedule", "workflow_dispatch"):
        assert not gate([], [], at(20, 17), event, state)
        assert not gate([row("published")], [], at(22, 17), event)


def test_gate_backup_cron_only_runs_in_retry_windows():
    failed = [row("failed")]
    one = [r(18, 1, "failure")]
    assert not gate(failed, one, at(19, 17))
    assert gate(failed, one, at(20, 17))
    assert not gate(failed, one + [r(20, 2, "failure")], at(21, 17))
    assert gate(failed, one + [r(20, 2, "failure")], at(22, 17))
    assert not gate(failed, one + [r(20, 2, "failure"), r(22, 3, "failure")], at(22, 40))
    assert gate([], [], at(19, 17))  # primary scheduler never fired


def test_skipped_runs_do_not_use_up_retries():
    runs = [r(18, 1, "failure"), r(19, 2)]  # run 2: skipped by the gate, so no history row
    assert [x["id"] for x in pm.real_attempts(runs, [row("failed")])] == [1]
    assert pm.decide(at(20).date(), at(20, 5), [row("failed")], pm.real_attempts(runs, [row("failed")]))["action"] == "dispatch"


def test_early_attention_alert_keeps_the_retries():
    blocked = [row("blocked_api", decision="blocked: Anthropic API usage limit")]
    early = pm.decide(at(19).date(), at(19), blocked, [r(18, 1, "failure")])
    assert early["action"] == "alert" and early["final"] is False
    assert pm.decide(at(20).date(), at(20, 5), blocked, [r(18, 1, "failure")])["action"] == "dispatch"


def test_workflow_sets_recovery_folders_only_after_tests():
    import yaml
    wf = yaml.safe_load((REPO / ".github/workflows/daily-seo.yml").read_text())
    names = [s.get("name") for s in wf["jobs"]["seo"]["steps"]]
    order = ["Unit tests (offline, mocked APIs)", "Set recovery folders", "Recover unpublished articles", "Run SEO agent",
             "Save finished article for recovery", "Commit and push changes", "Record publishing history"]
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)
    before = wf["jobs"]["seo"]["steps"][:names.index("Set recovery folders")]
    assert not any("SEO_PENDING_DIR" in str(s) or "SEO_RECOVER_DIR" in str(s) for s in before)
