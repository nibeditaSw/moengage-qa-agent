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

