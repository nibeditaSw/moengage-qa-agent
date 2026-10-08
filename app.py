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
# from io import BytesIO

# import streamlit as st
# from openpyxl import Workbook
# from openpyxl.styles import Font, PatternFill, Alignment
# from openpyxl.utils import get_column_letter

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

# def build_excel_report(results):
#     """Builds an in-memory .xlsx workbook from QA results: a per-campaign
#     Summary sheet, and a long-format Issues sheet (one row per issue) that's
#     easy to filter/pivot on in Excel."""
#     wb = Workbook()

#     HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
#     HEADER_FILL = PatternFill(start_color="2F5233", end_color="2F5233", fill_type="solid")
#     BODY_FONT = Font(name="Arial")
#     WRAP = Alignment(wrap_text=True, vertical="top")

#     def style_header_row(ws, row=1):
#         for cell in ws[row]:
#             cell.font = HEADER_FONT
#             cell.fill = HEADER_FILL
#             cell.alignment = Alignment(vertical="center")

#     def autofit(ws, widths):
#         for i, w in enumerate(widths, start=1):
#             ws.column_dimensions[get_column_letter(i)].width = w

#     # --- Summary sheet: one row per campaign ---
#     ws1 = wb.active
#     ws1.title = "Summary"
#     ws1.append(["Campaign ID", "Name", "Channel", "Status", "Issue Count", "Issues (combined)"])
#     for r in results:
#         ws1.append(
#             [
#                 r.get("campaign_id", ""),
#                 r.get("name", ""),
#                 r.get("channel", ""),
#                 r.get("status", ""),
#                 len(r.get("issues", [])),
#                 "; ".join(r.get("issues", [])) or "No issues found.",
#             ]
#         )
#     for row in ws1.iter_rows(min_row=2):
#         for cell in row:
#             cell.font = BODY_FONT
#         row[-1].alignment = WRAP
#     style_header_row(ws1)
#     ws1.freeze_panes = "A2"
#     autofit(ws1, [26, 40, 12, 14, 12, 70])

#     # --- Issues sheet: one row per issue, for easy filtering ---
#     ws2 = wb.create_sheet("Issues")
#     ws2.append(["Campaign ID", "Name", "Channel", "Status", "Issue"])
#     for r in results:
#         issues = r.get("issues", [])
#         if not issues:
#             continue
#         for issue in issues:
#             ws2.append([r.get("campaign_id", ""), r.get("name", ""), r.get("channel", ""), r.get("status", ""), issue])
#     for row in ws2.iter_rows(min_row=2):
#         for cell in row:
#             cell.font = BODY_FONT
#         row[-1].alignment = WRAP
#     style_header_row(ws2)
#     ws2.freeze_panes = "A2"
#     ws2.auto_filter.ref = ws2.dimensions
#     autofit(ws2, [26, 40, 12, 14, 70])

#     buffer = BytesIO()
#     wb.save(buffer)
#     buffer.seek(0)
#     return buffer



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
#         ["SCHEDULED", "DRAFT", "SENT", "ACTIVE", "PAUSED", "SENDING", "STOPPED", "ARCHIVED"],
#         index=0,
#         help=(
#             "These are MoEngage's official V5 status values. SCHEDULED, SENT, and "
#             "DRAFT are confirmed working for this account - others are included "
#             "per MoEngage's documented status list but haven't all been individually "
#             "confirmed against your data. If one errors, run "
#             "debug_dump_campaign.py --list-statuses to see exactly what your account "
#             "returns. Note: Draft campaigns are often missing lots of fields by "
#             "design (that's what makes them drafts) - most of the QA checks below "
#             "will flag what's still missing, which doubles as a pre-publish checklist."
#         ),
#     )
# with col2:
#     channel = st.selectbox("Channel", ["All", "PUSH", "EMAIL", "SMS"], index=0)
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

#         excel_buffer = build_excel_report(results)
#         st.download_button(
#             "⬇ Download full report (Excel)",
#             data=excel_buffer,
#             file_name=f"qa_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.xlsx",
#             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
from io import BytesIO

import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from moengage_qa_agent import fetch_campaigns, run_qa

st.set_page_config(page_title="MoEngage Campaign QA", page_icon="✅", layout="wide")


# ---------------------------------------------------------------------------
# Config loading — no secrets.toml / st.secrets involved anywhere. QA rules
# (qa_rules.json) are still loaded fresh from disk so edits take effect
# immediately without redeploying. MoEngage account details (Workspace ID,
# API Key, Data Center) and the Client are entered directly in the app on
# every run (Step 1 below) - nothing is read from or written to a secrets
# file, and nothing is saved anywhere between sessions.
# ---------------------------------------------------------------------------

def get_credential(key, default=""):
    """Env-var only (no st.secrets) - avoids StreamlitSecretNotFoundError
    when no .streamlit/secrets.toml exists, which is expected now that
    MoEngage credentials are entered directly in the app instead."""
    return os.getenv(key, default)


def load_rules():
    with open("qa_rules.json", "r") as f:
        rules = json.load(f)
    rules["slack_webhook_url"] = get_credential("SLACK_WEBHOOK_URL", "")
    return rules


CLIENT_OPTIONS = ["KFC", "HOAD_IND", "HOAD_USA", "HOAD_UAE", "ANDGD_IND", "WESTSIDE"]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def build_excel_report(results):
    """Builds an in-memory .xlsx workbook from QA results: a per-campaign
    Summary sheet, and a long-format Issues sheet (one row per issue) that's
    easy to filter/pivot on in Excel."""
    wb = Workbook()

    HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
    HEADER_FILL = PatternFill(start_color="2F5233", end_color="2F5233", fill_type="solid")
    BODY_FONT = Font(name="Arial")
    WRAP = Alignment(wrap_text=True, vertical="top")

    def style_header_row(ws, row=1):
        for cell in ws[row]:
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(vertical="center")

    def autofit(ws, widths):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    # --- Summary sheet: one row per campaign ---
    ws1 = wb.active
    ws1.title = "Summary"
    ws1.append(["Campaign ID", "Name", "Channel", "Status", "Issue Count", "Issues (combined)"])
    for r in results:
        ws1.append(
            [
                r.get("campaign_id", ""),
                r.get("name", ""),
                r.get("channel", ""),
                r.get("status", ""),
                len(r.get("issues", [])),
                "; ".join(r.get("issues", [])) or "No issues found.",
            ]
        )
    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
        row[-1].alignment = WRAP
    style_header_row(ws1)
    ws1.freeze_panes = "A2"
    autofit(ws1, [26, 40, 12, 14, 12, 70])

    # --- Issues sheet: one row per issue, for easy filtering ---
    ws2 = wb.create_sheet("Issues")
    ws2.append(["Campaign ID", "Name", "Channel", "Status", "Issue"])
    for r in results:
        issues = r.get("issues", [])
        if not issues:
            continue
        for issue in issues:
            ws2.append([r.get("campaign_id", ""), r.get("name", ""), r.get("channel", ""), r.get("status", ""), issue])
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
        row[-1].alignment = WRAP
    style_header_row(ws2)
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions
    autofit(ws2, [26, 40, 12, 14, 70])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer



st.caption("Run pre-launch QA checks on your MoEngage campaigns — no terminal, no setup.")

# ---------------------------------------------------------------------------
# Step 1: MoEngage account details, entered directly in the app - no
# secrets.toml, no environment file, nothing read from or saved to disk.
# Values only live in this browser session and are gone on refresh.
# ---------------------------------------------------------------------------

st.subheader("Step 1: MoEngage account details")
col_ws, col_key, col_dc, col_client = st.columns(4)
with col_ws:
    workspace_id = st.text_input("Workspace ID", value="", key="workspace_id_input")
with col_key:
    api_key = st.text_input("API Key", value="", type="password", key="api_key_input")
with col_dc:
    data_center = st.text_input("Data Center (e.g. 01)", value="", placeholder="01", key="data_center_input")
with col_client:
    client_key = st.selectbox(
        "Client Name",
        CLIENT_OPTIONS,
        index=None,
        placeholder="Choose a client...",
        key="client_key",
    )

if not workspace_id.strip() or not api_key.strip():
    st.info("Enter your Workspace ID and API Key above to continue.")
    st.stop()
if not client_key:
    st.info("Choose a client above to continue.")
    st.stop()

rules = load_rules()
rules["client_key"] = client_key
rules["moengage"] = {
    "workspace_id": workspace_id.strip(),
    "api_key": api_key.strip(),
    "data_center": data_center.strip() or "01",
}
st.caption(f"Using the account entered above for **{client_key}**.")

st.subheader("Step 2: Select channel to QA")
channel = st.selectbox(
    "Channel",
    ["All", "PUSH", "EMAIL", "SMS", "WHATSAPP", "RCS", "INAPP", "OSM"],
    index=0,
    key="channel_select",
    help=(
        "QA checks are applied based on this client + channel combination - each channel "
        "gets its own set of specific, meaningful checks (not just present/not-present). "
        "Availability differs by MoEngage's own API, not this tool: PUSH, EMAIL, and SMS "
        "get full checks (content, targeting, control group, delivery controls, goals, "
        "connector). WHATSAPP gets full checks too if this account has MoEngage's V5 API "
        "access set up - otherwise it automatically falls back to naming + tags only. "
        "RCS, INAPP, and OSM aren't available through any MoEngage campaigns API at all "
        "yet (per MoEngage Support) - selecting one of these shows a clear message rather "
        "than results."
    ),
)

st.subheader("Step 3: Filter & run")
col1, col2 = st.columns(2)
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
                    "limited_check": bool(campaign.get("_meta_only")),
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
                if r["limited_check"]:
                    st.caption(
                        "ℹ️ Limited data available for this channel via the API - only Naming "
                        "Convention and Tags were checked (content, targeting, control group, "
                        "delivery controls, conversion goals, and connector could not be checked)."
                    )
                if r["issues"]:
                    for issue in r["issues"]:
                        st.markdown(f"- {issue}")
                else:
                    st.markdown("No issues found.")

        excel_buffer = build_excel_report(results)
        st.download_button(
            "⬇ Download full report (Excel)",
            data=excel_buffer,
            file_name=f"qa_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Pick your filters above and click **Run QA Check** to get started.")

st.divider()
with st.expander("⚙ Current QA rules (edit qa_rules.json to change these)"):
    st.json(rules)
