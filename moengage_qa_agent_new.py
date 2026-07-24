#!/usr/bin/env python3
"""
MoEngage Campaign QA Agent
---------------------------
Pulls campaigns from MoEngage (via the Search Campaigns API) and runs a set
of pre-launch quality checks against them: naming convention, UTM params,
personalization token sanity, broken links, compliance footer (email),
schedule sanity, and segment sanity.

Results are printed to stdout, written to a JSON report, and optionally
posted to Slack via an incoming webhook.

Docs referenced:
  https://www.moengage.com/docs/api/get-campaign-details/search-campaigns
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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

CONFIG_PATH = Path(__file__).parent / "qa_rules.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

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
            "and MOENGAGE_API_KEY as environment variables, or fill them in "
            "qa_rules.json."
        )
    return config


# ---------------------------------------------------------------------------
# MoEngage API
# ---------------------------------------------------------------------------

def fetch_campaigns(config, status=None, channel=None, limit=15, page=1):
    """Calls POST /campaigns/search and returns the list of campaigns."""
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

    resp = requests.post(url, headers=headers, json=body, timeout=15)
    if resp.status_code != 200:
        print(f"MoEngage API error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Individual checks. Each returns a list of issue strings (empty = pass).
# ---------------------------------------------------------------------------

def check_naming_convention(campaign, rules):
    cfg = rules["naming_convention"]
    if not cfg["enabled"]:
        return []
    name = campaign.get("basic_details", {}).get("name", "")
    pattern = cfg["regex"]
    flags = re.IGNORECASE if cfg.get("regex_flags") == "IGNORECASE" else 0
    if not re.match(pattern, name, flags):
        example = cfg.get("example_push", cfg.get("example", ""))
        return [f"Name '{name}' doesn't match naming convention. Expected format like: {example}"]
    return []


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


def check_tags(campaign, rules):
    cfg = rules["tags_check"]
    if not cfg["enabled"]:
        return []
    tags = campaign.get("basic_details", {}).get("tags", []) or []
    if len(tags) < cfg.get("min_tags", 1):
        return [f"Campaign has no tags (found {len(tags)}, expected at least {cfg.get('min_tags', 1)})."]
    return []


def check_content_completeness(campaign, rules):
    cfg = rules["content_check"]
    if not cfg["enabled"]:
        return []
    channel = campaign.get("channel")
    if channel not in cfg.get("applies_to_channels", []):
        return []

    issues = []
    content_root = (campaign.get("campaign_content", {}) or {}).get("content", {}) or {}

    if channel == "PUSH":
        push = content_root.get("push", {}) or {}
        if not push:
            issues.append("No push content found for any platform.")
        for platform, plat_data in push.items():
            basic = (plat_data or {}).get("basic_details", {}) or {}
            title = (basic.get("title") or "").strip()
            message = (basic.get("message") or "").strip()
            if not title:
                issues.append(f"[{platform}] push title is empty.")
            if not message:
                issues.append(f"[{platform}] push message is empty.")
    elif channel == "EMAIL":
        email = content_root.get("email", {}) or {}
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
        if not preview_text:
            issues.append("Email preview text is empty.")
        if not sender_name:
            issues.append("Email sender name is empty.")
        if not from_address:
            issues.append("Email from_address is empty.")
        if not reply_to_address:
            issues.append("Email reply_to_address is empty.")
        if len(html_content) < cfg.get("min_total_content_length", 200):
            issues.append(
                f"Email html_content looks unusually short/empty "
                f"({len(html_content)} chars, expected at least {cfg.get('min_total_content_length', 200)})."
            )
    else:
        # Generic fallback for other channels (e.g. SMS) whose exact schema
        # we haven't confirmed yet - checks there's a reasonable amount of text.
        channel_key = channel.lower()
        node = content_root.get(channel_key) or content_root
        texts = _extract_content_strings(node)
        total_len = sum(len(t.strip()) for t in texts)
        min_len = cfg.get("min_total_content_length", 200)
        if total_len < min_len:
            issues.append(
                f"Content for {channel} looks unusually short or empty "
                f"(extracted {total_len} chars, expected at least {min_len})."
            )
    return issues


def check_control_group(campaign, rules):
    cfg = rules["control_group_check"]
    if not cfg["enabled"]:
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
    cfg = rules["conversion_goal_check"]
    if not cfg["enabled"]:
        return []
    goals = (campaign.get("conversion_goal_details", {}) or {}).get("goals", []) or []
    issues = []

    if cfg.get("require_at_least_one_goal") and not goals:
        issues.append("No conversion goals configured for this campaign.")

    if cfg.get("require_exactly_one_primary_goal") and goals:
        primary_count = sum(1 for g in goals if g.get("is_primary_goal"))
        if primary_count == 0:
            issues.append("No conversion goal is marked as primary (need exactly one).")
        elif primary_count > 1:
            issues.append(f"{primary_count} conversion goals are marked primary - should be exactly one.")
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


CHECKS = [
    check_naming_convention,
    check_tags,
    check_segment_sanity,
    check_content_completeness,
    check_control_group,
    check_conversion_goals,
    check_delivery_controls,
    check_utm_params,
    check_utm_mismatch,
    check_personalization_tokens,
    check_links,
    check_compliance_footer,
    check_schedule_sanity,
]


def run_qa(campaign, rules):
    issues = []
    for check_fn in CHECKS:
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
    parser.add_argument("--status", help="Filter by status, e.g. SCHEDULED, ACTIVE")
    parser.add_argument("--channel", help="Filter by channel, e.g. EMAIL, PUSH, SMS")
    parser.add_argument("--limit", type=int, default=15, help="Campaigns per page (max 15)")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--out", default="qa_report.json", help="Path to write JSON report")
    args = parser.parse_args()

    config = load_config()
    campaigns = fetch_campaigns(
        config, status=args.status, channel=args.channel, limit=args.limit, page=args.page
    )

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