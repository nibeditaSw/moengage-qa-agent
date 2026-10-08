# #!/usr/bin/env python3
# """
# MoEngage Campaign QA Agent
# ---------------------------
# Pulls campaigns from MoEngage (via the V5 Search Campaigns API) and runs a
# set of pre-launch quality checks against them: naming convention, tags,
# segments, content completeness, control group, conversion goals, delivery
# controls, UTM params/mismatch, personalization token sanity, broken links,
# compliance footer, and schedule sanity.

# Results are printed to stdout, written to a JSON report, and optionally
# posted to Slack via an incoming webhook.

# Docs referenced:
#   https://www.moengage.com/docs/api/get-campaign-details/search-campaigns-v5
#   https://www.moengage.com/docs/api/campaigns/search-campaigns-v5-migration
#   https://www.moengage.com/docs/api/introduction  (auth + data centers)

# Usage:
#   python3 moengage_qa_agent.py --status SCHEDULED
#   python3 moengage_qa_agent.py --status ACTIVE --channel EMAIL

# Environment variables (preferred over hardcoding secrets in qa_rules.json):
#   MOENGAGE_WORKSPACE_ID
#   MOENGAGE_API_KEY
#   MOENGAGE_DATA_CENTER   (e.g. "01")
#   SLACK_WEBHOOK_URL      (optional)
# """

# import argparse
# import base64
# import json
# import os
# import re
# import sys
# import uuid
# from datetime import datetime, timezone
# from pathlib import Path
# from urllib.parse import urlparse, parse_qs

# import requests

# CONFIG_PATH = Path(__file__).parent / "qa_rules.json"


# def load_config():
#     with open(CONFIG_PATH, "r") as f:
#         config = json.load(f)

#     # Environment variables override the config file for secrets.
#     config["moengage"]["workspace_id"] = os.getenv(
#         "MOENGAGE_WORKSPACE_ID", config["moengage"].get("workspace_id", "")
#     )
#     config["moengage"]["api_key"] = os.getenv(
#         "MOENGAGE_API_KEY", config["moengage"].get("api_key", "")
#     )
#     config["moengage"]["data_center"] = os.getenv(
#         "MOENGAGE_DATA_CENTER", config["moengage"].get("data_center", "01")
#     )
#     config["slack_webhook_url"] = os.getenv(
#         "SLACK_WEBHOOK_URL", config.get("slack_webhook_url", "")
#     )

#     if not config["moengage"]["workspace_id"] or not config["moengage"]["api_key"]:
#         sys.exit(
#             "ERROR: Missing MoEngage credentials. Set MOENGAGE_WORKSPACE_ID "
#             "and MOENGAGE_API_KEY as environment variables, or fill them in "
#             "qa_rules.json."
#         )
#     return config


# # ---------------------------------------------------------------------------
# # MoEngage API
# # ---------------------------------------------------------------------------

# def fetch_campaigns(config, status=None, channel=None, limit=15, page=1):
#     """Dispatches to V1 or V5 depending on what's being requested.

#     V1 is used by default because it works with the standard API key every
#     MoEngage account has (Settings > Account > APIs). V1 cannot return Draft
#     campaigns at all, though.

#     V5 is only used when status is exactly "DRAFT", since that's the only
#     thing V1 can't do. V5 requires a *different* kind of API key - one
#     generated from Settings > Account > API keys, a page that is an Early
#     Access feature MoEngage enables per-account on request (contact your
#     MoEngage CSM or Support team to turn it on). If that key isn't set up
#     yet, V5 calls fail with a 401 - see _fetch_campaigns_v5 for the specific
#     error message this raises in that case.

#     Both return the same shape: a plain list of campaign dicts.
#     """
#     if status == "DRAFT":
#         return _fetch_campaigns_v5(config, status=status, channel=channel, limit=limit, page=page)
#     return _fetch_campaigns_v1(config, status=status, channel=channel, limit=limit, page=page)


# def _fetch_campaigns_v1(config, status=None, channel=None, limit=15, page=1):
#     """Calls POST /core-services/v1/campaigns/search. Works with the standard
#     API key from Settings > Account > APIs. Cannot return Draft campaigns."""
#     dc = config["moengage"]["data_center"]
#     workspace_id = config["moengage"]["workspace_id"]
#     api_key = config["moengage"]["api_key"]

#     url = f"https://api-{dc}.moengage.com/core-services/v1/campaigns/search"

#     auth_string = base64.b64encode(f"{workspace_id}:{api_key}".encode()).decode()
#     headers = {
#         "Content-Type": "application/json",
#         "MOE-APPKEY": workspace_id,
#         "Authorization": f"Basic {auth_string}",
#     }

#     campaign_fields = {}
#     if status:
#         campaign_fields["status"] = [status]
#     if channel:
#         campaign_fields["channels"] = [channel]

#     body = {
#         "request_id": f"qa_agent_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
#         "campaign_fields": campaign_fields,
#         "limit": limit,
#         "page": page,
#     }

#     last_error = None
#     for attempt in range(2):  # try once, then one retry on timeout
#         try:
#             resp = requests.post(url, headers=headers, json=body, timeout=30)
#             if resp.status_code != 200:
#                 print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
#                 raise requests.exceptions.HTTPError(
#                     f"{resp.status_code} error from MoEngage: {resp.text}", response=resp
#                 )
#             return resp.json()
#         except requests.exceptions.Timeout as e:
#             last_error = e
#             continue  # retry once
#     raise last_error


# def _fetch_campaigns_v5(config, status=None, channel=None, limit=15, page=1):
#     """Calls POST /v5/campaigns/search - the only way to retrieve Draft
#     campaigns. Requires an API key generated from Settings > Account >
#     API keys (an Early Access feature - contact MoEngage CSM/Support to
#     enable it if that page isn't visible in your dashboard yet). Using a
#     standard V1-style key here will fail with a 401."""
#     dc = config["moengage"]["data_center"]
#     workspace_id = config["moengage"]["workspace_id"]
#     api_key = config["moengage"]["api_key"]

#     url = f"https://api-{dc}.moengage.com/v5/campaigns/search"

#     auth_string = base64.b64encode(f"{workspace_id}:{api_key}".encode()).decode()
#     request_id = str(uuid.uuid4())
#     headers = {
#         "Content-Type": "application/json",
#         "MOE-APPKEY": workspace_id,
#         "Authorization": f"Basic {auth_string}",
#         "X-MOE-Request-Id": request_id,      # required in V5, must match body.request_id if both set
#         "Idempotency-Key": str(uuid.uuid4()),  # required on every POST in V5
#     }

#     campaign_fields = {}
#     if status:
#         campaign_fields["status"] = [status]
#     if channel:
#         campaign_fields["channels"] = [channel]

#     body = {
#         "request_id": request_id,
#         "campaign_fields": campaign_fields,
#         "limit": limit,
#         "page": page,
#     }

#     last_error = None
#     for attempt in range(2):  # try once, then one retry on timeout
#         try:
#             resp = requests.post(url, headers=headers, json=body, timeout=30)
#             if resp.status_code == 401:
#                 raise requests.exceptions.HTTPError(
#                     "401 from MoEngage V5 API: your API key doesn't have V5/Campaigns "
#                     "permissions. Draft campaigns require a key generated from Settings > "
#                     "Account > API keys (with the Campaigns: View / Create & Manage / "
#                     "Create, Manage & Publish boxes checked) - this page is an Early Access "
#                     "feature; ask your MoEngage CSM or Support team to enable it for your "
#                     "account, then generate a key there and use it here.",
#                     response=resp,
#                 )
#             if resp.status_code != 200:
#                 print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
#                 raise requests.exceptions.HTTPError(
#                     f"{resp.status_code} error from MoEngage: {resp.text}", response=resp
#                 )
#             payload = resp.json()
#             return payload.get("data", {}).get("campaigns", [])
#         except requests.exceptions.Timeout as e:
#             last_error = e
#             continue  # retry once
#     raise last_error


# # ---------------------------------------------------------------------------
# # Individual checks. Each returns a list of issue strings (empty = pass).
# # ---------------------------------------------------------------------------

# def check_naming_convention(campaign, rules):
#     cfg = rules["naming_convention"]
#     if not cfg["enabled"]:
#         return []
#     name = campaign.get("basic_details", {}).get("name", "")
#     flags = re.IGNORECASE if cfg.get("regex_flags") == "IGNORECASE" else 0

#     for pattern_cfg in cfg.get("patterns", []):
#         if re.match(pattern_cfg["regex"], name, flags):
#             return []  # matched at least one valid pattern - pass

#     examples = "; OR ".join(f"{p['name']}: {p['example']}" for p in cfg.get("patterns", []))
#     return [f"Name '{name}' doesn't match any known naming convention. Expected format like: {examples}"]


# def check_utm_params(campaign, rules):
#     cfg = rules["utm_required"]
#     if not cfg["enabled"]:
#         return []
#     if campaign.get("channel") not in cfg["applies_to_channels"]:
#         return []
#     issues = []
#     utm = campaign.get("utm_params") or {}
#     for field in cfg["required_fields"]:
#         if not utm.get(field):
#             issues.append(f"Missing required UTM field: {field}")
#     return issues


# def _resolve_utm_template(value, campaign):
#     """Resolves known MoEngage dynamic tokens inside a utm_params template value."""
#     if not isinstance(value, str):
#         return value
#     resolved = value
#     resolved = resolved.replace("{{Campaign Channel}}", str(campaign.get("channel", "")))
#     resolved = resolved.replace(
#         "{{Campaign Name}}", str(campaign.get("basic_details", {}).get("name", ""))
#     )
#     return resolved


# def _extract_urls_with_query(campaign_content):
#     """Finds all http(s) URLs (with any query string) inside the campaign content."""
#     texts = _extract_content_strings(campaign_content)
#     url_pattern = re.compile(r'https?://[^\s"\'<>)]+')
#     urls = set()
#     for text in texts:
#         # unescape HTML entities commonly seen in email HTML (e.g. &amp; -> &)
#         cleaned = text.replace("&amp;", "&")
#         urls.update(url_pattern.findall(cleaned))
#     return [u for u in urls if "?" in u]


# def check_utm_mismatch(campaign, rules):
#     cfg = rules["utm_mismatch_check"]
#     if not cfg["enabled"]:
#         return []
#     if campaign.get("channel") not in cfg["applies_to_channels"]:
#         return []

#     campaign_utm = campaign.get("utm_params") or {}
#     if not campaign_utm:
#         return []  # nothing to compare against; check_utm_params already flags this

#     expected = {
#         field: _resolve_utm_template(campaign_utm.get(field), campaign)
#         for field in cfg["fields_to_compare"]
#         if campaign_utm.get(field)
#     }
#     if not expected:
#         return []

#     case_sensitive = cfg.get("case_sensitive", False)

#     def norm(v):
#         return v if case_sensitive else str(v).lower()

#     issues = []
#     urls = _extract_urls_with_query(campaign.get("campaign_content", {}))
#     for url in urls:
#         query = parse_qs(urlparse(url).query)
#         for field, expected_value in expected.items():
#             if field not in query:
#                 continue  # link doesn't tag this field at all; not a mismatch, just untagged
#             actual_value = query[field][0]
#             if norm(actual_value) != norm(expected_value):
#                 issues.append(
#                     f"UTM mismatch on '{field}' in link {url} — "
#                     f"link has '{actual_value}', campaign-level utm_params expects '{expected_value}'."
#                 )
#     return issues


# def _extract_content_strings(campaign_content):
#     """Pulls out any text/html strings from the (variable-shaped) content object."""
#     texts = []

#     def walk(obj):
#         if isinstance(obj, str):
#             texts.append(obj)
#         elif isinstance(obj, dict):
#             for v in obj.values():
#                 walk(v)
#         elif isinstance(obj, list):
#             for item in obj:
#                 walk(item)

#     walk(campaign_content)
#     return texts


# def check_personalization_tokens(campaign, rules):
#     if not rules["personalization_tokens"]["enabled"]:
#         return []
#     issues = []
#     texts = _extract_content_strings(campaign.get("campaign_content", {}))
#     for text in texts:
#         # Walk the string tracking {{ / }} as a stack so we find the exact
#         # position of a genuinely unmatched brace, rather than just comparing
#         # total counts (which flags huge HTML blobs with no real problem,
#         # and reports an unhelpful snippet from the start of the string).
#         open_positions = []
#         unmatched_positions = []
#         for m in re.finditer(r"\{\{|\}\}", text):
#             if m.group() == "{{":
#                 open_positions.append(m.start())
#             else:
#                 if open_positions:
#                     open_positions.pop()
#                 else:
#                     unmatched_positions.append(m.start())  # stray closing }}
#         unmatched_positions.extend(open_positions)  # any {{ never closed

#         for pos in sorted(set(unmatched_positions)):
#             start = max(0, pos - 25)
#             end = min(len(text), pos + 25)
#             snippet = text[start:end].replace("\n", " ").strip()
#             issues.append(f"Possible malformed personalization tag near: '...{snippet}...'")
#     return issues


# def check_links(campaign, rules):
#     if not rules["link_check"]["enabled"]:
#         return []
#     issues = []
#     texts = _extract_content_strings(campaign.get("campaign_content", {}))
#     url_pattern = re.compile(r'https?://[^\s"\'<>)]+')
#     urls = set()
#     for text in texts:
#         urls.update(url_pattern.findall(text))

#     timeout = rules["link_check"]["timeout_seconds"]
#     flag_above = rules["link_check"]["flag_status_codes_above"]
#     for url in urls:
#         try:
#             r = requests.head(url, timeout=timeout, allow_redirects=True)
#             if r.status_code > flag_above:
#                 issues.append(f"Link returned status {r.status_code}: {url}")
#         except requests.RequestException as e:
#             issues.append(f"Link unreachable ({e.__class__.__name__}): {url}")
#     return issues


# def check_compliance_footer(campaign, rules):
#     cfg = rules["compliance_footer"]
#     if not cfg["enabled"]:
#         return []
#     if campaign.get("channel") not in cfg["applies_to_channels"]:
#         return []
#     texts = _extract_content_strings(campaign.get("campaign_content", {}))
#     combined = " ".join(texts).lower()
#     if not any(phrase in combined for phrase in cfg["required_any_of"]):
#         return ["Email content is missing an unsubscribe / manage-preferences footer."]
#     return []


# def check_schedule_sanity(campaign, rules):
#     cfg = rules["schedule_sanity"]
#     if not cfg["enabled"]:
#         return []
#     issues = []
#     sched = campaign.get("scheduling_details", {}) or {}
#     start_time = sched.get("start_time")
#     if start_time:
#         try:
#             start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
#             if start_dt.tzinfo is None:
#                 start_dt = start_dt.replace(tzinfo=timezone.utc)
#             now = datetime.now(timezone.utc)
#             if cfg["flag_if_start_time_in_past"] and start_dt < now:
#                 issues.append(f"Scheduled start_time {start_time} is in the past.")
#             hour_cfg = cfg["flag_send_hour_outside_range"]
#             if hour_cfg["enabled"]:
#                 if not (hour_cfg["start_hour_utc"] <= start_dt.hour <= hour_cfg["end_hour_utc"]):
#                     issues.append(
#                         f"Send hour {start_dt.hour}:00 UTC is outside the approved "
#                         f"window ({hour_cfg['start_hour_utc']}:00-{hour_cfg['end_hour_utc']}:00 UTC)."
#                     )
#         except ValueError:
#             issues.append(f"Could not parse start_time: {start_time}")
#     return issues


# def check_segment_sanity(campaign, rules):
#     cfg = rules["segment_sanity"]
#     if not cfg["enabled"]:
#         return []
#     issues = []
#     seg = campaign.get("segmentation_details", {}) or {}
#     tags = campaign.get("basic_details", {}).get("tags", []) or []
#     is_all_user = seg.get("is_all_user_campaign")

#     if is_all_user and cfg["flag_if_all_user_campaign_without_tag"] not in tags:
#         issues.append(
#             "Campaign targets ALL users but is missing the "
#             f"'{cfg['flag_if_all_user_campaign_without_tag']}' approval tag."
#         )

#     if cfg.get("flag_if_no_included_filters") and not is_all_user:
#         included = (seg.get("included_filters") or {}).get("filters", [])
#         if not included:
#             issues.append(
#                 "Campaign is not marked as an all-user campaign but has zero "
#                 "included audience filters - check targeting, this may send to nobody."
#             )
#     return issues


# def check_tags(campaign, rules):
#     cfg = rules["tags_check"]
#     if not cfg["enabled"]:
#         return []
#     tags = campaign.get("basic_details", {}).get("tags", []) or []
#     if len(tags) < cfg.get("min_tags", 1):
#         return [f"Campaign has no tags (found {len(tags)}, expected at least {cfg.get('min_tags', 1)})."]
#     return []


# def check_content_completeness(campaign, rules):
#     cfg = rules["content_check"]
#     if not cfg["enabled"]:
#         return []
#     channel = campaign.get("channel")
#     if channel not in cfg.get("applies_to_channels", []):
#         return []

#     issues = []
#     content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}

#     if channel == "PUSH":
#         push = content_root.get("push", {}) or {}
#         if not push:
#             issues.append("No push content found for any platform.")
#         for platform, plat_data in push.items():
#             basic = (plat_data or {}).get("basic_details", {}) or {}
#             title = (basic.get("title") or "").strip()
#             message = (basic.get("message") or "").strip()
#             if not title:
#                 issues.append(f"[{platform}] push title is empty.")
#             if not message:
#                 issues.append(f"[{platform}] push message is empty.")
#     elif channel == "EMAIL":
#         email = content_root.get("email", {}) or {}
#         if not email:
#             issues.append("No email content block found.")
#             return issues

#         subject = (email.get("subject") or "").strip()
#         preview_text = (email.get("preview_text") or "").strip()
#         sender_name = (email.get("sender_name") or "").strip()
#         from_address = (email.get("from_address") or "").strip()
#         reply_to_address = (email.get("reply_to_address") or "").strip()
#         html_content = (email.get("html_content") or "").strip()

#         if not subject:
#             issues.append("Email subject line is empty.")
#         if not preview_text:
#             issues.append("Email preview text is empty.")
#         if not sender_name:
#             issues.append("Email sender name is empty.")
#         if not from_address:
#             issues.append("Email from_address is empty.")
#         if not reply_to_address:
#             issues.append("Email reply_to_address is empty.")
#         if len(html_content) < cfg.get("min_total_content_length", 200):
#             issues.append(
#                 f"Email html_content looks unusually short/empty "
#                 f"({len(html_content)} chars, expected at least {cfg.get('min_total_content_length', 200)})."
#             )
#     else:
#         # Generic fallback for other channels (e.g. SMS) whose exact schema
#         # we haven't confirmed yet - checks there's a reasonable amount of text.
#         channel_key = channel.lower()
#         node = content_root.get(channel_key) or content_root
#         texts = _extract_content_strings(node)
#         total_len = sum(len(t.strip()) for t in texts)
#         min_len = cfg.get("min_total_content_length", 200)
#         if total_len < min_len:
#             issues.append(
#                 f"Content for {channel} looks unusually short or empty "
#                 f"(extracted {total_len} chars, expected at least {min_len})."
#             )
#     return issues


# def check_control_group(campaign, rules):
#     cfg = rules["control_group_check"]
#     if not cfg["enabled"]:
#         return []
#     cg = campaign.get("control_group_details", {}) or {}
#     issues = []
#     global_enabled = cg.get("is_global_control_group_enabled", False)
#     campaign_enabled = cg.get("is_campaign_control_group_enabled", False)
#     campaign_pct = cg.get("campaign_control_group_percentage", 0) or 0

#     if cfg.get("flag_if_no_control_group") and not global_enabled and not campaign_enabled:
#         issues.append(
#             "Neither global nor campaign-level control group is enabled - "
#             "no way to measure this campaign's incremental impact."
#         )
#     if campaign_enabled and campaign_pct <= 0:
#         issues.append("Campaign-level control group is enabled but percentage is 0.")
#     return issues


# def check_conversion_goals(campaign, rules):
#     cfg = rules["conversion_goal_check"]
#     if not cfg["enabled"]:
#         return []
#     goals = (campaign.get("conversion_goal_details", {}) or {}).get("goals", []) or []
#     issues = []

#     if cfg.get("require_at_least_one_goal") and not goals:
#         issues.append("No conversion goals configured for this campaign.")

#     if cfg.get("require_exactly_one_primary_goal") and goals:
#         primary_count = sum(1 for g in goals if g.get("is_primary_goal"))
#         if primary_count == 0:
#             issues.append("No conversion goal is marked as primary (need exactly one).")
#         elif primary_count > 1:
#             issues.append(f"{primary_count} conversion goals are marked primary - should be exactly one.")
#     return issues


# def check_delivery_controls(campaign, rules):
#     cfg = rules["delivery_controls_check"]
#     if not cfg["enabled"]:
#         return []
#     dc = campaign.get("delivery_controls", {}) or {}
#     issues = []

#     if cfg.get("flag_if_ignore_frequency_capping") and dc.get("ignore_frequency_capping"):
#         issues.append("Campaign is set to ignore frequency capping - may over-message users.")
#     if cfg.get("flag_if_throttle_rpm_zero") and not dc.get("campaign_throttle_rpm"):
#         issues.append("Campaign throttle (campaign_throttle_rpm) is 0 or unset.")
#     if cfg.get("flag_if_bypass_dnd") and dc.get("bypass_dnd"):
#         issues.append("Campaign is set to bypass Do-Not-Disturb hours (bypass_dnd=true).")
#     return issues


# CHECKS = [
#     check_naming_convention,
#     check_tags,
#     check_segment_sanity,
#     check_content_completeness,
#     check_control_group,
#     check_conversion_goals,
#     check_delivery_controls,
#     check_utm_params,
#     check_utm_mismatch,
#     check_personalization_tokens,
#     check_links,
#     check_compliance_footer,
#     check_schedule_sanity,
# ]


# def run_qa(campaign, rules):
#     issues = []
#     for check_fn in CHECKS:
#         issues.extend(check_fn(campaign, rules))
#     return issues


# # ---------------------------------------------------------------------------
# # Reporting
# # ---------------------------------------------------------------------------

# def post_to_slack(webhook_url, results):
#     if not webhook_url:
#         return
#     failed = [r for r in results if r["issues"]]
#     if not failed:
#         text = "✅ MoEngage Campaign QA: all checked campaigns passed."
#     else:
#         lines = [f"🚨 MoEngage Campaign QA found issues in {len(failed)} campaign(s):"]
#         for r in failed:
#             lines.append(f"\n*{r['name']}* ({r['campaign_id']}, {r['channel']})")
#             for issue in r["issues"]:
#                 lines.append(f"  • {issue}")
#         text = "\n".join(lines)
#     try:
#         requests.post(webhook_url, json={"text": text}, timeout=10)
#     except requests.RequestException as e:
#         print(f"Failed to post to Slack: {e}", file=sys.stderr)


# def main():
#     parser = argparse.ArgumentParser(description="MoEngage Campaign QA Agent")
#     parser.add_argument("--status", help="Filter by status, e.g. SCHEDULED, ACTIVE")
#     parser.add_argument("--channel", help="Filter by channel, e.g. EMAIL, PUSH, SMS")
#     parser.add_argument("--limit", type=int, default=15, help="Campaigns per page (max 15)")
#     parser.add_argument("--page", type=int, default=1)
#     parser.add_argument("--out", default="qa_report.json", help="Path to write JSON report")
#     args = parser.parse_args()

#     config = load_config()
#     campaigns = fetch_campaigns(
#         config, status=args.status, channel=args.channel, limit=args.limit, page=args.page
#     )

#     results = []
#     for campaign in campaigns:
#         issues = run_qa(campaign, config)
#         results.append(
#             {
#                 "campaign_id": campaign.get("campaign_id"),
#                 "name": campaign.get("basic_details", {}).get("name"),
#                 "channel": campaign.get("channel"),
#                 "status": campaign.get("status"),
#                 "issues": issues,
#             }
#         )

#     with open(args.out, "w") as f:
#         json.dump(results, f, indent=2)

#     passed = sum(1 for r in results if not r["issues"])
#     failed = sum(1 for r in results if r["issues"])
#     print(f"Checked {len(results)} campaign(s): {passed} passed, {failed} flagged.")
#     for r in results:
#         if r["issues"]:
#             print(f"\n[FAIL] {r['name']} ({r['campaign_id']}, {r['channel']})")
#             for issue in r["issues"]:
#                 print(f"   - {issue}")

#     post_to_slack(config.get("slack_webhook_url"), results)


# if __name__ == "__main__":
#     main()




#!/usr/bin/env python3
"""
MoEngage Campaign QA Agent
---------------------------
Pulls campaigns from MoEngage (via the V5 Search Campaigns API) and runs a
set of pre-launch quality checks against them: naming convention, tags,
segments, content completeness, control group, conversion goals, delivery
controls, UTM params/mismatch, personalization token sanity, broken links,
compliance footer, and schedule sanity.

Results are printed to stdout, written to a JSON report, and optionally
posted to Slack via an incoming webhook.

Docs referenced:
  https://www.moengage.com/docs/api/get-campaign-details/search-campaigns-v5
  https://www.moengage.com/docs/api/campaigns/search-campaigns-v5-migration
  https://www.moengage.com/docs/api/introduction  (auth + data centers)

Usage:
  python3 moengage_qa_agent.py --status SCHEDULED
  python3 moengage_qa_agent.py --status ACTIVE --channel EMAIL

Environment variables (preferred over hardcoding secrets in qa_rules.json):
  MOENGAGE_WORKSPACE_ID
  MOENGAGE_API_KEY
  MOENGAGE_DATA_CENTER   (e.g. "01")
  SLACK_WEBHOOK_URL      (optional)
"""

import argparse
import base64
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

CONFIG_PATH = Path(__file__).parent / "qa_rules.json"
CLIENTS_CONFIG_PATH = Path(__file__).parent / "clients_config.json"


def load_clients_config():
    """Loads the per-client MoEngage account directory (clients_config.json).
    Returns {} if the file isn't present, so single-account setups (the
    original behavior) keep working untouched."""
    if not CLIENTS_CONFIG_PATH.exists():
        return {}
    with open(CLIENTS_CONFIG_PATH, "r") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_client_credentials(client_key, clients_config=None):
    """Resolves the MoEngage account (client_name, workspace_id, api_key,
    data_center) for one client key (e.g. 'KFC'). Environment variables /
    Streamlit secrets named MOENGAGE_<FIELD>_<CLIENT_KEY> always win over
    whatever is in clients_config.json, same "env overrides file" pattern
    the original single-account config used."""
    clients_config = clients_config if clients_config is not None else load_clients_config()
    entry = clients_config.get(client_key, {})
    suffix = client_key.upper()
    return {
        "client_name": entry.get("client_name", client_key),
        "workspace_id": os.getenv(f"MOENGAGE_WORKSPACE_ID_{suffix}", entry.get("workspace_id", "")),
        "api_key": os.getenv(f"MOENGAGE_API_KEY_{suffix}", entry.get("api_key", "")),
        "data_center": os.getenv(f"MOENGAGE_DATA_CENTER_{suffix}", entry.get("data_center", "01")),
    }


def load_config(client=None):
    """Loads qa_rules.json. If `client` is given (a key from
    clients_config.json, e.g. "KFC"), the moengage account block is
    resolved for that client. Otherwise falls back to the original
    single-account behavior (MOENGAGE_WORKSPACE_ID / MOENGAGE_API_KEY /
    MOENGAGE_DATA_CENTER env vars, or the "moengage" block in qa_rules.json)
    so existing single-account setups (e.g. the GitHub Actions workflow)
    keep working unchanged."""
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    if client:
        creds = resolve_client_credentials(client)
        config["moengage"] = {
            "workspace_id": creds["workspace_id"],
            "api_key": creds["api_key"],
            "data_center": creds["data_center"],
        }
        config["client_name"] = creds["client_name"]
        config["client_key"] = client
    else:
        config["client_key"] = None
        # Environment variables override the config file for secrets.
        config["moengage"]["workspace_id"] = os.getenv(
            "MOENGAGE_WORKSPACE_ID", config["moengage"].get("workspace_id", "")
        )
        config["moengage"]["api_key"] = os.getenv(
            "MOENGAGE_API_KEY", config["moengage"].get("api_key", "")
        )
        config["moengage"]["data_center"] = os.getenv(
            "MOENGAGE_DATA_CENTER", config["moengage"].get("data_center", "01")
        )

    config["slack_webhook_url"] = os.getenv(
        "SLACK_WEBHOOK_URL", config.get("slack_webhook_url", "")
    )

    if not config["moengage"]["workspace_id"] or not config["moengage"]["api_key"]:
        sys.exit(
            "ERROR: Missing MoEngage credentials. Set MOENGAGE_WORKSPACE_ID "
            "and MOENGAGE_API_KEY as environment variables (or the "
            "per-client MOENGAGE_WORKSPACE_ID_<CLIENT>/MOENGAGE_API_KEY_<CLIENT> "
            "equivalents), or fill them in qa_rules.json / clients_config.json."
        )
    return config


# ---------------------------------------------------------------------------
# MoEngage API
# ---------------------------------------------------------------------------

META_ONLY_CHANNELS = set()
# Was {"WHATSAPP", "SMS"}. Per MoEngage Support (ticket reply, confirmed with
# docs link https://www.moengage.com/docs/api/get-campaign-details/search-campaigns):
# SMS *is* supported by /core-services/v1/campaigns/search like PUSH/EMAIL -
# our original "SMS behaves the same as WHATSAPP" assumption was wrong, so SMS
# now goes through the normal full-detail V1 Search path below, same as
# PUSH/EMAIL. WHATSAPP is handled separately - see V5_PREFERRED_CHANNELS.

V5_PREFERRED_CHANNELS = {"WHATSAPP"}
# /core-services/v1/campaigns/search rejects WHATSAPP outright (confirmed
# empirically: passing channels=["WHATSAPP"] there returns a 400 "channels is
# invalid passed value" error). Per MoEngage Support, /v5/campaigns/search
# DOES support it with full detail. V5 needs a different, Early-Access API
# key (see _fetch_campaigns_v5's docstring) that may not be provisioned yet,
# so fetch_campaigns() tries V5 first for these channels and automatically
# falls back to the lightweight /campaigns/meta endpoint (naming + tags only
# - see _fetch_campaigns_meta) if V5 isn't available for this account yet.
# Once V5 access is granted, WhatsApp automatically starts getting full
# checks with no config change needed here.

UNAVAILABLE_CHANNELS = {"RCS", "INAPP", "OSM", "ON_SITE_MESSAGING"}
# Channels with no *campaign-level* API access at all right now, per
# MoEngage Support directly: RCS has no API of any kind yet (Support
# suggested filing a feature request). In-App and On-Site Messaging have
# template-level APIs (/custom-templates/inapp, /custom-templates/osm) for
# managing creative content, but nothing for campaign-level
# targeting/scheduling/control-group/etc., so there's no campaign to QA via
# API for these yet. Listed here so fetch_campaigns can fail with a clear
# explanation instead of a confusing raw API error.


def fetch_campaigns(config, status=None, channel=None, limit=15, page=1):
    """Dispatches to V1 Search, V5 Search, or the V1 Meta endpoint depending
    on what's being requested.

    V1 Search is used by default because it works with the standard API key
    every MoEngage account has (Settings > Account > APIs), and gives full
    campaign detail. It cannot return Draft campaigns, and cannot return
    WHATSAPP (or FACEBOOK/GOOGLE ADS/CONNECTORS) campaigns at all - see
    V5_PREFERRED_CHANNELS.

    V5 Search is used for Draft campaigns (status == "DRAFT") and for
    V5_PREFERRED_CHANNELS, since V1 Search can't do either. V5 requires a
    *different* kind of API key - one generated from Settings > Account >
    API keys, a page that is an Early Access feature MoEngage enables
    per-account on request (contact your MoEngage CSM or Support team to
    turn it on). If that key isn't set up yet, V5 calls fail with a 401 -
    see _fetch_campaigns_v5 for the specific error message this raises in
    that case. For a V5_PREFERRED_CHANNELS channel specifically (not for
    Draft status), that 401 is caught here and this falls back to V1 Meta
    automatically rather than failing outright.

    V1 Meta is the fallback for V5_PREFERRED_CHANNELS channels when V5 isn't
    available for this account.

    All three return the same shape: a plain list of campaign dicts (Meta's
    are reshaped to match; see _fetch_campaigns_meta).
    """
    if channel and channel.upper() in UNAVAILABLE_CHANNELS:
        # Deliberately a normal exception, not sys.exit(): sys.exit() raises
        # SystemExit, which is NOT a subclass of Exception, so app.py's
        # `except Exception` around this call wouldn't catch it and the
        # whole Streamlit app would crash instead of showing a clean error.
        raise RuntimeError(
            f"'{channel}' campaigns have no campaign-level API access right now (per "
            "MoEngage Support) - this is a current MoEngage platform limitation, not a "
            "bug in this tool. In-App/On-Site Messaging do have template-level APIs "
            "(/custom-templates/inapp, /custom-templates/osm) for managing creative "
            "content, but not campaign targeting/scheduling/etc., so this tool doesn't "
            "use them yet. RCS has no API at all - MoEngage Support suggested filing a "
            "feature request. Only PUSH/EMAIL/SMS (full detail) and WHATSAPP (full "
            "detail if V5 API access is set up, otherwise naming + tags only) can be "
            "checked today."
        )
    if channel in V5_PREFERRED_CHANNELS and status != "DRAFT":
        try:
            return _fetch_campaigns_v5(config, status=status, channel=channel, limit=limit, page=page)
        except requests.exceptions.HTTPError as e:
            if getattr(e.response, "status_code", None) == 401:
                return _fetch_campaigns_meta(config, status=status, channel=channel, limit=limit, page=page)
            raise
    if status == "DRAFT":
        return _fetch_campaigns_v5(config, status=status, channel=channel, limit=limit, page=page)
    return _fetch_campaigns_v1(config, status=status, channel=channel, limit=limit, page=page)


def _fetch_campaigns_v1(config, status=None, channel=None, limit=15, page=1):
    """Calls POST /core-services/v1/campaigns/search. Works with the standard
    API key from Settings > Account > APIs. Cannot return Draft campaigns."""
    dc = config["moengage"]["data_center"]
    workspace_id = config["moengage"]["workspace_id"]
    api_key = config["moengage"]["api_key"]

    url = f"https://api-{dc}.moengage.com/core-services/v1/campaigns/search"

    auth_string = base64.b64encode(f"{workspace_id}:{api_key}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "MOE-APPKEY": workspace_id,
        "Authorization": f"Basic {auth_string}",
    }

    campaign_fields = {}
    if status:
        campaign_fields["status"] = [status]
    if channel:
        campaign_fields["channels"] = [channel]

    body = {
        "request_id": f"qa_agent_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "campaign_fields": campaign_fields,
        "limit": limit,
        "page": page,
    }

    last_error = None
    for attempt in range(2):  # try once, then one retry on timeout
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code != 200:
                print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
                raise requests.exceptions.HTTPError(
                    f"{resp.status_code} error from MoEngage: {resp.text}", response=resp
                )
            return resp.json()
        except requests.exceptions.Timeout as e:
            last_error = e
            continue  # retry once
    raise last_error


def _fetch_campaigns_meta(config, status=None, channel=None, limit=15, page=1):
    """Calls POST /core-services/v1/campaigns/meta (V1 - Legacy). Works with
    the standard API key from Settings > Account > APIs, same as V1 Search.
    Used for channels V1/V5 Search reject (see META_ONLY_CHANNELS) - returns
    much less per campaign (no content/targeting/control-group/delivery-
    controls/conversion-goals/connector), so results are reshaped into the
    same basic_details.{name,tags} shape the rest of this tool expects, with
    _meta_only=True marking them as limited-detail for run_qa()."""
    dc = config["moengage"]["data_center"]
    workspace_id = config["moengage"]["workspace_id"]
    api_key = config["moengage"]["api_key"]

    url = f"https://api-{dc}.moengage.com/core-services/v1/campaigns/meta"

    auth_string = base64.b64encode(f"{workspace_id}:{api_key}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "MOE-APPKEY": workspace_id,
        "Authorization": f"Basic {auth_string}",
    }

    campaign_fields = {}
    if status:
        campaign_fields["status"] = [status]
    if channel:
        campaign_fields["channels"] = [channel]

    body = {
        "request_id": f"qa_agent_meta_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "campaign_fields": campaign_fields,
        "limit": limit,
        "page": page,
    }

    last_error = None
    for attempt in range(2):  # try once, then one retry on timeout
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code != 200:
                print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
                raise requests.exceptions.HTTPError(
                    f"{resp.status_code} error from MoEngage: {resp.text}", response=resp
                )
            return [_reshape_meta_campaign(item) for item in resp.json()]
        except requests.exceptions.Timeout as e:
            last_error = e
            continue  # retry once
    raise last_error


def _reshape_meta_campaign(meta):
    """Maps one /campaigns/meta response item onto the same shape the rest
    of this tool expects from /campaigns/search - the full original response
    is kept under _raw_meta for reference/debugging."""
    return {
        "campaign_id": meta.get("campaign_id"),
        "channel": meta.get("channel"),
        "status": meta.get("campaign_status"),
        "campaign_delivery_type": meta.get("campaign_delivery_type"),
        "basic_details": {
            "name": meta.get("campaign_name", ""),
            "tags": meta.get("campaign_tags", []) or [],
            "platforms": meta.get("platform", []) or [],
        },
        "_meta_only": True,
        "_raw_meta": meta,
    }


def _fetch_campaigns_v5(config, status=None, channel=None, limit=15, page=1):
    """Calls POST /v5/campaigns/search - the only way to retrieve Draft
    campaigns. Requires an API key generated from Settings > Account >
    API keys (an Early Access feature - contact MoEngage CSM/Support to
    enable it if that page isn't visible in your dashboard yet). Using a
    standard V1-style key here will fail with a 401."""
    dc = config["moengage"]["data_center"]
    workspace_id = config["moengage"]["workspace_id"]
    api_key = config["moengage"]["api_key"]

    url = f"https://api-{dc}.moengage.com/v5/campaigns/search"

    auth_string = base64.b64encode(f"{workspace_id}:{api_key}".encode()).decode()
    request_id = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "MOE-APPKEY": workspace_id,
        "Authorization": f"Basic {auth_string}",
        "X-MOE-Request-Id": request_id,      # required in V5, must match body.request_id if both set
        "Idempotency-Key": str(uuid.uuid4()),  # required on every POST in V5
    }

    campaign_fields = {}
    if status:
        campaign_fields["status"] = [status]
    if channel:
        campaign_fields["channels"] = [channel]

    body = {
        "request_id": request_id,
        "campaign_fields": campaign_fields,
        "limit": limit,
        "page": page,
    }

    last_error = None
    for attempt in range(2):  # try once, then one retry on timeout
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code == 401:
                raise requests.exceptions.HTTPError(
                    "401 from MoEngage V5 API: your API key doesn't have V5/Campaigns "
                    "permissions. Draft campaigns require a key generated from Settings > "
                    "Account > API keys (with the Campaigns: View / Create & Manage / "
                    "Create, Manage & Publish boxes checked) - this page is an Early Access "
                    "feature; ask your MoEngage CSM or Support team to enable it for your "
                    "account, then generate a key there and use it here.",
                    response=resp,
                )
            if resp.status_code != 200:
                print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
                raise requests.exceptions.HTTPError(
                    f"{resp.status_code} error from MoEngage: {resp.text}", response=resp
                )
            payload = resp.json()
            return payload.get("data", {}).get("campaigns", [])
        except requests.exceptions.Timeout as e:
            last_error = e
            continue  # retry once
    raise last_error


# ---------------------------------------------------------------------------
# Individual checks. Each returns a list of issue strings (empty = pass).
# ---------------------------------------------------------------------------

def check_naming_convention(campaign, rules):
    cfg = rules["naming_convention"]
    if not cfg["enabled"]:
        return []
    name = campaign.get("basic_details", {}).get("name", "")
    flags = re.IGNORECASE if cfg.get("regex_flags") == "IGNORECASE" else 0

    for pattern_cfg in cfg.get("patterns", []):
        if re.match(pattern_cfg["regex"], name, flags):
            return []  # matched at least one valid pattern - pass

    examples = "; OR ".join(f"{p['name']}: {p['example']}" for p in cfg.get("patterns", []))
    return [f"Name '{name}' doesn't match any known naming convention. Expected format like: {examples}"]


def check_utm_params(campaign, rules):
    cfg = rules["utm_required"]
    if not cfg["enabled"]:
        return []
    if campaign.get("channel") not in cfg["applies_to_channels"]:
        return []
    issues = []
    utm = campaign.get("utm_params") or {}
    for field in cfg["required_fields"]:
        if not utm.get(field):
            issues.append(f"Missing required UTM field: {field}")
    return issues


def _resolve_utm_template(value, campaign):
    """Resolves known MoEngage dynamic tokens inside a utm_params template value."""
    if not isinstance(value, str):
        return value
    resolved = value
    resolved = resolved.replace("{{Campaign Channel}}", str(campaign.get("channel", "")))
    resolved = resolved.replace(
        "{{Campaign Name}}", str(campaign.get("basic_details", {}).get("name", ""))
    )
    return resolved


def _extract_urls_with_query(campaign_content):
    """Finds all http(s) URLs (with any query string) inside the campaign content."""
    texts = _extract_content_strings(campaign_content)
    url_pattern = re.compile(r'https?://[^\s"\'<>)]+')
    urls = set()
    for text in texts:
        # unescape HTML entities commonly seen in email HTML (e.g. &amp; -> &)
        cleaned = text.replace("&amp;", "&")
        urls.update(url_pattern.findall(cleaned))
    return [u for u in urls if "?" in u]


def check_utm_mismatch(campaign, rules):
    cfg = rules["utm_mismatch_check"]
    if not cfg["enabled"]:
        return []
    if campaign.get("channel") not in cfg["applies_to_channels"]:
        return []

    campaign_utm = campaign.get("utm_params") or {}
    if not campaign_utm:
        return []  # nothing to compare against; check_utm_params already flags this

    expected = {
        field: _resolve_utm_template(campaign_utm.get(field), campaign)
        for field in cfg["fields_to_compare"]
        if campaign_utm.get(field)
    }
    if not expected:
        return []

    case_sensitive = cfg.get("case_sensitive", False)

    def norm(v):
        return v if case_sensitive else str(v).lower()

    issues = []
    urls = _extract_urls_with_query(campaign.get("campaign_content", {}))
    for url in urls:
        query = parse_qs(urlparse(url).query)
        for field, expected_value in expected.items():
            if field not in query:
                continue  # link doesn't tag this field at all; not a mismatch, just untagged
            actual_value = query[field][0]
            if norm(actual_value) != norm(expected_value):
                issues.append(
                    f"UTM mismatch on '{field}' in link {url} — "
                    f"link has '{actual_value}', campaign-level utm_params expects '{expected_value}'."
                )
    return issues


def _extract_content_strings(campaign_content):
    """Pulls out any text/html strings from the (variable-shaped) content object."""
    texts = []

    def walk(obj):
        if isinstance(obj, str):
            texts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(campaign_content)
    return texts


def check_personalization_tokens(campaign, rules):
    if not rules["personalization_tokens"]["enabled"]:
        return []
    issues = []
    texts = _extract_content_strings(campaign.get("campaign_content", {}))
    for text in texts:
        # Walk the string tracking {{ / }} as a stack so we find the exact
        # position of a genuinely unmatched brace, rather than just comparing
        # total counts (which flags huge HTML blobs with no real problem,
        # and reports an unhelpful snippet from the start of the string).
        open_positions = []
        unmatched_positions = []
        for m in re.finditer(r"\{\{|\}\}", text):
            if m.group() == "{{":
                open_positions.append(m.start())
            else:
                if open_positions:
                    open_positions.pop()
                else:
                    unmatched_positions.append(m.start())  # stray closing }}
        unmatched_positions.extend(open_positions)  # any {{ never closed

        for pos in sorted(set(unmatched_positions)):
            start = max(0, pos - 25)
            end = min(len(text), pos + 25)
            snippet = text[start:end].replace("\n", " ").strip()
            issues.append(f"Possible malformed personalization tag near: '...{snippet}...'")
    return issues


def check_links(campaign, rules):
    if not rules["link_check"]["enabled"]:
        return []
    issues = []
    texts = _extract_content_strings(campaign.get("campaign_content", {}))
    url_pattern = re.compile(r'https?://[^\s"\'<>)]+')
    urls = set()
    for text in texts:
        urls.update(url_pattern.findall(text))

    timeout = rules["link_check"]["timeout_seconds"]
    flag_above = rules["link_check"]["flag_status_codes_above"]
    for url in urls:
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            if r.status_code > flag_above:
                issues.append(f"Link returned status {r.status_code}: {url}")
        except requests.RequestException as e:
            issues.append(f"Link unreachable ({e.__class__.__name__}): {url}")
    return issues


def check_compliance_footer(campaign, rules):
    cfg = rules["compliance_footer"]
    if not cfg["enabled"]:
        return []
    if campaign.get("channel") not in cfg["applies_to_channels"]:
        return []
    texts = _extract_content_strings(campaign.get("campaign_content", {}))
    combined = " ".join(texts).lower()
    if not any(phrase in combined for phrase in cfg["required_any_of"]):
        return ["Email content is missing an unsubscribe / manage-preferences footer."]
    return []


def check_schedule_sanity(campaign, rules):
    cfg = rules["schedule_sanity"]
    if not cfg["enabled"]:
        return []
    issues = []
    sched = campaign.get("scheduling_details", {}) or {}
    start_time = sched.get("start_time")
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if cfg["flag_if_start_time_in_past"] and start_dt < now:
                issues.append(f"Scheduled start_time {start_time} is in the past.")
            hour_cfg = cfg["flag_send_hour_outside_range"]
            if hour_cfg["enabled"]:
                if not (hour_cfg["start_hour_utc"] <= start_dt.hour <= hour_cfg["end_hour_utc"]):
                    issues.append(
                        f"Send hour {start_dt.hour}:00 UTC is outside the approved "
                        f"window ({hour_cfg['start_hour_utc']}:00-{hour_cfg['end_hour_utc']}:00 UTC)."
                    )
        except ValueError:
            issues.append(f"Could not parse start_time: {start_time}")
    return issues


def check_segment_sanity(campaign, rules):
    cfg = rules["segment_sanity"]
    if not cfg["enabled"]:
        return []
    issues = []
    seg = campaign.get("segmentation_details", {}) or {}
    tags = campaign.get("basic_details", {}).get("tags", []) or []
    is_all_user = seg.get("is_all_user_campaign")

    if is_all_user and cfg["flag_if_all_user_campaign_without_tag"] not in tags:
        issues.append(
            "Campaign targets ALL users but is missing the "
            f"'{cfg['flag_if_all_user_campaign_without_tag']}' approval tag."
        )

    if cfg.get("flag_if_no_included_filters") and not is_all_user:
        included = (seg.get("included_filters") or {}).get("filters", [])
        if not included:
            issues.append(
                "Campaign is not marked as an all-user campaign but has zero "
                "included audience filters - check targeting, this may send to nobody."
            )
    return issues


_CLM_NAME_SEGMENTS_RE = re.compile(r"^CLM_([A-Za-z0-9]+)_(.+?)_(push|emailer|sms)_", re.IGNORECASE)


def _extract_clm_name_segments(name):
    """Pulls the <creativename> and <cohortname> segments out of a
    Standard/CLM-prefix campaign name (CLM_<creative>_<cohort>_<channel>_<date>).
    Returns (creative, cohort) or (None, None) if the name doesn't match
    that pattern (naming_convention check already flags that separately)."""
    m = _CLM_NAME_SEGMENTS_RE.match(name or "")
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _normalize_tag_text(s):
    """Lowercase, alphanumeric-only - lets 'Fully Loaded Double Rice' match
    'FullyLoadedDoubleRice' (spaces vs camelCase vs underscores are all
    just formatting, not a real difference in what the tag/segment means)."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _texts_fuzzy_match(a, b):
    """True if two already-_normalize_tag_text'd strings refer to the same
    thing. Tries substring containment first (the common, stricter case -
    e.g. name segment 'COCKTAILEDIT' vs tag 'Cocktail Edit'), then falls
    back to same-letters-any-order (e.g. name segment 'TRUNKSHOWBellevue'
    vs tag 'Bellevue Trunk show' - real HOAD data where the tag reorders
    the words compared to the name). The anagram fallback is intentionally
    looser, but for creative/cohort-length strings a same-letter-multiset
    coincidence between two genuinely different names is vanishingly
    unlikely, and it's a better trade-off than false-failing legitimate
    campaigns over word order."""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return sorted(a) == sorted(b)


def _get_client_channel_rules(rules, campaign):
    """Looks up rules.client_channel_rules[<client_key>][<channel>] for the
    campaign currently being checked. Returns {} if there's no override
    configured for this client+channel yet (e.g. HOAD/WESTSIDE PUSH before
    their standards are added) so every check below that reads from this
    cleanly no-ops instead of erroring."""
    client_key = rules.get("client_key")
    channel = campaign.get("channel")
    if not client_key or not channel:
        return {}
    return ((rules.get("client_channel_rules", {}) or {}).get(client_key, {}) or {}).get(channel, {}) or {}


def check_tags(campaign, rules):
    cfg = rules["tags_check"]
    if not cfg["enabled"]:
        return []
    tags = campaign.get("basic_details", {}).get("tags", []) or []

    ccr = _get_client_channel_rules(rules, campaign)

    if ccr.get("tags_must_match_name_segments"):
        # MoEngage's tag categories (e.g. "cohort", "creative") aren't in the
        # campaign API response - only the flat tag text is. So instead of
        # looking for a literal 'cohort'/'creative' word in the tags (which
        # real campaigns don't have - the tag IS the cohort/creative name,
        # e.g. tag "High_frequency_shoppers" for the cohort category), this
        # derives the expected creative/cohort names from the campaign name
        # itself (CLM_<creative>_<cohort>_<channel>_<date>) and checks each
        # one shows up as a tag.
        creative, cohort = _extract_clm_name_segments(campaign.get("basic_details", {}).get("name", ""))
        if creative is None:
            return []  # unparseable name - check_naming_convention already flags this
        normalized_tags = [_normalize_tag_text(t) for t in tags]
        issues = []
        for label, segment in (("creative", creative), ("cohort", cohort)):
            norm_segment = _normalize_tag_text(segment)
            if not any(_texts_fuzzy_match(norm_segment, nt) for nt in normalized_tags if nt):
                issues.append(
                    f"No tag found matching the {label} name '{segment}' from the campaign name "
                    f"(found tags: {tags or 'none'}) - expected a {label}-category tag."
                )
        return issues

    named_cfg = ccr.get("tags_must_match_named_segments")
    if named_cfg:
        # More general version of the above: some clients' naming convention
        # (e.g. HOAD's ADH_<Brand>_<Creative>_<Account>_OMNI_<Channel>_WK<week>_<date>)
        # encodes several distinct pieces, only some of which need a matching
        # tag (e.g. campaign-type and week, not brand/account). name_regex's
        # capture groups map to tag_segments by 1-based group index; each
        # segment's expected tag text is either the captured text as-is, put
        # through a value_map (e.g. "ADH" -> "Adhoc"), or a template (e.g.
        # "WK{}" for a week number captured as just digits).
        name = campaign.get("basic_details", {}).get("name", "")
        m = re.match(named_cfg["name_regex"], name, re.IGNORECASE)
        if not m:
            return []  # unparseable name - check_naming_convention already flags this
        normalized_tags = [_normalize_tag_text(t) for t in tags]
        issues = []
        matched_tag_indexes = set()
        for seg in named_cfg.get("tag_segments", []):
            group_text = m.group(seg["group"])
            if group_text is None:
                continue
            if "value_map" in seg:
                expected = next(
                    (v for k, v in seg["value_map"].items() if k.lower() == group_text.lower()),
                    group_text,
                )
            elif "template" in seg:
                expected = seg["template"].format(group_text)
            else:
                expected = group_text
            norm_expected = _normalize_tag_text(expected)
            match_idx = next(
                (i for i, nt in enumerate(normalized_tags) if nt and _texts_fuzzy_match(norm_expected, nt)),
                None,
            )
            if match_idx is None:
                label = seg.get("label", f"segment {seg['group']}")
                issues.append(
                    f"No tag found matching the {label} ('{expected}') from the campaign name "
                    f"(found tags: {tags or 'none'})."
                )
            else:
                matched_tag_indexes.add(match_idx)

        if named_cfg.get("require_extra_unmatched_tag"):
            # For categories with no name-derivable expected value (e.g.
            # Cohort, where the tag text doesn't resemble the name's cohort
            # segment at all - see HOAD/ANDGD naming notes), the best this
            # tool can check without a false-positive risk is presence: is
            # there at least one tag beyond the ones already matched above?
            unmatched_count = len(tags) - len(matched_tag_indexes)
            if unmatched_count < 1:
                issues.append(
                    "No additional tag found beyond campaign type/brand/creative/channel/week "
                    f"(found tags: {tags or 'none'}) - expected at least one more tag (e.g. for cohort)."
                )
        return issues

    required_contains = ccr.get("required_tags_contains")
    if required_contains:
        tags_lower = [str(t).lower() for t in tags]
        issues = []
        for keyword in required_contains:
            if not any(keyword.lower() in t for t in tags_lower):
                issues.append(
                    f"Missing a required tag referencing '{keyword}' "
                    f"(found tags: {tags or 'none'})."
                )
        return issues

    if len(tags) < cfg.get("min_tags", 1):
        return [f"Campaign has no tags (found {len(tags)}, expected at least {cfg.get('min_tags', 1)})."]
    return []


_PLACEHOLDER_PHRASES = ("lorem ipsum", "test test", "{{name}} {{name}}", "todo:", "xxx", "sample text")


def _looks_like_placeholder(text):
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _PLACEHOLDER_PHRASES)


def _has_field_anywhere(obj, keywords):
    """Best-effort recursive search: True if any dict key (at any depth)
    contains one of the keywords (case-insensitive) and holds a truthy
    value. Used for fields like "default click action" where the exact
    schema path isn't confirmed - matches on key name instead of an exact
    path so it still works across minor schema differences."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(kw in k.lower() for kw in keywords) and v:
                return True
            if _has_field_anywhere(v, keywords):
                return True
    elif isinstance(obj, list):
        return any(_has_field_anywhere(item, keywords) for item in obj)
    return False


def _check_push_content(campaign, cfg, ccr=None):
    """Push: goes beyond "is title/message empty" to check per-platform
    length limits (platforms truncate/clip long push copy differently),
    title/message not being duplicates of each other, placeholder text,
    that the platforms configured for this account are all present, and
    (per client_channel_rules override) that a default click action is set.
    `ccr` is this campaign's client_channel_rules block (e.g.
    client_channel_rules.KFC.PUSH), if any - its `content.push` settings
    override the generic `content_check.push` defaults below."""
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}
    push = content_root.get("push", {}) or {}
    issues = []
    push_cfg = dict(cfg.get("push", {}))
    push_cfg.update(((ccr or {}).get("content", {}) or {}).get("push", {}) or {})
    max_title = push_cfg.get("max_title_length", 65)
    max_message = push_cfg.get("max_message_length", 178)
    expected_platforms = push_cfg.get("expected_platforms", [])
    require_click_action = push_cfg.get("require_default_click_action", False)

    if not push:
        issues.append("No push content found for any platform.")
        return issues

    for platform, plat_data in push.items():
        basic = (plat_data or {}).get("basic_details", {}) or {}
        title = (basic.get("title") or "").strip()
        message = (basic.get("message") or "").strip()

        if not title:
            issues.append(f"[{platform}] push title is empty.")
        elif len(title) > max_title:
            issues.append(
                f"[{platform}] push title is {len(title)} chars, over the {max_title}-char "
                f"guideline - it may get truncated on device."
            )
        if not message:
            issues.append(f"[{platform}] push message is empty.")
        elif len(message) > max_message:
            issues.append(
                f"[{platform}] push message is {len(message)} chars, over the {max_message}-char "
                f"guideline - it may get truncated on device."
            )
        if title and message and title.strip().lower() == message.strip().lower():
            issues.append(f"[{platform}] push title and message are identical - likely a copy/paste mistake.")
        if _looks_like_placeholder(title) or _looks_like_placeholder(message):
            issues.append(f"[{platform}] push content looks like placeholder/test copy, not final content.")
        if require_click_action and not _has_field_anywhere(
            plat_data, ["click_action", "default_action", "redirect", "deep_link", "landing"]
        ):
            issues.append(
                f"[{platform}] no default click action / redirection found - push should have "
                f"where-to-go-on-tap configured."
            )

    missing_platforms = [p for p in expected_platforms if p not in push]
    if missing_platforms:
        issues.append(
            f"Push content is missing for platform(s): {', '.join(missing_platforms)} "
            f"- users on those platforms won't receive this push."
        )
    return issues


def _check_email_content(campaign, cfg, ccr=None):
    """Email: goes beyond "is subject/sender/etc empty" to check subject
    length (too short reads as spammy, too long gets clipped in the inbox
    list), preview text not just repeating the subject, sender/reply-to
    being valid email addresses, from_address domain matching an approved
    list (if configured), sender_name/reply-to matching a client's standard
    (if configured via `ccr`), and placeholder copy left in the HTML."""
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}
    email = content_root.get("email", {}) or {}
    issues = []
    email_cfg = dict(cfg.get("email", {}))
    email_cfg.update(((ccr or {}).get("content", {}) or {}).get("email", {}) or {})
    min_subject = email_cfg.get("min_subject_length", 10)
    max_subject = email_cfg.get("max_subject_length", 150)
    approved_domains = email_cfg.get("approved_from_domains", [])
    required_sender_name = email_cfg.get("sender_name_required")
    reply_to_must_equal_from = email_cfg.get("reply_to_must_equal_from", False)
    email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    if not email:
        issues.append("No email content block found.")
        return issues

    subject = (email.get("subject") or "").strip()
    preview_text = (email.get("preview_text") or "").strip()
    sender_name = (email.get("sender_name") or "").strip()
    from_address = (email.get("from_address") or "").strip()
    reply_to_address = (email.get("reply_to_address") or "").strip()
    html_content = (email.get("html_content") or "").strip()

    if not subject:
        issues.append("Email subject line is empty.")
    elif len(subject) < min_subject:
        issues.append(f"Email subject is only {len(subject)} chars - unusually short, check it's meaningful.")
    elif len(subject) > max_subject:
        issues.append(f"Email subject is {len(subject)} chars, over the {max_subject}-char guideline - it may get clipped in inbox previews.")

    if not preview_text:
        issues.append("Email preview text is empty.")
    elif subject and preview_text.strip().lower() == subject.strip().lower():
        issues.append("Email preview text is identical to the subject line - it's wasting valuable inbox preview space.")

    if not sender_name:
        issues.append("Email sender name is empty.")
    elif required_sender_name and sender_name != required_sender_name:
        issues.append(
            f"Email sender name is '{sender_name}', expected '{required_sender_name}' per this "
            "client/channel's standard setup."
        )
    if not from_address:
        issues.append("Email from_address is empty.")
    elif not email_re.match(from_address):
        issues.append(f"Email from_address '{from_address}' doesn't look like a valid email address.")
    elif approved_domains and from_address.split("@")[-1].lower() not in [d.lower() for d in approved_domains]:
        issues.append(
            f"Email from_address domain '{from_address.split('@')[-1]}' isn't in the approved "
            f"sender domain list ({', '.join(approved_domains)})."
        )

    if not reply_to_address:
        issues.append("Email reply_to_address is empty.")
    elif not email_re.match(reply_to_address):
        issues.append(f"Email reply_to_address '{reply_to_address}' doesn't look like a valid email address.")
    elif reply_to_must_equal_from and from_address and reply_to_address.lower() != from_address.lower():
        issues.append(
            f"Email reply_to_address '{reply_to_address}' doesn't match from_address "
            f"'{from_address}' - this client/channel's standard expects them to be the same."
        )

    if len(html_content) < cfg.get("min_total_content_length", 200):
        issues.append(
            f"Email html_content looks unusually short/empty "
            f"({len(html_content)} chars, expected at least {cfg.get('min_total_content_length', 200)})."
        )
    elif _looks_like_placeholder(html_content):
        issues.append("Email html_content looks like it still contains placeholder/test copy.")
    return issues


_TEMPLATE_SYNTAX_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def _check_sms_content(campaign, cfg, ccr=None):
    """SMS: goes beyond "is there some text" to check actual SMS segment
    math (GSM-7 single-segment is 160 chars, each additional concatenated
    segment is 153 chars - going one char over silently costs a second
    segment, i.e. doubles the send cost) and flags placeholder copy.

    Skips the segment-length math specifically when the message uses
    MoEngage's Jinja-style personalization ({% if %}...{% endif %},
    {{ variable }}): the *stored* message concatenates every branch's text
    (e.g. one branch per store-lookup outcome), which can run to 10+x the
    length of whatever single branch actually renders and sends - so
    comparing the raw stored length against the 160-char limit would be
    comparing the wrong number entirely, not a real finding."""
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}
    node = content_root.get("sms") or content_root
    texts = _extract_content_strings(node)
    combined = " ".join(t.strip() for t in texts if t.strip())
    issues = []
    sms_cfg = cfg.get("sms", {})
    single_segment_len = sms_cfg.get("single_segment_length", 160)
    concat_segment_len = sms_cfg.get("concatenated_segment_length", 153)
    min_len = cfg.get("min_total_content_length_by_channel", {}).get("SMS", 10)

    if len(combined) < min_len:
        issues.append(f"SMS content looks unusually short or empty ({len(combined)} chars).")
        return issues

    if _looks_like_placeholder(combined):
        issues.append("SMS content looks like placeholder/test copy, not final content.")

    has_template_syntax = bool(_TEMPLATE_SYNTAX_RE.search(combined))
    if len(combined) > single_segment_len and not has_template_syntax:
        segments = 1 + -(-(len(combined) - single_segment_len) // concat_segment_len)  # ceil division
        issues.append(
            f"SMS message is {len(combined)} chars, over the {single_segment_len}-char single-segment "
            f"limit - it will send as {segments} concatenated segments (multiplies delivery cost)."
        )
    return issues


def _check_whatsapp_content(campaign, cfg, ccr=None):
    """WhatsApp: goes beyond "is there some text" to flag placeholder copy
    and (best-effort, since a confirmed WhatsApp content payload sample
    wasn't available when this was written) look for an approved template
    name/category if the campaign content includes one - adjust the field
    names in this function if your account's payload shape differs."""
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}
    node = content_root.get("whatsapp") or content_root
    texts = _extract_content_strings(node)
    combined = " ".join(t.strip() for t in texts if t.strip())
    issues = []
    min_len = cfg.get("min_total_content_length_by_channel", {}).get("WHATSAPP", 10)

    if len(combined) < min_len:
        issues.append(f"WhatsApp content looks unusually short or empty ({len(combined)} chars).")
        return issues

    if _looks_like_placeholder(combined):
        issues.append("WhatsApp content looks like placeholder/test copy, not final content.")

    template_name = None
    if isinstance(node, dict):
        template_name = node.get("template_name") or node.get("templateName")
    if cfg.get("whatsapp", {}).get("require_template_name") and not template_name:
        issues.append(
            "No WhatsApp template_name found on the content block - if this account requires "
            "pre-approved templates, confirm this campaign is actually using one."
        )
    return issues


_CHANNEL_CONTENT_CHECKS = {
    "PUSH": _check_push_content,
    "EMAIL": _check_email_content,
    "SMS": _check_sms_content,
    "WHATSAPP": _check_whatsapp_content,
}


def check_content_completeness(campaign, rules):
    cfg = rules["content_check"]
    if not cfg["enabled"]:
        return []
    channel = campaign.get("channel")
    if channel not in cfg.get("applies_to_channels", []):
        return []

    ccr = _get_client_channel_rules(rules, campaign)
    check_fn = _CHANNEL_CONTENT_CHECKS.get(channel)
    if check_fn:
        return check_fn(campaign, cfg, ccr)

    # Generic fallback for any other/unrecognized channel - checks there's a
    # reasonable amount of text rather than nothing at all.
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}
    channel_key = channel.lower()
    node = content_root.get(channel_key) or content_root
    texts = _extract_content_strings(node)
    total_len = sum(len(t.strip()) for t in texts)
    min_len = cfg.get("min_total_content_length_by_channel", {}).get(
        channel, cfg.get("min_total_content_length", 200)
    )
    if total_len < min_len:
        return [
            f"Content for {channel} looks unusually short or empty "
            f"(extracted {total_len} chars, expected at least {min_len})."
        ]
    return []


def check_control_group(campaign, rules):
    cfg = rules["control_group_check"]
    if not cfg["enabled"]:
        return []
    ccr = _get_client_channel_rules(rules, campaign)
    if "control_group" in ccr:
        # This client/channel has its own explicit control-group standard
        # (client_channel_rules.<CLIENT>.<CHANNEL>.control_group, checked
        # in check_client_channel_rules) - e.g. HOAD_IND's standard is
        # global control group OFF, so the generic "no control group at
        # all" blanket flag below would just be noise on every legitimate
        # HOAD_IND campaign. Defer entirely to the specific check instead.
        return []
    cg = campaign.get("control_group_details", {}) or {}
    issues = []
    global_enabled = cg.get("is_global_control_group_enabled", False)
    campaign_enabled = cg.get("is_campaign_control_group_enabled", False)
    campaign_pct = cg.get("campaign_control_group_percentage", 0) or 0

    if cfg.get("flag_if_no_control_group") and not global_enabled and not campaign_enabled:
        issues.append(
            "Neither global nor campaign-level control group is enabled - "
            "no way to measure this campaign's incremental impact."
        )
    if campaign_enabled and campaign_pct <= 0:
        issues.append("Campaign-level control group is enabled but percentage is 0.")
    return issues


def check_conversion_goals(campaign, rules):
    """Verifies the standard conversion goals rather than just "is something
    configured". This is scoped per client via
    conversion_goal_check.standard_goals_by_client (keyed by client key,
    e.g. "KFC") since the 3 standard goals are a KFC-specific convention,
    not necessarily shared by every client on this tool. For a client with
    no entry there yet (or when no client is selected at all, e.g. the
    original single-account CLI usage), this falls back to the flat
    `standard_goals` list if set, and finally to the original
    presence-only checks (require_at_least_one_goal /
    require_exactly_one_primary_goal) if neither is configured."""
    cfg = rules["conversion_goal_check"]
    if not cfg["enabled"]:
        return []
    goals = (campaign.get("conversion_goal_details", {}) or {}).get("goals", []) or []
    issues = []

    client_key = rules.get("client_key")
    standard_goals = (cfg.get("standard_goals_by_client", {}) or {}).get(client_key)
    if standard_goals is None:
        standard_goals = cfg.get("standard_goals") or []

    if not standard_goals:
        # No standard goal list configured for this client yet - fall back
        # to the original presence-only checks.
        if cfg.get("require_at_least_one_goal") and not goals:
            issues.append("No conversion goals configured for this campaign.")
        if cfg.get("require_exactly_one_primary_goal") and goals:
            primary_count = sum(1 for g in goals if g.get("is_primary_goal"))
            if primary_count == 0:
                issues.append("No conversion goal is marked as primary (need exactly one).")
            elif primary_count > 1:
                issues.append(f"{primary_count} conversion goals are marked primary - should be exactly one.")
        return issues

    if not goals:
        expected_events = ", ".join(g["goal_event_name"] for g in standard_goals)
        issues.append(
            f"No conversion goals configured - expected the {len(standard_goals)} standard "
            f"goals ({expected_events})."
        )
        return issues

    by_event = {}
    for g in goals:
        by_event.setdefault(g.get("goal_event_name"), []).append(g)

    for expected in standard_goals:
        event_name = expected["goal_event_name"]
        matches = by_event.get(event_name, [])

        if not matches:
            issues.append(
                f"Missing standard conversion goal for event '{event_name}' "
                f"(expected: {expected.get('goal_name', event_name)})."
            )
            continue

        if len(matches) > 1:
            issues.append(
                f"Standard conversion goal for event '{event_name}' is configured "
                f"{len(matches)} times - should appear exactly once."
            )

        goal = matches[0]
        is_primary = bool(goal.get("is_primary_goal"))
        should_be_primary = bool(expected.get("must_be_primary"))

        if should_be_primary and not is_primary:
            issues.append(
                f"Conversion goal '{event_name}' should be the primary goal but isn't marked primary."
            )
        if is_primary and not should_be_primary:
            issues.append(
                f"Conversion goal '{event_name}' is marked primary, but per the standard "
                f"setup only '{next((g['goal_event_name'] for g in standard_goals if g.get('must_be_primary')), '')}' should be."
            )

        if expected.get("require_revenue_tracking") and is_primary:
            if not (goal.get("revenue_attribute") or "").strip():
                issues.append(f"Primary conversion goal '{event_name}' is missing revenue_attribute.")
            if not (goal.get("revenue_currency") or "").strip():
                issues.append(f"Primary conversion goal '{event_name}' is missing revenue_currency.")
            expected_currency = expected.get("revenue_currency")
            actual_currency = (goal.get("revenue_currency") or "").strip()
            if expected_currency and actual_currency and actual_currency.upper() != expected_currency.upper():
                issues.append(
                    f"Primary conversion goal '{event_name}' revenue_currency is '{actual_currency}', "
                    f"expected '{expected_currency}' for this client."
                )

    primary_count = sum(1 for g in goals if g.get("is_primary_goal"))
    if primary_count == 0:
        issues.append("No conversion goal is marked as primary (need exactly one).")
    elif primary_count > 1:
        issues.append(f"{primary_count} conversion goals are marked primary - should be exactly one.")

    if cfg.get("flag_extra_goals"):
        expected_events = {g["goal_event_name"] for g in standard_goals}
        extra = [g.get("goal_event_name") for g in goals if g.get("goal_event_name") not in expected_events]
        if extra:
            issues.append(f"Campaign has extra, non-standard conversion goal(s): {', '.join(extra)}.")

    return issues


def check_delivery_controls(campaign, rules):
    cfg = rules["delivery_controls_check"]
    if not cfg["enabled"]:
        return []
    dc = campaign.get("delivery_controls", {}) or {}
    issues = []

    if cfg.get("flag_if_ignore_frequency_capping") and dc.get("ignore_frequency_capping"):
        issues.append("Campaign is set to ignore frequency capping - may over-message users.")
    if cfg.get("flag_if_throttle_rpm_zero") and not dc.get("campaign_throttle_rpm"):
        issues.append("Campaign throttle (campaign_throttle_rpm) is 0 or unset.")
    if cfg.get("flag_if_bypass_dnd") and dc.get("bypass_dnd"):
        issues.append("Campaign is set to bypass Do-Not-Disturb hours (bypass_dnd=true).")
    return issues


def _has_any_filter_type(filters, filter_type):
    """Recursively searches a segmentation filters list (which can nest
    arbitrarily via filter_type == 'nested_filters') for any filter whose
    own filter_type matches. Used for clients like HOAD where the QA
    standard is just "was some segment-based exclusion added at all" -
    the exact segment/exclusion logic itself varies per campaign and isn't
    something this tool should be locking in as a fixed requirement."""
    for f in filters or []:
        if f.get("filter_type") == filter_type:
            return True
        nested = f.get("filters")
        if nested and _has_any_filter_type(nested, filter_type):
            return True
    return False


def _filter_matches(filters, name_keywords, expected_values=None, values_must_be_subset=False):
    """Best-effort search through a segmentation_details filters list for one
    matching a set of keywords (case-insensitive substring match against
    the filter's `name` + `category` combined - e.g. the real Reachability
    exclusion filters are named 'moe_rsp_android'/'moe_rsp_ios' with
    category 'Reachability', so a keyword like 'reach' only matches via the
    category, not the name), optionally also checking its `value` list
    contains (or is a superset of) expected_values."""
    for f in filters:
        haystack = f"{f.get('name', '')} {f.get('category', '')}".lower()
        if not all(kw in haystack for kw in name_keywords):
            continue
        if expected_values is None:
            return True
        actual_values = {str(v) for v in (f.get("value") or [])}
        expected = {str(v) for v in expected_values}
        if values_must_be_subset:
            if expected.issubset(actual_values):
                return True
        elif expected & actual_values:
            return True
    return False


def check_client_channel_rules(campaign, rules):
    """The client- and channel-specific standards layer: everything that's
    common across a client's campaigns for one channel (e.g. every KFC PUSH
    campaign needs the same exclude-user filters, control group setup,
    delivery throttle, and conversion-goal tracking window) rather than a
    generic present/not-present check. No-ops entirely if there's no
    client_channel_rules entry for this campaign's client+channel yet (see
    _get_client_channel_rules) - tags/content-specific pieces of this same
    config are applied inside check_tags / check_content_completeness."""
    ccr = _get_client_channel_rules(rules, campaign)
    if not ccr:
        return []
    issues = []

    ef_cfg = ccr.get("exclude_filters")
    if ef_cfg and ef_cfg.get("required"):
        excluded = (campaign.get("segmentation_details", {}) or {}).get("excluded_filters", {}) or {}
        filters = excluded.get("filters", []) or []

        if not filters:
            issues.append(
                "No exclude-user filters configured - this client/channel's standard setup "
                "requires at least one exclusion to be added."
            )
        else:
            country = ef_cfg.get("must_exclude_country")
            if country and not _filter_matches(filters, ["country"], [country]):
                issues.append(f"Exclude filters are missing the standard '{country}' country exclusion.")

            android_codes = ef_cfg.get("must_exclude_reachability_android_codes")
            if android_codes and not _filter_matches(
                filters, ["reach", "android"], android_codes, values_must_be_subset=True
            ):
                issues.append(
                    "Exclude filters are missing the standard Push Android reachability exclusion codes "
                    f"({android_codes})."
                )

            ios_codes = ef_cfg.get("must_exclude_reachability_ios_codes")
            if ios_codes and not _filter_matches(
                filters, ["reach", "ios"], ios_codes, values_must_be_subset=True
            ):
                issues.append(
                    "Exclude filters are missing the standard Push iOS reachability exclusion codes "
                    f"({ios_codes})."
                )

            expected_op = ef_cfg.get("filter_operator_required")
            actual_op = str(excluded.get("filter_operator", "")).lower()
            if expected_op and actual_op != expected_op.lower():
                issues.append(
                    f"Exclude filters are combined with '{actual_op or 'unset'}', expected "
                    f"'{expected_op}' (per the standard AND/OR setup for this client/channel)."
                )

            segment_name = ef_cfg.get("must_exclude_custom_segment")
            if segment_name and not any(
                f.get("filter_type") == "custom_segments"
                and str(f.get("name", "")).strip().lower() == segment_name.strip().lower()
                for f in filters
            ):
                issues.append(f"Exclude filters are missing the standard '{segment_name}' segment exclusion.")

            if ef_cfg.get("must_exclude_unsubscribed") and not any(
                "unsubscribe" in str(f.get("name", "")).lower() and f.get("value") is True
                for f in filters
            ):
                issues.append("Exclude filters are missing the standard unsubscribed-users exclusion.")

            if ef_cfg.get("must_have_custom_segment_exclusion") and not _has_any_filter_type(
                filters, "custom_segments"
            ):
                issues.append(
                    "No segment-based exclusion found in exclude filters - expected at least one "
                    "exclusion segment added (the specific segment/exclusion logic itself varies "
                    "per campaign, so only presence is checked)."
                )

    connector_cfg = ccr.get("connector")
    if connector_cfg:
        # Connector shape differs by channel: Email returns a dict
        # ({"connector_type": "SENDGRID", "connector_name": "..."}); SMS
        # returns a plain string (the connector's name, e.g.
        # "Dove_Soft_GLDESI_Promo"). Handle both rather than assuming dict.
        raw_connector = campaign.get("connector")
        if isinstance(raw_connector, dict):
            connector_value = raw_connector.get("connector_type")
            connector_present = bool(raw_connector)
        elif isinstance(raw_connector, str):
            connector_value = raw_connector
            connector_present = bool(raw_connector.strip())
        else:
            connector_value = None
            connector_present = False

        if connector_cfg.get("type_required"):
            if connector_value != connector_cfg["type_required"]:
                issues.append(
                    f"Connector is '{connector_value}', expected '{connector_cfg['type_required']}' per "
                    "this client/channel's standard setup."
                )
        elif connector_cfg.get("required") and not connector_present:
            issues.append("No connector configured for this campaign - expected one to be set up.")

    cg_cfg = ccr.get("control_group")
    if cg_cfg and "global_required" in cg_cfg:
        expected_global = bool(cg_cfg["global_required"])
        cg = campaign.get("control_group_details", {}) or {}
        actual_global = bool(cg.get("is_global_control_group_enabled"))
        if actual_global != expected_global:
            issues.append(
                f"Global control group is {'enabled' if actual_global else 'disabled'}, expected "
                f"{'enabled' if expected_global else 'disabled'} per this client/channel's standard setup."
            )

    dc_cfg = ccr.get("delivery_controls")
    if dc_cfg:
        dc = campaign.get("delivery_controls", {}) or {}
        expected_rpm = dc_cfg.get("campaign_throttle_rpm_required")
        actual_rpm = dc.get("campaign_throttle_rpm")
        if expected_rpm is not None and actual_rpm != expected_rpm:
            issues.append(
                f"Request limit (campaign_throttle_rpm) is {actual_rpm}, expected {expected_rpm} "
                "requests/minute per this client/channel's standard setup."
            )
        expected_ifc = dc_cfg.get("ignore_frequency_capping_must_be")
        actual_ifc = bool(dc.get("ignore_frequency_capping"))
        if expected_ifc is not None and actual_ifc != expected_ifc:
            issues.append(
                f"'Ignore frequency capping' is {actual_ifc}, expected {expected_ifc} per this "
                "client/channel's standard setup."
            )
        expected_bypass = dc_cfg.get("bypass_dnd_must_be")
        actual_bypass = bool(dc.get("bypass_dnd"))
        if expected_bypass is not None and actual_bypass != expected_bypass:
            issues.append(
                f"'Bypass DND' is {actual_bypass}, expected {expected_bypass} per this "
                "client/channel's standard setup."
            )

    attr_hours = ccr.get("conversion_goal_attribution_hours_required")
    if attr_hours is not None:
        cgd = campaign.get("conversion_goal_details", {}) or {}
        actual_hours = cgd.get("attribution_window_in_hours")
        if actual_hours != attr_hours:
            issues.append(
                f"Conversion goal tracking window is {actual_hours} hour(s), expected "
                f"{attr_hours} hour(s) per this client/channel's standard setup."
            )

    plat_cfg = ccr.get("platforms")
    if plat_cfg and plat_cfg.get("required"):
        actual_platforms = {str(p).upper() for p in (campaign.get("basic_details", {}) or {}).get("platforms", []) or []}
        expected_platforms = {str(p).upper() for p in plat_cfg["required"]}
        missing = expected_platforms - actual_platforms
        if missing:
            issues.append(
                f"Target Platforms is missing {', '.join(sorted(missing))} - expected "
                f"{', '.join(sorted(expected_platforms))} all checked."
            )

    plat_specific = (campaign.get("basic_details", {}) or {}).get("platform_specific_details", {}) or {}

    android_cfg = ccr.get("android_settings")
    if android_cfg:
        android_details = plat_specific.get("android", {}) or {}
        if android_cfg.get("huawei_mobile_services_delivery_required") is not None:
            expected = android_cfg["huawei_mobile_services_delivery_required"]
            actual = android_details.get("push_amp_plus_enabled")
            if bool(actual) != bool(expected):
                issues.append(
                    f"'Use Huawei Mobile Services delivery (Push amp+)' is {bool(actual)}, "
                    f"expected {bool(expected)} per this client/channel's standard setup."
                )

    ios_prov_cfg = ccr.get("ios_provisional_push")
    if ios_prov_cfg:
        ios_details = plat_specific.get("ios", {}) or {}
        field_map = {
            "send_to_all_eligible_device_required": "send_to_all_eligible_device",
            "exclude_provisional_push_devices_required": "exclude_provisional_push_devices",
            "send_to_only_provisional_push_enabled_devices_required": "send_to_only_provisional_push_enabled_devices",
        }
        mismatches = []
        for cfg_key, api_field in field_map.items():
            if cfg_key in ios_prov_cfg:
                expected = bool(ios_prov_cfg[cfg_key])
                actual = bool(ios_details.get(api_field))
                if actual != expected:
                    mismatches.append(f"{api_field}={actual} (expected {expected})")
        if mismatches:
            issues.append(
                "iOS provisional push setting doesn't match this client/channel's standard "
                f"('Opted-in devices' mode expected): {', '.join(mismatches)}."
            )

    adv_cfg = ccr.get("advanced")
    if adv_cfg:
        adv = campaign.get("advanced", {}) or {}
        exp_settings = adv.get("expiration_settings", {}) or {}
        priority_settings = adv.get("platform_level_priority", {}) or {}
        android_priority = priority_settings.get("android_specific_priority", {}) or {}
        ios_priority = priority_settings.get("ios_specific_priority", {}) or {}

        def _check_eq(label, actual, expected):
            if expected is not None and actual != expected:
                issues.append(f"{label} is {actual}, expected {expected} per this client/channel's standard setup.")

        _check_eq(
            "Expire notifications after",
            exp_settings.get("expire_notification_after_value"),
            adv_cfg.get("expire_notification_after_value_required"),
        )
        _check_eq(
            "Expire notifications after (unit)",
            exp_settings.get("expire_notification_after_type"),
            adv_cfg.get("expire_notification_after_type_required"),
        )
        _check_eq(
            "Remove notifications from inbox after",
            exp_settings.get("remove_from_inbox_after_value"),
            adv_cfg.get("remove_from_inbox_after_value_required"),
        )
        _check_eq(
            "Remove notifications from inbox after (unit)",
            exp_settings.get("remove_from_inbox_after_type"),
            adv_cfg.get("remove_from_inbox_after_type_required"),
        )
        _check_eq(
            "Android 'Send at priority'",
            android_priority.get("send_with_priority"),
            adv_cfg.get("android_send_with_priority_required"),
        )
        _check_eq(
            "APNS Priority",
            ios_priority.get("apns_priority"),
            adv_cfg.get("apns_priority_required"),
        )
        _check_eq(
            "Interruption Level",
            ios_priority.get("interruption_level"),
            adv_cfg.get("interruption_level_required"),
        )
        _check_eq(
            "Relevance Score",
            ios_priority.get("relevance_score"),
            adv_cfg.get("relevance_score_required"),
        )

    return issues


CHECKS = [
    check_naming_convention,
    check_tags,
    check_segment_sanity,
    check_content_completeness,
    check_control_group,
    check_conversion_goals,
    check_delivery_controls,
    check_client_channel_rules,
    check_utm_params,
    check_utm_mismatch,
    check_personalization_tokens,
    check_links,
    check_compliance_footer,
    check_schedule_sanity,
]

# Used for campaigns fetched via /campaigns/meta (see META_ONLY_CHANNELS,
# _fetch_campaigns_meta) - that endpoint only returns campaign_id, channel,
# status, name, tags, platform. Every other CHECKS entry reads fields that
# simply aren't in that response (content, targeting, control group,
# delivery controls, conversion goals, connector, schedule details), so
# running them would report false "missing X" issues for every campaign
# rather than a real finding. Only checks that work from name+tags alone
# run for these.
LIGHTWEIGHT_CHECKS = [
    check_naming_convention,
    check_tags,
]


def run_qa(campaign, rules):
    checks = LIGHTWEIGHT_CHECKS if campaign.get("_meta_only") else CHECKS
    issues = []
    for check_fn in checks:
        issues.extend(check_fn(campaign, rules))
    return issues


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def post_to_slack(webhook_url, results):
    if not webhook_url:
        return
    failed = [r for r in results if r["issues"]]
    if not failed:
        text = "✅ MoEngage Campaign QA: all checked campaigns passed."
    else:
        lines = [f"🚨 MoEngage Campaign QA found issues in {len(failed)} campaign(s):"]
        for r in failed:
            lines.append(f"\n*{r['name']}* ({r['campaign_id']}, {r['channel']})")
            for issue in r["issues"]:
                lines.append(f"  • {issue}")
        text = "\n".join(lines)
    try:
        requests.post(webhook_url, json={"text": text}, timeout=10)
    except requests.RequestException as e:
        print(f"Failed to post to Slack: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="MoEngage Campaign QA Agent")
    parser.add_argument(
        "--client", help="Client key from clients_config.json, e.g. KFC, HOAD, WESTSIDE. "
        "Omit to use the original single-account MOENGAGE_WORKSPACE_ID/MOENGAGE_API_KEY env vars."
    )
    parser.add_argument("--status", help="Filter by status, e.g. SCHEDULED, ACTIVE")
    parser.add_argument("--channel", help="Filter by channel, e.g. EMAIL, PUSH, SMS")
    parser.add_argument("--limit", type=int, default=15, help="Campaigns per page (max 15)")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--out", default="qa_report.json", help="Path to write JSON report")
    parser.add_argument(
        "--dump-raw",
        metavar="PATH",
        help="Instead of running QA, write the raw JSON of the first matching campaign "
        "(after --status/--channel/--client filters) to PATH and exit. Use this to grab a "
        "real campaign payload (e.g. one KFC PUSH campaign) so exact field paths for "
        "not-yet-verified checks can be confirmed - see the 'pending_verification' notes "
        "in qa_rules.json.",
    )
    args = parser.parse_args()

    config = load_config(client=args.client)
    try:
        campaigns = fetch_campaigns(
            config, status=args.status, channel=args.channel, limit=args.limit, page=args.page
        )
    except RuntimeError as e:
        sys.exit(str(e))

    if args.dump_raw:
        if not campaigns:
            sys.exit("No campaigns matched those filters - nothing to dump.")
        first = campaigns[0]
        to_dump = first.get("_raw_meta", first) if first.get("_meta_only") else first
        with open(args.dump_raw, "w") as f:
            json.dump(to_dump, f, indent=2)
        note = " (from /campaigns/meta - limited fields only)" if first.get("_meta_only") else ""
        print(f"Wrote raw JSON for campaign '{first.get('campaign_id')}' to {args.dump_raw}{note}")
        return

    results = []
    for campaign in campaigns:
        issues = run_qa(campaign, config)
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

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    passed = sum(1 for r in results if not r["issues"])
    failed = sum(1 for r in results if r["issues"])
    print(f"Checked {len(results)} campaign(s): {passed} passed, {failed} flagged.")
    for r in results:
        if r["issues"]:
            print(f"\n[FAIL] {r['name']} ({r['campaign_id']}, {r['channel']})")
            for issue in r["issues"]:
                print(f"   - {issue}")

    post_to_slack(config.get("slack_webhook_url"), results)


if __name__ == "__main__":
    main()
