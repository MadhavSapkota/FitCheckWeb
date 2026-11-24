"""Regressions for missed daily publications: claim filtering, new seeds and retry limits."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import subprocess
from zoneinfo import ZoneInfo

import pytest
import yaml

from seo_agent import content, dataforseo, main, quality, research
from test_agent import site, mock_apis, enable_global, idea  # noqa: F401


@pytest.mark.parametrize('text', [
    'Dermatologist Thomas Fitzpatrick developed the scale in the 1970s.',
    'A dermatologist can help with skin concerns. AI feedback is not medical advice.',
    'See a dermatologist or doctor. The app does not diagnose skin conditions.',
])
def test_professional_attribution_and_referrals_are_allowed(text):
    assert not [label for pattern, label in quality.FORBIDDEN
                if re.search(pattern, quality.claim_text(text), re.I)]


@pytest.mark.parametrize('text', [
    'FitCheck diagnoses skin conditions.',
    'FitCheck is a dermatologist in your pocket.',
    'Meet your AI dermatologist.',
    'Our app is dermatologist-approved.',
    'See a dermatologist, but this app detects melanoma.',
    'Dermatologist Thomas Fitzpatrick developed the scale. FitCheck diagnoses acne.',
])
def test_medical_promises_remain_blocked(text):
    assert any(re.search(pattern, quality.claim_text(text), re.I) for pattern, _ in quality.FORBIDDEN)


def setup_fallback(site, monkeypatch, *, primary_fails=False):
    mock_apis(monkeypatch)
    enable_global(site)
    monkeypatch.setattr(dataforseo, 'keyword_difficulty', lambda cfg, kws: {k: 10 for k in kws})
    calls = []
    cfg = main.load_config()
    extra = {q for f in cfg.get('features').values() for q in f.get('fallback_seeds', [])}
    assert extra

    def discover(cfg, seeds=None):
        fallback = bool(set(seeds or []) & extra)
        calls.append(fallback)
        if fallback:
            return [idea('how to match colors in an outfit', 3000)]
        return [idea('how to organize your closet', 3000)] if primary_fails else []
    monkeypatch.setattr(research, 'discover', discover)
    if primary_fails:
        write = content.write_article
        def write_by_keyword(cfg, kw, *args, **kwargs):
            article = write(cfg, kw, *args, **kwargs)
            if kw['keyword'] == 'how to organize your closet':
                article['body_html'] += '<p>Over 1 million users love this app.</p>'
            return article
        monkeypatch.setattr(content, 'write_article', write_by_keyword)
    return calls


@pytest.mark.parametrize('primary_fails', [False, True])
def test_new_seed_search_publishes_after_empty_or_rejected_primary(site, monkeypatch, primary_fails):
    calls = setup_fallback(site, monkeypatch, primary_fails=primary_fails)
    assert main.main(['run']) == 0
    articles = list((site / 'blog').glob('*/index.html'))
    assert len(articles) == 1
    state = json.loads((site / 'seo-agent/data/state.json').read_text())
    assert state['keywords']['how to match colors in an outfit']['decision'].startswith('published:')
    assert True in calls and False in calls
    before = len(calls)
    assert main.main(['run']) == 0
    assert len(calls) == before  # retry cannot generate a second article on the same Chicago day


@pytest.mark.parametrize('cap', ['writing', 'planning'])
def test_fallback_shares_primary_run_limits(site, monkeypatch, cap):
    calls = setup_fallback(site, monkeypatch, primary_fails=True)
    cfg_path = site / 'seo-agent/seo-config.yaml'
    text = cfg_path.read_text()
    if cap == 'writing':
        text = re.sub(r'max_candidates_per_run: \d+', 'max_candidates_per_run: 1', text)
    else:
        text = re.sub(r'max_planner_calls_per_run: \d+', 'max_planner_calls_per_run: 1', text)
        monkeypatch.setattr(content, 'plan', lambda *args: {'action': 'skip', 'reason': 'covered'})
    cfg_path.write_text(text)
    assert main.main(['run']) == 0
    assert not any(calls)  # no fallback requests after exhausting either cap
    assert not list((site / 'blog').glob('*/index.html'))


@pytest.mark.parametrize('month', [1, 7])
def test_backup_schedule_covers_chicago_evenings_across_dst(month, tmp_path):
    path = Path(__file__).resolve().parents[2] / '.github/workflows/daily-seo.yml'
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    cron = workflow['on']['schedule'][0]['cron'].split()
    hours = [int(x) for x in cron[1].split(',')]
    start = datetime(2026, month, 15, tzinfo=timezone.utc)
    chicago = ZoneInfo('America/Chicago')
    local_hours = {(start + timedelta(hours=h, minutes=int(cron[0]))).astimezone(chicago).hour for h in hours}
    assert {18, 20, 22} <= local_hours
    script = workflow['jobs']['schedule']['steps'][0]['run']
    output = tmp_path / 'output'
    for hour in range(24):
        output.write_text('')
        # Inject the wall-clock hour without depending on the test machine's time.
        subprocess.run(['bash', '-c', 'date() { echo "$TEST_HOUR"; }; ' + script],
                                env={'EVENT_NAME': 'schedule', 'TEST_HOUR': f'{hour:02}', 'GITHUB_OUTPUT': str(output)},
                                text=True, capture_output=True, check=True)
        assert output.read_text().strip() == f"due={'true' if 18 <= hour <= 22 else 'false'}"


def test_historical_attribution_does_not_block_a_complete_article(site, monkeypatch):
    from test_agent import fake_body
    mock_apis(monkeypatch, body=fake_body('color matching') +
              '<p>Dermatologist Thomas Fitzpatrick developed the scale in the 1970s.</p>')
    assert main.main(['run']) == 0
    assert len(list((site / 'blog').glob('*/index.html'))) == 1
