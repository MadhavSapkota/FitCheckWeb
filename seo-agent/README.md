# Style AI SEO agent

Low-cost, daily, automated content marketing for fitcheck-fashion.com. It finds long-tail Google searches related to the
app, publishes at most one genuinely useful guide per day, and sends readers to the Google Play listing.

## Where things live
| Path | What |
|---|---|
| `seo-agent/seo_agent/agents/` | The six agents (plain Python modules, one Claude account) |
| `seo-agent/seo-config.yaml` | All settings: domain, thresholds, limits, analytics |
| `seo-agent/seo_agent/app_facts.yaml` | The only app facts articles may state + claims they must never make |
| `seo-agent/templates/` | Article and blog index templates |
| `seo-agent/data/` | State/history, article sources, daily reports, logs, Search Console snapshots |
| `blog/` | Published guides (`/blog/<slug>/`), blog index, `blog.css` matching the site design |
| `.github/workflows/daily-seo.yml` | Daily run; deploys through the existing `jekyll-gh-pages.yml` |

The hand-built pages (`index.html`, `how-it-works.html`, `privacy.html`, `terms.html`) are never redesigned. The agent
only adds a missing canonical / `og:url` tag to their `<head>` and fixes `sitemap.xml` / `robots.txt`.
`_config.yml` keeps `seo-agent/` out of the published website.

## The agents
- **Keyword Research** (`keyword_agent.py`): ideas from Google Ads Keyword Planner (verified volume) and Search Console
  queries the site already appears for. Rejects irrelevant, duplicate, already-covered, and low-evidence topics.
- **SEO Strategy** (`strategy_agent.py`): search intent; decides new page / improve existing / skip.
- **Content Writer** (`writer_agent.py`): writes the guide; a separate Claude review checks facts, app claims, and spam policy.
- **Website Editor** (`editor_agent.py`): pages, metadata, JSON-LD, internal "related guides" links, blog index, sitemap.
- **Conversion Optimization** (`conversion_agent.py`): topic-matched CTA ("Check Your Outfit With AI",
  "Get AI Makeup Feedback", "Explore Hairstyles With AI"), one inline CTA after the 2nd section, one at the end.
- **Analytics** (`analytics_agent.py`): Search Console 7/28-day performance, GA4 `cta_click` events (optional),
  improvement suggestions. CTA clicks are Play Store link clicks, **not installs**. Installs are only in Play Console.

## How keywords are chosen (no invented metrics)
- Verified volume (Keyword Planner) must be >= 100/month.
- Search Console queries with no verified volume need >= 30 impressions in 28 days, and are labeled "volume unverified".
- **Opportunity estimate (0-100)** is a labeled heuristic, NOT keyword difficulty, built from: long-tail length, question
  format, verified volume band, relevance, and Search Console ranking evidence. Minimum: 50.
- Ads "competition" is never used as organic difficulty. Google Trends is not used because there is no official API.
- Optional paid upgrade: `organic_difficulty_source: dataforseo` adds measured difficulty (KD <= 25) and live top-10 SERPs.
- Nothing qualifies → nothing is published that day.

## Quality gate (any failure blocks publishing; reason saved in `data/state.json`)
Thresholds, intent, 900+ words, one H1, 3+ H2s, title/meta length, canonical + og:url, keyword density <= 2.5%,
term overuse, repeated sentences, near-duplicate check against every page, valid internal links, end CTA present,
regex block-list for invented features/statistics/testing, and the Claude review must pass (value >= 7, no issues).
Existing guides are improved at most once per 28 days, and only with substantive new content (no date-only edits).

## Costs and limits
| Service | Cost |
|---|---|
| Claude API (Sonnet) | about 3 calls per candidate, max 12 per run. Roughly $0.10-0.30/day |
| Google Ads API / Keyword Planner | free (needs a Google Ads account + developer token) |
| Search Console API, GA4 Data API | free |
| GitHub Actions | free for public repos; a few minutes/day for private ones |

`limits.max_monthly_usd` (default $10) stops generation once the month's estimated spend reaches it. Token prices in
the config are estimates, so **verify them at anthropic.com/pricing** and also set a hard limit in the Anthropic Console.

---

## Setup: API keys
Add each one in **GitHub → repository → Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Required? | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | console.anthropic.com → API Keys (add credit, set a spend limit) |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Recommended | ads.google.com → Tools → API Center (apply; Explorer/Basic access) |
| `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET` | with Ads | Google Cloud Console → APIs & Services → Credentials → OAuth client (Desktop). Enable "Google Ads API" |
| `GOOGLE_ADS_REFRESH_TOKEN` | with Ads | run Google's `generate_user_credentials.py` example from the google-ads-python repo once, locally |
| `GOOGLE_ADS_CUSTOMER_ID` | with Ads | 10-digit account ID at the top of Google Ads (digits only) |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | only with a manager (MCC) account | manager account ID |
| `GSC_SERVICE_ACCOUNT_JSON` | Recommended | Google Cloud → IAM → Service Accounts → create → Keys → JSON. Paste the whole file. Enable "Google Search Console API". Then in Search Console → Settings → Users and permissions, add the service account email (Restricted). |

You need at least one keyword source: Google Ads **or** Search Console. With both, you get the best results.
Accounts with no ad spend may get bucketed volumes from Keyword Planner. The agent uses what the API returns.

**Optional CTA click tracking:** create a GA4 property, put the measurement ID (`G-...`) and numeric property ID into
`seo-config.yaml` → `analytics`, enable "Google Analytics Data API" in Google Cloud, and add the service account email as a
Viewer in GA4. **Update `privacy.html` to disclose Google Analytics before enabling.** Tracking runs on `/blog/` pages only.

**Repository settings:** Settings → Actions → General → Workflow permissions → "Read and write permissions".
If `master` is branch-protected, allow GitHub Actions to push.

## Testing the first run
1. Push the code, then add the secrets.
2. GitHub → Actions → **Daily SEO agent** → Run workflow → tick **Dry run** → Run.
   It runs tests and prints the full report in the "Run SEO agent" log. No files are changed.
3. Read the report. It shows keyword candidates with their evidence, the plan decision, and any quality-gate failures.
4. Run again without dry run. Check the **seo-report** artifact, the new commit on `master`, and that
   "Deploy Jekyll with GitHub Pages" started and succeeded. Open `https://fitcheck-fashion.com/blog/`.
5. From then on it runs daily at 06:17 UTC. Submit `https://fitcheck-fashion.com/sitemap.xml` once in Search Console.
   This helps discovery but does not guarantee indexing.

## Local commands
```bash
python3 -m venv .venv-seo && .venv-seo/bin/pip install -r seo-agent/requirements.txt
cd seo-agent
../.venv-seo/bin/python -m pytest -q tests              # offline tests, all APIs mocked
../.venv-seo/bin/python -m seo_agent.main check         # site validation (the "build")
../.venv-seo/bin/python -m seo_agent.main run --dry-run # report only, writes nothing
```
