# MoEngage Campaign QA Agent — Zero-Setup Team Usage

Once this is set up (one time, by whoever has repo/GitHub access), **nobody on the team
needs Python, pip, terminal access, or MoEngage API credentials on their own machine.**
The QA agent runs automatically on a schedule and posts results to Slack. Anyone can also
trigger an on-demand run from a button in GitHub's website — no code, no terminal.

## One-time setup (do this once)

### 1. Create a GitHub repo and push these files
```
git init
git add .
git commit -m "MoEngage QA agent"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```
Can be a private repo — this doesn't need to be public.

### 2. Add your credentials as GitHub Secrets (not in any file)
In the repo → **Settings → Secrets and variables → Actions → New repository secret**.
Add these four:

| Secret name | Value |
|---|---|
| `MOENGAGE_WORKSPACE_ID` | Your MoEngage Workspace/App ID |
| `MOENGAGE_API_KEY` | Your MoEngage API Key |
| `MOENGAGE_DATA_CENTER` | Your data center number, e.g. `01` |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL for your QA alerts channel |

These are encrypted by GitHub and never visible in logs or to anyone browsing the repo.

### 3. That's it — the workflow is already configured
`.github/workflows/qa-agent.yml` is already in this repo. Once secrets are added, it will:
- Run automatically every 30 minutes (edit the `cron` line in that file to change frequency)
- Post pass/fail results straight to your Slack channel
- Save a detailed `qa_report.json` you can download from the run's "Artifacts" section if needed

## Day-to-day usage for the team (zero setup, ever)

**To see results:** just check the Slack channel connected to the webhook. Nothing to install, run, or configure.

**To trigger an on-demand check right now** (e.g. right before a big send):
1. Go to the repo on GitHub → **Actions** tab
2. Click **"MoEngage Campaign QA"** on the left
3. Click **"Run workflow"** (top right) → **"Run workflow"** button
4. Results land in Slack within a minute or two — no terminal, no local setup, works from a phone browser too

**To change QA rules** (naming regex, which checks are on/off, thresholds):
Edit `qa_rules.json` directly on GitHub's website (click the file → pencil icon → edit → commit).
No local setup needed for this either — changes take effect on the next run automatically.

## If you'd rather have an on-demand web page instead of Slack/GitHub Actions

Good news — it's already built. `app.py` is a Streamlit dashboard: anyone opens a URL,
picks Status/Channel filters, clicks **"Run QA Check"**, and sees pass/fail results with
expandable issue details right in the browser. No terminal, no GitHub account, no Python
knowledge needed for anyone using it day-to-day.

### One-time setup (Streamlit Community Cloud — free, easiest option)

1. Push this whole folder to a GitHub repo (same repo as the Actions workflow above is fine —
   they can coexist).
2. Go to **share.streamlit.io** → sign in → **"New app"** → pick your repo, branch `main`,
   main file path `app.py`.
3. Before/after deploying, open the app's **Settings → Secrets** in Streamlit Cloud and paste:
   ```
   MOENGAGE_WORKSPACE_ID = "your_workspace_id"
   MOENGAGE_API_KEY = "your_api_key"
   MOENGAGE_DATA_CENTER = "01"
   SLACK_WEBHOOK_URL = ""
   ```
4. Deploy. You'll get a URL like `https://your-app-name.streamlit.app` — share that with the
   team. That's it, permanently — nobody else needs GitHub, Python, or credentials.

### Running it locally instead (e.g. to test changes before deploying)
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill in real values
streamlit run app.py
```
Opens automatically at `http://localhost:8501`.

### What the dashboard does
- Dropdown filters for campaign status (Scheduled/Active/etc.) and channel (Push/Email/SMS/All)
- One button to run all QA checks from `qa_rules.json` against matching campaigns
- Pass/flagged counts at a glance, expandable per-campaign issue details
- Downloadable JSON report
- A read-only view of the current QA rules at the bottom, so anyone can see what's being
  checked without opening any code

To change what gets checked, edit `qa_rules.json` (on GitHub's website works fine) — the
dashboard reads it fresh on every run, no redeploy needed.

## Client-wise + channel-wise QA (added)

The dashboard now starts with **Step 1: MoEngage account details**, entered directly in
the app on every run — Workspace ID, API Key, Data Center, and Client Name (KFC / HOAD /
WESTSIDE), in that order. Nothing is read from or written to a secrets file; the values
only live in your browser session and are gone on refresh/reload. **Step 2: Select channel
to QA** then picks which campaign channel (Push, Email, SMS, WhatsApp, or All) to check.
QA checks run against whichever client + channel you entered/picked.

This app deliberately does **not** use `.streamlit/secrets.toml` at all (avoids
`StreamlitSecretNotFoundError` when that file doesn't exist, which is expected in this
mode). `SLACK_WEBHOOK_URL` is still read from an environment variable if you want Slack
posting for the CLI/Actions path below, but the MoEngage account fields in the app itself
are manual-entry only.

The original single-account env vars (`MOENGAGE_WORKSPACE_ID` / `MOENGAGE_API_KEY` /
`MOENGAGE_DATA_CENTER`, no client suffix) still work as before for the CLI
(`python3 moengage_qa_agent.py`, no `--client` flag) and the GitHub Actions workflow —
nothing about that path changed. The CLI can also resolve per-client credentials from
`clients_config.json` / `MOENGAGE_*_<CLIENT>` env vars if you want that for automation:
```bash
python3 moengage_qa_agent.py --client KFC --status SCHEDULED --channel EMAIL
```
(`clients_config.json` is only used by this CLI path — the Streamlit app in Step 1 above
doesn't read it.)

### QA checks are now specific, not just present/not-present

`qa_rules.json` checks were upgraded from presence checks to meaningful, channel-aware
checks:

- **Conversion goals** (`conversion_goal_check.standard_goals_by_client`): verifies the 3
  standard goals are each present (matched by `goal_event_name`), have the correct primary
  flag, and that the primary/revenue goal has `revenue_attribute`/`revenue_currency` filled
  in — not just "is at least one goal configured". This is **per client**, keyed by the
  Client Name selected in Step 1 (e.g. `"KFC": [...]`), since the 3 standard goals are
  currently a KFC-specific convention. HOAD and WESTSIDE have no entry yet, so campaigns
  for those clients fall back to the plain presence-only checks until their standard goals
  are added the same way.

### Client + channel standards (`client_channel_rules`)

Beyond the checks above (which are the same shape for every client, just parameterized),
`qa_rules.json → client_channel_rules.<CLIENT>.<CHANNEL>` holds standards that are
genuinely specific to one client's one channel. Two are filled in so far:

#### KFC / PUSH

- **Tags**: `tags_must_match_name_segments` - derives the expected creative/cohort names
  from the campaign name and checks each shows up as a tag (see "Tags are a special
  case" below).
- **Exclude filters**: Israel country exclusion, Push Android reachability exclusion
  codes, Push iOS reachability exclusion codes, combined with OR — matched against the
  real `segmentation_details.excluded_filters` API shape (confirmed against a real
  campaign export).
- **Control group**: global control group must be enabled.
- **Delivery controls**: request limit (`campaign_throttle_rpm`) must be exactly 100000,
  `ignore_frequency_capping` must be off.
- **Conversion goal tracking window**: `attribution_window_in_hours` must be exactly 24.
- **Push content**: title/message required for Android+iOS+Web, plus a default click
  action must be set (Android/iOS use `default_click_action`, Web uses `redirect_url` -
  both matched by the same best-effort key search).

This all lives in `check_client_channel_rules` (and the `ccr` override passed into
`_check_push_content`/`check_tags`) in `moengage_qa_agent.py`. Add another
`client_channel_rules.HOAD.PUSH` (or any other client/channel) block the same way once
that standard is defined — nothing here is KFC-hardcoded in the Python, only in the JSON.

All of the above (except tags, see below) was confirmed against a real raw KFC PUSH
campaign export and verified to pass clean with zero false positives.

**Tags** are a special case: MoEngage's tag *categories* (e.g. "cohort", "creative")
aren't in the campaign API response, only the flat tag text is — and real tags are the
actual cohort/creative *names* (e.g. `High_frequency_shoppers`, `Fully Loaded Double
Rice`), not the literal words "cohort"/"creative". So `tags_must_match_name_segments:
true` instead derives the expected creative/cohort names from the campaign name itself
(`CLM_<creative>_<cohort>_push_<date>`) and checks each one shows up as a tag
(case/spacing/underscore-insensitive match) — confirmed against the real campaign.

**Still not wired in** (only 3 fields left): Precompute audience, Campaign audience
limit, and Background update targeting. All three were off/unchecked in the real
campaign used to confirm everything else, so their key names when turned ON are still
unknown — they're recorded under
`client_channel_rules.KFC.PUSH.pending_verification` with their required values. If a
campaign with any of these enabled ever slips through, dump its raw JSON and share it:
```bash
python3 moengage_qa_agent.py --client KFC --channel PUSH --status SCHEDULED --dump-raw kfc_push_sample.json
```

#### KFC / EMAIL

Confirmed against a real raw KFC EMAIL campaign export and verified clean:

- **Tags**: `tags_must_match_name_segments` (same approach as Push).
- **Exclude filters**: Israel country exclusion, a standard hard-bounce suppression
  segment (`CLM_HardBounce_11/11/24`), and an unsubscribed-users exclusion, combined
  with OR.
- **Control group**: global control group must be enabled.
- **Delivery controls**: request limit (`campaign_throttle_rpm`) must be exactly 60000
  (different from Push's 100000 — these are genuinely per-channel, not client-wide),
  `ignore_frequency_capping` and `bypass_dnd` must both be off.
- **Conversion goal tracking window**: exactly 5 hours (different from Push's 24 hours —
  also per-channel, not client-wide, hence why this lives in `client_channel_rules`
  rather than the shared `conversion_goal_check`).
- **Connector**: must be `SENDGRID`.
- **Email content**: from-address domain must be `marketing.kfc.com.ph`, sender name
  must be exactly "KFC Philippines", and reply-to must match the from-address.

#### HOAD_IND / HOAD_USA / HOAD_UAE / ANDGD_IND / EMAIL

HOAD isn't one MoEngage account - it's 4 separate dashboards (workspaces), each its own
Client entry with its own Workspace ID/API Key/Data Center. Confirmed against a real raw
HOAD_IND EMAIL campaign export:

- **Naming convention**: uses the pre-existing "ADH client" pattern -
  `ADH_<Brand>_<Creative>_<Account>_OMNI_<Channel>_WK<week>_<DDMMYYYY>`.
- **Tags**: `tags_must_match_named_segments` - unlike KFC's simpler 2-segment version,
  this maps specific *named* regex capture groups to expected tags: campaign type (`ADH`
  → tag `Adhoc`, via a `value_map`), creative, channel, and week (`25` → tag `WK25`, via
  a `template`). Brand and account intentionally have no tag requirement, per
  instructions.
- **Exclude filters**: only checks that *some* segment-based exclusion was added
  (`must_have_custom_segment_exclusion`) - the specific exclusion logic itself is
  campaign-specific (varies by promo, audience, etc.) and deliberately not locked in as
  a fixed standard, unlike KFC's exact country/segment/reachability checks.
- **Control group**: global control group must be **disabled** for HOAD_IND/HOAD_USA/
  HOAD_UAE, but **enabled** for ANDGD_IND — the opposite of each other, and both the
  opposite of KFC. (`check_control_group`, the generic blanket "no control group at all"
  check, automatically steps aside for any client/channel that has its own
  `client_channel_rules` control_group entry, so it doesn't conflict with this.)
- **Delivery controls**: request limit (`campaign_throttle_rpm`) must be exactly 1000 for
  EMAIL (1000 vs KFC Email's 60000 vs KFC Push's 100000 - genuinely a different number
  per client *and* channel).
- **Connector**: just checks *a* connector is configured (`required: true`), not a
  specific type like KFC's `SENDGRID` requirement.
- **Content**: no client-specific email content rules - the generic `content_check.email`
  defaults (presence + valid-format checks on subject/sender/from/reply-to) already cover
  what was asked for ("check hai ki nahi", not exact values).
- **Conversion goals**: 2 standard goals (`Order_Summary` primary/revenue,
  `LineItem_Purchase` secondary) - identical event names across all 4 dashboards, only
  `revenue_currency` differs (HOAD_IND/ANDGD_IND: INR, HOAD_USA: USD, HOAD_UAE: AED).
  Attribution window is confirmed at exactly 7 hours for all 4 dashboards, all channels.
- **ANDGD_IND only**: also requires a **brand** tag (`AD` or `GD`, matched literally - no
  `value_map` needed since, unlike `ADH` → `Adhoc`, the brand token doesn't get expanded).
  ANDGD_IND manages two sub-brands under one workspace, so distinguishing which brand a
  campaign is for via tag matters more here than for the single-brand HOAD dashboards
  (which have no brand-tag requirement).
- Confirmed against real campaigns for all 4 dashboards. The tag-segment fuzzy-matcher
  (`_texts_fuzzy_match`) had to be loosened from pure substring containment to also allow
  same-letters-any-order, since real tags don't always keep the same word order as the
  name (e.g. name segment `TRUNKSHOWBellevue` vs tag `Bellevue Trunk show`).

#### Channel availability outside PUSH/EMAIL (In-App, On-Site Messaging, WhatsApp)

Two real API limitations were hit and worked around while building this out - worth
knowing before adding more channels for any client:

- **In-App and On-Site Messaging (OSM) aren't available via any documented MoEngage
  campaigns API at all** (checked both `/campaigns/search` and the lighter
  `/campaigns/meta`) - not a bug in this tool, a current platform limitation. KFC's
  In-App/OSM QA is on hold until MoEngage exposes them.
- **WhatsApp isn't available via `/campaigns/search`** (confirmed by a real `400 Bad
  Request: channels is invalid passed value ['WHATSAPP']` error) **but is available via
  `/campaigns/meta`** - a separate, lighter endpoint that only returns campaign_id,
  channel, status, name, tags, platform, team, and (for scheduled campaigns) a
  reachability count. No content, targeting, control group, delivery controls,
  conversion goals, or connector data. `fetch_campaigns` (see `META_ONLY_CHANNELS` in
  `moengage_qa_agent.py`) automatically routes WhatsApp (and any other channel added to
  that set later) through `/campaigns/meta` instead, and tags the resulting campaign dict
  with `_meta_only: true`. `run_qa` checks this flag and runs only `LIGHTWEIGHT_CHECKS`
  (naming convention + tags) for such campaigns instead of the full `CHECKS` list - running
  the full list would report false "missing X" issues for every field that endpoint simply
  doesn't return. The Streamlit app shows a note on any campaign checked this way so it's
  clear the result is partial, not a clean pass.

All of this is config-driven from `qa_rules.json` — edit it on GitHub's website, no
redeploy needed, same as before.

