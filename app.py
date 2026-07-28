# """
# MoEngage Campaign QA — Web Dashboard
# --------------------------------------
# A no-terminal, no-code way for the team to run campaign QA checks.
# Anyone with the URL opens it in a browser, picks filters, clicks a button,
# and sees pass/fail results. Credentials live in Streamlit secrets, never
# touched by end users.

# Run locally:
#     streamlit run app.py

# Deploy (so the team just gets a URL, no local setup at all):
#     Streamlit Community Cloud (streamlit.io/cloud) is the simplest free option.
#     See README.md for full deployment steps.
# """

# import json
# import os
# from datetime import datetime, timezone

# import streamlit as st

# from moengage_qa_agent import fetch_campaigns, run_qa

# st.set_page_config(page_title="MoEngage Campaign QA", page_icon="✅", layout="wide")


# # ---------------------------------------------------------------------------
# # Config loading — pulls from Streamlit secrets first (for deployed use),
# # falls back to environment variables (for local runs), and always loads
# # QA rules fresh from qa_rules.json so edits to that file take effect
# # immediately without redeploying.
# # ---------------------------------------------------------------------------

# def get_credential(key, default=""):
#     if key in st.secrets:
#         return st.secrets[key]
#     return os.getenv(key, default)


# def load_rules():
#     with open("qa_rules.json", "r") as f:
#         rules = json.load(f)
#     rules["moengage"] = {
#         "workspace_id": get_credential("MOENGAGE_WORKSPACE_ID"),
#         "api_key": get_credential("MOENGAGE_API_KEY"),
#         "data_center": get_credential("MOENGAGE_DATA_CENTER", "01"),
#     }
#     rules["slack_webhook_url"] = get_credential("SLACK_WEBHOOK_URL", "")
#     return rules


# # ---------------------------------------------------------------------------
# # UI
# # ---------------------------------------------------------------------------

# st.title("✅ MoEngage Campaign QA")
# st.caption("Run pre-launch QA checks on your MoEngage campaigns — no terminal, no setup.")

# # ---------------------------------------------------------------------------
# # Sidebar: optional per-session credential override, so anyone can point
# # this at a different MoEngage account without touching Streamlit secrets
# # or redeploying. Left blank = falls back to the deployed default account.
# # Nothing entered here is saved anywhere - it only lives for this browser
# # session and is cleared on refresh.
# # ---------------------------------------------------------------------------

# with st.sidebar:
#     st.header("MoEngage account")
#     st.caption("Leave blank to use the default account configured for this app.")
#     override_workspace_id = st.text_input("Workspace ID", value="", key="override_workspace_id")
#     override_api_key = st.text_input("API Key", value="", type="password", key="override_api_key")
#     override_data_center = st.text_input(
#         "Data Center (e.g. 01)", value="", placeholder="01", key="override_data_center"
#     )
#     st.caption("These values are only used for your current session and are never saved.")

# rules = load_rules()

# if override_workspace_id.strip():
#     rules["moengage"]["workspace_id"] = override_workspace_id.strip()
# if override_api_key.strip():
#     rules["moengage"]["api_key"] = override_api_key.strip()
# if override_data_center.strip():
#     rules["moengage"]["data_center"] = override_data_center.strip()

# using_override = bool(override_workspace_id.strip() or override_api_key.strip())
# if using_override:
#     st.info("Using the MoEngage account entered in the sidebar for this session.", icon="🔑")

# if not rules["moengage"]["workspace_id"] or not rules["moengage"]["api_key"]:
#     st.error(
#         "No MoEngage credentials available. Either enter them in the sidebar, or whoever "
#         "deployed this app needs to add MOENGAGE_WORKSPACE_ID, MOENGAGE_API_KEY, and "
#         "MOENGAGE_DATA_CENTER in Streamlit secrets (see README.md)."
#     )
#     st.stop()

# col1, col2, col3 = st.columns(3)
# with col1:
#     status = st.selectbox(
#         "Campaign status",
#         ["SCHEDULED", "SENT", "ACTIVE", "PAUSED", "STOPPED"],
#         index=0,
#         help=(
#             "SCHEDULED and SENT are confirmed working for this account. "
#             "ACTIVE/PAUSED/STOPPED are included per MoEngage's general status list "
#             "but haven't been confirmed against your data yet - if one errors, "
#             "run debug_dump_campaign.py --list-statuses to see exactly what your "
#             "account returns. Draft campaigns aren't queryable through this API "
#             "at all (MoEngage only exposes drafts one-by-one via a different, "
#             "newer API once you already know the campaign ID) - so there's no "
#             "Draft option here."
#         ),
#     )
# with col2:
#     channel = st.selectbox("Channel", ["All", "PUSH", "EMAIL"], index=0)
# with col3:
#     limit = st.number_input("Max campaigns to check", min_value=1, max_value=15, value=15)

# run_clicked = st.button("▶ Run QA Check", type="primary", use_container_width=True)

# if run_clicked:
#     channel_filter = None if channel == "All" else channel
#     with st.spinner("Fetching campaigns and running checks..."):
#         try:
#             campaigns = fetch_campaigns(rules, status=status, channel=channel_filter, limit=int(limit))
#         except Exception as e:
#             st.error(f"Failed to fetch campaigns from MoEngage: {e}")
#             st.stop()

#         results = []
#         for campaign in campaigns:
#             issues = run_qa(campaign, rules)
#             results.append(
#                 {
#                     "campaign_id": campaign.get("campaign_id"),
#                     "name": campaign.get("basic_details", {}).get("name"),
#                     "channel": campaign.get("channel"),
#                     "status": campaign.get("status"),
#                     "issues": issues,
#                 }
#             )

#     if not results:
#         st.info("No campaigns matched that status/channel filter.")
#     else:
#         passed = sum(1 for r in results if not r["issues"])
#         failed = sum(1 for r in results if r["issues"])

#         c1, c2, c3 = st.columns(3)
#         c1.metric("Checked", len(results))
#         c2.metric("Passed", passed)
#         c3.metric("Flagged", failed)

#         st.divider()

#         for r in results:
#             icon = "🚨" if r["issues"] else "✅"
#             with st.expander(f"{icon} {r['name']}  ·  {r['channel']}  ·  {r['campaign_id']}", expanded=bool(r["issues"])):
#                 if r["issues"]:
#                     for issue in r["issues"]:
#                         st.markdown(f"- {issue}")
#                 else:
#                     st.markdown("No issues found.")

#         report_json = json.dumps(results, indent=2)
#         st.download_button(
#             "⬇ Download full report (JSON)",
#             data=report_json,
#             file_name=f"qa_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json",
#             mime="application/json",
#         )
# else:
#     st.info("Pick your filters above and click **Run QA Check** to get started.")

# st.divider()
# with st.expander("⚙ Current QA rules (edit qa_rules.json to change these)"):
#     st.json(rules)


"""
MoEngage Campaign QA — Web Dashboard
--------------------------------------
A no-terminal, no-code way for the team to run campaign QA checks.
Anyone with the URL opens it in a browser, picks filters, clicks a button,
and sees pass/fail results. Credentials live in Streamlit secrets, never
touched by end users.

Run locally:
    streamlit run app.py

Deploy (so the team just gets a URL, no local setup at all):
    Streamlit Community Cloud (streamlit.io/cloud) is the simplest free option.
    See README.md for full deployment steps.
"""

import json
import os
from datetime import datetime, timezone

import streamlit as st

from moengage_qa_agent import fetch_campaigns, run_qa

st.set_page_config(page_title="MoEngage Campaign QA", page_icon="✅", layout="wide")


# ---------------------------------------------------------------------------
# Config loading — pulls from Streamlit secrets first (for deployed use),
# falls back to environment variables (for local runs), and always loads
# QA rules fresh from qa_rules.json so edits to that file take effect
# immediately without redeploying.
# ---------------------------------------------------------------------------

def get_credential(key, default=""):
    if key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)


def load_rules():
    with open("qa_rules.json", "r") as f:
        rules = json.load(f)
    rules["moengage"] = {
        "workspace_id": get_credential("MOENGAGE_WORKSPACE_ID"),
        "api_key": get_credential("MOENGAGE_API_KEY"),
        "data_center": get_credential("MOENGAGE_DATA_CENTER", "01"),
    }
    rules["slack_webhook_url"] = get_credential("SLACK_WEBHOOK_URL", "")
    return rules


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("✅ MoEngage Campaign QA")
st.caption("Run pre-launch QA checks on your MoEngage campaigns — no terminal, no setup.")

# ---------------------------------------------------------------------------
# Sidebar: optional per-session credential override, so anyone can point
# this at a different MoEngage account without touching Streamlit secrets
# or redeploying. Left blank = falls back to the deployed default account.
# Nothing entered here is saved anywhere - it only lives for this browser
# session and is cleared on refresh.
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("MoEngage account")
    st.caption("Leave blank to use the default account configured for this app.")
    override_workspace_id = st.text_input("Workspace ID", value="", key="override_workspace_id")
    override_api_key = st.text_input("API Key", value="", type="password", key="override_api_key")
    override_data_center = st.text_input(
        "Data Center (e.g. 01)", value="", placeholder="01", key="override_data_center"
    )
    st.caption("These values are only used for your current session and are never saved.")

rules = load_rules()

if override_workspace_id.strip():
    rules["moengage"]["workspace_id"] = override_workspace_id.strip()
if override_api_key.strip():
    rules["moengage"]["api_key"] = override_api_key.strip()
if override_data_center.strip():
    rules["moengage"]["data_center"] = override_data_center.strip()

using_override = bool(override_workspace_id.strip() or override_api_key.strip())
if using_override:
    st.info("Using the MoEngage account entered in the sidebar for this session.", icon="🔑")

if not rules["moengage"]["workspace_id"] or not rules["moengage"]["api_key"]:
    st.error(
        "No MoEngage credentials available. Either enter them in the sidebar, or whoever "
        "deployed this app needs to add MOENGAGE_WORKSPACE_ID, MOENGAGE_API_KEY, and "
        "MOENGAGE_DATA_CENTER in Streamlit secrets (see README.md)."
    )
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    status = st.selectbox(
        "Campaign status",
        ["SCHEDULED", "DRAFT", "SENT", "ACTIVE", "PAUSED", "SENDING", "STOPPED", "ARCHIVED"],
        index=0,
        help=(
            "These are MoEngage's official V5 status values. SCHEDULED, SENT, and "
            "DRAFT are confirmed working for this account - others are included "
            "per MoEngage's documented status list but haven't all been individually "
            "confirmed against your data. If one errors, run "
            "debug_dump_campaign.py --list-statuses to see exactly what your account "
            "returns. Note: Draft campaigns are often missing lots of fields by "
            "design (that's what makes them drafts) - most of the QA checks below "
            "will flag what's still missing, which doubles as a pre-publish checklist."
        ),
    )
with col2:
    channel = st.selectbox("Channel", ["All", "PUSH", "EMAIL", "SMS"], index=0)
with col3:
    limit = st.number_input("Max campaigns to check", min_value=1, max_value=15, value=15)

run_clicked = st.button("▶ Run QA Check", type="primary", use_container_width=True)

if run_clicked:
    channel_filter = None if channel == "All" else channel
    with st.spinner("Fetching campaigns and running checks..."):
        try:
            campaigns = fetch_campaigns(rules, status=status, channel=channel_filter, limit=int(limit))
        except Exception as e:
            st.error(f"Failed to fetch campaigns from MoEngage: {e}")
            st.stop()

        results = []
        for campaign in campaigns:
            issues = run_qa(campaign, rules)
            results.append(
                {
                    "campaign_id": campaign.get("campaign_id"),
                    "name": campaign.get("basic_details", {}).get("name"),
                    "channel": campaign.get("channel"),
                    "status": campaign.get("status"),
                    "issues": issues,
                }
            )

    if not results:
        st.info("No campaigns matched that status/channel filter.")
    else:
        passed = sum(1 for r in results if not r["issues"])
        failed = sum(1 for r in results if r["issues"])

        c1, c2, c3 = st.columns(3)
        c1.metric("Checked", len(results))
        c2.metric("Passed", passed)
        c3.metric("Flagged", failed)

        st.divider()

        for r in results:
            icon = "🚨" if r["issues"] else "✅"
            with st.expander(f"{icon} {r['name']}  ·  {r['channel']}  ·  {r['campaign_id']}", expanded=bool(r["issues"])):
                if r["issues"]:
                    for issue in r["issues"]:
                        st.markdown(f"- {issue}")
                else:
                    st.markdown("No issues found.")

        report_json = json.dumps(results, indent=2)
        st.download_button(
            "⬇ Download full report (JSON)",
            data=report_json,
            file_name=f"qa_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
        )
else:
    st.info("Pick your filters above and click **Run QA Check** to get started.")

st.divider()
with st.expander("⚙ Current QA rules (edit qa_rules.json to change these)"):
    st.json(rules)
