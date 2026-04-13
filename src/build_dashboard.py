#!/usr/bin/env python3
"""Build an interactive HTML dashboard from scored gardener data.

Usage: python3 src/build_dashboard.py --data-dir reports/owner-repo/YYYY-MM-DD --repo owner/repo
"""
import argparse
import json
import os
import re
import html
from collections import Counter, defaultdict
from datetime import datetime


STATE_RE = re.compile(
    r"<!-- gardener:state · reviewed=(?P<reviewed>[^ ]+) · verdict=(?P<verdict>[A-Z_]+) "
    r"· severity=(?P<severity>[a-z]+) · tree_sha=(?P<tree_sha>[^ ]+) -->"
)

# Engagement detection
ENGAGE_KW = re.compile(
    r"gardener|repo-gardener|bot review|bot comment|context.tree|context review", re.I
)
VERDICT_KW = re.compile(
    r"verdict|ALIGNED|NEEDS_REVIEW|CONFLICT|INSUFFICIENT_CONTEXT|NEW_TERRITORY|severity", re.I
)
QUOTE_RE = re.compile(
    r"^>\s*.*(gardener|verdict|severity|ALIGNED|NEEDS_REVIEW|context review)",
    re.I | re.MULTILINE,
)
ADDRESS_RE = re.compile(
    r"(thanks\s*@\w+.{0,10}review|thanks for the.{0,20}review|good catch|addressing|"
    r"response to gardener|review follow|went through.{0,30}concern|"
    r"addressed.{0,20}(point|finding|concern|feedback|review)|"
    r"follow.?up.{0,15}(gardener|review)|update pushed)",
    re.I,
)


def is_engaging(body):
    signals = []
    if ENGAGE_KW.search(body):
        signals.append("mentions-gardener")
    if VERDICT_KW.search(body):
        signals.append("references-verdict")
    if QUOTE_RE.search(body):
        signals.append("quotes-gardener")
    if ADDRESS_RE.search(body):
        signals.append("addresses-review")
    return (len(signals) > 0, signals)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def esc(s):
    return html.escape(s or "")


def md_lite(s, repo):
    s = esc(s)
    s = re.sub(
        r"```([^`]+?)```",
        lambda m: f"<pre><code>{m.group(1)}</code></pre>",
        s, flags=re.DOTALL,
    )
    s = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(
        r"(?<![A-Za-z0-9/])#(\d{3,5})",
        rf'<a href="https://github.com/{repo}/issues/\1" target="_blank">#\1</a>',
        s,
    )
    s = re.sub(
        r"(?<![A-Za-z0-9])@([A-Za-z0-9-]+)",
        r'<a href="https://github.com/\1" target="_blank">@\1</a>',
        s,
    )
    s = re.sub(
        r'(?<!href=")(https?://[^\s<]+)',
        r'<a href="\1" target="_blank">\1</a>',
        s,
    )
    s = s.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{s}</p>"


VERDICT_COLORS = {
    "ALIGNED": "#2ea44f",
    "NEEDS_REVIEW": "#bf8700",
    "CONFLICT": "#cf222e",
    "INSUFFICIENT_CONTEXT": "#8250df",
    "NEW_TERRITORY": "#0969da",
}
SEVERITY_COLORS = {"low": "#6e7781", "medium": "#bf8700", "high": "#cf222e"}
SCORE_COLORS = {
    "correct": "#2ea44f",
    "partial": "#bf8700",
    "wrong": "#cf222e",
    "unscorable": "#6e7781",
}
OUTCOME_LABELS = {
    "merged_clean": "Merged cleanly",
    "merged_after_revision": "Merged after revision",
    "maintainer_rejected": "Maintainer rejected",
    "author_withdrawn": "Author withdrawn",
    "governance_closed": "Governance closed",
    "pending": "Still open",
}


def chip(text, color):
    return f'<span class="chip" style="background:{color}">{esc(text)}</span>'


def signal_chips(signals):
    colors = {
        "mentions-gardener": "#8250df",
        "references-verdict": "#0969da",
        "quotes-gardener": "#bf8700",
        "addresses-review": "#2ea44f",
    }
    return " ".join(
        f'<span class="signal-chip" style="background:{colors.get(s, "#6e7781")}">{esc(s)}</span>'
        for s in signals
    )


def build_dashboard(data_dir, repo, output_path):
    gardener_comments = load_json(os.path.join(data_dir, "gardener_comments.json"))
    targets = load_json(os.path.join(data_dir, "targets.json"))
    pr_scores = load_json(os.path.join(data_dir, "pr_scores.json"))
    accuracy = load_json(os.path.join(data_dir, "accuracy.json"))
    threads = load_json(os.path.join(data_dir, "threads.json"))

    targets_by_n = {t["n"]: t for t in targets}
    scores_by_n = {s["n"]: s for s in pr_scores}

    # Parse gardener comments
    parsed = []
    for c in gardener_comments:
        m = STATE_RE.search(c["body"])
        if not m:
            continue
        reviewed = m.group("reviewed")
        target_kind = "issue" if reviewed.startswith("issue@") else "pr"
        n = int(c["issue_url"].rsplit("/", 1)[-1])
        t = targets_by_n.get(n, {})
        body = c["body"]
        body = re.sub(r"<!-- gardener:state[^>]*-->\n?", "", body)
        body = re.sub(r"<!-- gardener:last_consumed_rereview=[^>]*-->\n?", "", body)
        body = body.strip()
        parsed.append({
            "comment_id": c["id"],
            "html_url": c["html_url"],
            "created_at": c["created_at"],
            "verdict": m.group("verdict"),
            "severity": m.group("severity"),
            "target_kind": target_kind,
            "target_n": n,
            "target_title": t.get("title", ""),
            "target_state": t.get("state", ""),
            "target_author": t.get("user", ""),
            "target_url": t.get("url", f"https://github.com/{repo}/issues/{n}"),
            "target_is_pr": t.get("is_pr", False),
            "body": body,
        })

    parsed.sort(key=lambda r: r["created_at"])

    # Thread replies + engagement
    all_replies = defaultdict(list)
    engaging_replies = defaultdict(list)
    other_replies = defaultdict(list)
    prior_comments = defaultdict(list)

    gardener_ids_by_n = defaultdict(set)
    for r in parsed:
        gardener_ids_by_n[r["target_n"]].add(r["comment_id"])

    for n in {r["target_n"] for r in parsed}:
        thread = threads.get(str(n), threads.get(n, []))
        g_ids = gardener_ids_by_n[n]
        thread.sort(key=lambda c: c["created_at"])
        first_gt = min(
            (c["created_at"] for c in thread if c["id"] in g_ids), default=None
        )
        if not first_gt:
            continue
        for c in thread:
            if c["id"] in g_ids:
                continue
            entry = {
                "user": c["user"]["login"],
                "created_at": c["created_at"],
                "body": c["body"],
                "html_url": c["html_url"],
            }
            if c["created_at"] < first_gt:
                prior_comments[n].append(entry)
            else:
                engaged, signals = is_engaging(c["body"])
                entry["engaged"] = engaged
                entry["signals"] = signals
                all_replies[n].append(entry)
                if engaged:
                    engaging_replies[n].append(entry)
                else:
                    other_replies[n].append(entry)

    # Stats
    total = len(parsed)
    verdicts = Counter(r["verdict"] for r in parsed)
    severities = Counter(r["severity"] for r in parsed)
    kinds = Counter(r["target_kind"] for r in parsed)
    unique_targets = len({r["target_n"] for r in parsed})
    earliest = parsed[0]["created_at"] if parsed else "N/A"
    latest = parsed[-1]["created_at"] if parsed else "N/A"

    threads_with_any_reply = sum(1 for r in parsed if all_replies.get(r["target_n"]))
    threads_with_engagement = sum(1 for r in parsed if engaging_replies.get(r["target_n"]))
    total_engaging_replies = sum(len(v) for v in engaging_replies.values())
    total_other_replies = sum(len(v) for v in other_replies.values())

    review_authors = Counter(r["target_author"] for r in parsed)
    engager_counter = Counter()
    for n, lst in engaging_replies.items():
        for c in lst:
            engager_counter[c["user"]] += 1

    # Accuracy
    acc = accuracy
    acc_pct = acc.get("accuracy", 0)
    gauge_color = "#2ea44f" if acc_pct >= 80 else "#bf8700" if acc_pct >= 60 else "#cf222e"

    # Confusion matrix
    confusion = defaultdict(lambda: defaultdict(int))
    for s in pr_scores:
        if s["score"] == "unscorable":
            continue
        confusion[s["verdict"]][s["outcome"]] += 1

    confusion_outcomes = ["merged_clean", "merged_after_revision", "maintainer_rejected"]
    confusion_verdicts = sorted({s["verdict"] for s in pr_scores if s["score"] != "unscorable"})

    confusion_rows = ""
    for v in confusion_verdicts:
        cells = ""
        for o in confusion_outcomes:
            count = confusion[v][o]
            if (v == "ALIGNED" and o == "merged_clean") or (
                v != "ALIGNED" and o in ("merged_after_revision", "maintainer_rejected")
            ):
                bg = "#dcfce7" if count > 0 else ""
            elif count > 0:
                bg = "#fee2e2"
            else:
                bg = ""
            style = f' style="background:{bg}"' if bg else ""
            cells += f"<td{style}>{count}</td>"
        confusion_rows += f"<tr><td>{chip(v, VERDICT_COLORS.get(v, '#6e7781'))}</td>{cells}</tr>"

    # Wrong/partial/unscorable tables
    def score_table(score_type, label):
        rows = ""
        for s in pr_scores:
            if s["score"] != score_type:
                continue
            rows += (
                f'<tr{"" if score_type != "unscorable" else " class=\"muted-row\""}>'
                f'<td><a href="https://github.com/{repo}/pull/{s["n"]}" target="_blank">#{s["n"]}</a></td>'
                f'<td>{chip(s["verdict"], VERDICT_COLORS.get(s["verdict"], "#6e7781"))}</td>'
                f'<td>{esc(OUTCOME_LABELS.get(s.get("outcome", s.get("score_reason", "")), s.get("score_reason", "")))}</td>'
                f'<td>{esc(s["title"][:70])}</td>'
                f'<td><a href="https://github.com/{esc(s["author"])}" target="_blank">@{esc(s["author"])}</a></td>'
                f'<td class="muted">{esc(s.get("score_reason", ""))}</td>'
                f'</tr>'
            )
        if not rows:
            return ""
        return (
            f'<h4>{label}</h4>'
            f'<table class="detail-table"><tr><th>PR</th><th>Verdict</th><th>Outcome</th><th>Title</th><th>Author</th><th>Reason</th></tr>'
            f'{rows}</table>'
        )

    wrong_html = score_table("wrong", "Wrong calls — feedback for gardener improvement")
    partial_html = score_table("partial", "Partial calls")

    unscorable_rows = ""
    for s in pr_scores:
        if s["score"] != "unscorable":
            continue
        reason_label = OUTCOME_LABELS.get(s.get("score_reason", ""), s.get("score_reason", ""))
        unscorable_rows += (
            f'<tr class="muted-row">'
            f'<td><a href="https://github.com/{repo}/pull/{s["n"]}" target="_blank">#{s["n"]}</a></td>'
            f'<td>{chip(s["verdict"], VERDICT_COLORS.get(s["verdict"], "#6e7781"))}</td>'
            f'<td>{esc(reason_label)}</td>'
            f'<td>{esc(s["title"][:70])}</td>'
            f'<td><a href="https://github.com/{esc(s["author"])}" target="_blank">@{esc(s["author"])}</a></td>'
            f'</tr>'
        )

    # Card rows
    rows_html = []
    for r in parsed:
        kind_label = "PR" if r["target_is_pr"] else "Issue"
        verdict_chip = chip(r["verdict"], VERDICT_COLORS.get(r["verdict"], "#6e7781"))
        sev_chip = chip(r["severity"], SEVERITY_COLORS.get(r["severity"], "#6e7781"))
        state_chip = chip(r["target_state"], "#6e7781") if r["target_state"] else ""

        score_info = scores_by_n.get(r["target_n"])
        score_chip = ""
        if score_info and r["target_is_pr"]:
            sc = score_info["score"]
            sc_color = SCORE_COLORS.get(sc, "#6e7781")
            sc_label = sc.upper()
            if sc == "unscorable":
                sc_label = score_info.get("score_reason", "unscorable").replace("_", " ").upper()
            score_chip = f' {chip(sc_label, sc_color)}'

        n = r["target_n"]
        eng = engaging_replies.get(n, [])
        oth = other_replies.get(n, [])
        eng_count = len(eng)
        oth_count = len(oth)

        eng_html = ""
        if eng:
            parts = []
            for rep in eng:
                parts.append(
                    f'<div class="reply engaging"><div class="reply-meta">'
                    f'<a href="{esc(rep["html_url"])}" target="_blank">'
                    f'<strong>{esc(rep["user"])}</strong></a> · {esc(rep["created_at"])} '
                    f'{signal_chips(rep["signals"])}'
                    f'</div><div class="reply-body">{md_lite(rep["body"], repo)}</div></div>'
                )
            eng_html = (
                '<div class="replies engaging-section">'
                f'<h4>Engaging with gardener ({eng_count})</h4>'
                + "".join(parts) + "</div>"
            )

        oth_html = ""
        if oth:
            parts = []
            for rep in oth:
                parts.append(
                    f'<div class="reply other"><div class="reply-meta">'
                    f'<a href="{esc(rep["html_url"])}" target="_blank">'
                    f'<strong>{esc(rep["user"])}</strong></a> · {esc(rep["created_at"])}'
                    f'</div><div class="reply-body">{md_lite(rep["body"], repo)}</div></div>'
                )
            oth_html = (
                f'<details class="other-replies"><summary class="muted">'
                f'{oth_count} other repl{"y" if oth_count == 1 else "ies"} '
                f'(not engaging with gardener)</summary>'
                + "".join(parts) + "</details>"
            )

        prior = prior_comments.get(n, [])
        prior_html = ""
        if prior:
            prior_html = f'<div class="prior-note">({len(prior)} comment(s) before gardener on this thread)</div>'

        badge = ""
        if eng_count:
            badge = f'<span class="reply-badge engage">{eng_count} engaging</span>'
        if oth_count:
            badge += f' <span class="reply-badge other-badge">{oth_count} other</span>'

        rows_html.append(f"""
<article class="card" data-verdict="{esc(r['verdict'])}" data-severity="{esc(r['severity'])}" data-kind="{esc(r['target_kind'])}" data-eng="{eng_count}" data-replies="{eng_count + oth_count}" data-score="{esc(score_info['score'] if score_info else '')}">
  <header>
    <div class="card-title">
      <span class="kind">{kind_label} <a href="{esc(r['target_url'])}" target="_blank">#{r['target_n']}</a></span>
      <a class="title-link" href="{esc(r['target_url'])}" target="_blank">{esc(r['target_title'])}</a>
    </div>
    <div class="meta">
      {verdict_chip} {sev_chip} {state_chip}{score_chip}
      <span class="muted">by <a href="https://github.com/{esc(r['target_author'])}" target="_blank">@{esc(r['target_author'])}</a></span>
      <span class="muted">· {esc(r['created_at'])}</span>
      <a class="comment-link" href="{esc(r['html_url'])}" target="_blank">→ gardener comment</a>
      {badge}
    </div>
  </header>
  {prior_html}
  <div class="body">{md_lite(r['body'], repo)}</div>
  {eng_html}
  {oth_html}
</article>
""")

    verdict_summary = " ".join(
        f'{chip(v, VERDICT_COLORS.get(v, "#6e7781"))} <span class="muted">{n}</span>'
        for v, n in verdicts.most_common()
    )
    severity_summary = " ".join(
        f'{chip(s, SEVERITY_COLORS.get(s, "#6e7781"))} <span class="muted">{n}</span>'
        for s, n in severities.most_common()
    )
    top_reviewed = "".join(
        f'<li><a href="https://github.com/{esc(u)}" target="_blank">@{esc(u)}</a> — {n}</li>'
        for u, n in review_authors.most_common(10)
    )
    top_engagers = "".join(
        f'<li><a href="https://github.com/{esc(u)}" target="_blank">@{esc(u)}</a> — {n}</li>'
        for u, n in engager_counter.most_common(10)
    ) or "<li class='muted'>No human engagement detected.</li>"

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gardener-bench — {repo}</title>
<style>
  :root {{
    --fg: #1f2328; --muted: #656d76; --bg: #ffffff; --panel: #f6f8fa;
    --border: #d0d7de; --accent: #0969da;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font: 14px/1.5 -apple-system, "SF Pro Text", system-ui, Segoe UI, sans-serif;
         color: var(--fg); background: var(--bg); margin: 0; padding: 24px; max-width: 1100px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px 0; font-size: 24px; }}
  h2 {{ margin: 24px 0 8px 0; font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  h4 {{ margin: 12px 0 4px 0; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }}
  .sub {{ color: var(--muted); margin-bottom: 16px; }}
  .muted {{ color: var(--muted); font-size: 12px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 16px 0; }}
  .stat {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }}
  .stat .n {{ font-size: 24px; font-weight: 600; }}
  .stat .l {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }}
  .stat.highlight {{ border-left: 4px solid #8250df; }}
  .row-summary {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 8px; }}
  .chip {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;
         color: #fff; text-transform: uppercase; letter-spacing: .4px; }}
  .signal-chip {{ display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 9px; font-weight: 600;
         color: #fff; letter-spacing: .3px; vertical-align: middle; }}
  .controls {{ position: sticky; top: 0; background: var(--bg); padding: 12px 0; border-bottom: 1px solid var(--border); z-index: 10; }}
  .controls label {{ margin-right: 12px; font-size: 12px; color: var(--muted); }}
  .controls select, .controls input {{ font: inherit; padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; }}
  .card {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 12px 0; background: var(--bg); }}
  .card header {{ margin-bottom: 8px; }}
  .card-title {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }}
  .card-title .kind {{ color: var(--muted); font-size: 13px; }}
  .card-title .title-link {{ font-size: 15px; font-weight: 600; color: var(--fg); text-decoration: none; }}
  .card-title .title-link:hover {{ text-decoration: underline; color: var(--accent); }}
  .meta {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 12px; }}
  .meta .comment-link {{ color: var(--accent); text-decoration: none; margin-left: auto; }}
  .meta .comment-link:hover {{ text-decoration: underline; }}
  .reply-badge {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .reply-badge.engage {{ background: #f3e8ff; color: #8250df; }}
  .reply-badge.other-badge {{ background: #eee; color: #656d76; }}
  .prior-note {{ color: var(--muted); font-size: 11px; font-style: italic; margin-bottom: 6px; }}
  .body {{ background: var(--panel); border-left: 3px solid #2da44e; padding: 10px 14px; border-radius: 4px; }}
  .body p {{ margin: 6px 0; }}
  .body code {{ background: rgba(175,184,193,.3); padding: 1px 4px; border-radius: 3px; font-size: 12px; }}
  .body pre {{ background: #1f2328; color: #f6f8fa; padding: 10px; border-radius: 6px; overflow-x: auto; }}
  .body pre code {{ background: none; color: inherit; }}
  .body a {{ color: var(--accent); }}
  .engaging-section {{ margin-top: 10px; padding-left: 14px; border-left: 3px solid #8250df; }}
  .reply.engaging {{ background: #f3e8ff; padding: 8px 12px; border-radius: 4px; margin: 6px 0; }}
  .reply.other {{ background: #f6f8fa; padding: 8px 12px; border-radius: 4px; margin: 6px 0; }}
  .other-replies {{ margin-top: 8px; }}
  .other-replies summary {{ cursor: pointer; padding: 4px 0; }}
  .reply-meta {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
  .reply-body p {{ margin: 4px 0; }}
  ul {{ margin: 4px 0; padding-left: 20px; }}
  a {{ color: var(--accent); }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .methodology {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin: 16px 0; font-size: 12px; color: var(--muted); }}
  .methodology h4 {{ color: var(--fg); }}
  .methodology ul {{ font-size: 12px; }}
  .accuracy-hero {{ display: flex; align-items: center; gap: 24px; margin: 16px 0; flex-wrap: wrap; }}
  .gauge {{ width: 200px; flex-shrink: 0; }}
  .gauge-svg {{ width: 100%; height: auto; }}
  .accuracy-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; flex: 1; min-width: 280px; }}
  .accuracy-stats .stat {{ padding: 8px 12px; }}
  .scoring-table, .confusion, .detail-table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 12px; }}
  .scoring-table th, .scoring-table td,
  .confusion th, .confusion td,
  .detail-table th, .detail-table td {{ border: 1px solid var(--border); padding: 6px 10px; text-align: left; }}
  .scoring-table th, .confusion th, .detail-table th {{ background: var(--panel); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .3px; }}
  .muted-row {{ opacity: 0.6; }}
  @media (max-width: 720px) {{
    .two-col {{ grid-template-columns: 1fr; }}
    .accuracy-hero {{ flex-direction: column; }}
    .accuracy-stats {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
  <h1>gardener-bench</h1>
  <div class="sub">
    Repo: <a href="https://github.com/{repo}" target="_blank">{repo}</a> ·
    Window: {earliest} &rarr; {latest} ·
    Generated {datetime.now().strftime('%Y-%m-%d')} ·
    <a href="https://github.com/agent-team-foundation/gardener-bench" target="_blank">source</a>
  </div>

  <div class="stats">
    <div class="stat"><div class="n">{total}</div><div class="l">Gardener comments</div></div>
    <div class="stat"><div class="n">{unique_targets}</div><div class="l">Unique targets</div></div>
    <div class="stat"><div class="n">{kinds.get('pr', 0)}</div><div class="l">PR reviews</div></div>
    <div class="stat"><div class="n">{kinds.get('issue', 0)}</div><div class="l">Issue reviews</div></div>
    <div class="stat highlight"><div class="n">{threads_with_engagement}</div><div class="l">Threads with engagement</div></div>
    <div class="stat"><div class="n">{threads_with_any_reply}</div><div class="l">Threads with any reply</div></div>
    <div class="stat highlight"><div class="n">{total_engaging_replies}</div><div class="l">Engaging replies</div></div>
    <div class="stat"><div class="n">{total_other_replies}</div><div class="l">Other replies</div></div>
  </div>

  <div class="row-summary">
    <h4>Verdicts</h4>{verdict_summary}
    <h4>Severity</h4>{severity_summary}
  </div>

  <h2>Verdict accuracy</h2>
  <p class="muted">Measures how often gardener's verdict matches the actual maintainer decision. Only scored on PRs with resolved outcomes.</p>

  <div class="accuracy-hero">
    <div class="gauge">
      <svg viewBox="0 0 120 70" class="gauge-svg">
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke="#e5e7eb" stroke-width="8" stroke-linecap="round"/>
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke="{gauge_color}" stroke-width="8" stroke-linecap="round"
              stroke-dasharray="{acc_pct * 1.57} 157" class="gauge-fill"/>
        <text x="60" y="55" text-anchor="middle" font-size="22" font-weight="700" fill="{gauge_color}">{acc_pct:.0f}%</text>
        <text x="60" y="67" text-anchor="middle" font-size="7" fill="#656d76">VERDICT ACCURACY</text>
      </svg>
    </div>
    <div class="accuracy-stats">
      <div class="stat"><div class="n" style="color:#2ea44f">{acc.get('correct',0)}</div><div class="l">Correct</div></div>
      <div class="stat"><div class="n" style="color:#bf8700">{acc.get('partial',0)}</div><div class="l">Partial</div></div>
      <div class="stat"><div class="n" style="color:#cf222e">{acc.get('wrong',0)}</div><div class="l">Wrong</div></div>
      <div class="stat"><div class="n">{acc.get('scorable',0)}</div><div class="l">Scorable PRs</div></div>
      <div class="stat"><div class="n" style="color:#6e7781">{acc.get('pending',0)}</div><div class="l">Pending</div></div>
      <div class="stat"><div class="n" style="color:#6e7781">{acc.get('withdrawn',0)}</div><div class="l">Withdrawn</div></div>
      <div class="stat"><div class="n" style="color:#6e7781">{acc.get('governance_closed',0)}</div><div class="l">Governance closed</div></div>
    </div>
  </div>

  <div class="methodology">
    <h4>How accuracy is calculated</h4>
    <table class="scoring-table">
      <tr><th>Gardener said</th><th>Merged cleanly</th><th>Merged after revision</th><th>Maintainer rejected</th></tr>
      <tr><td>{chip("ALIGNED","#2ea44f")}</td><td style="background:#dcfce7">Correct</td><td style="background:#fef3c7">Partial</td><td style="background:#fee2e2">Wrong</td></tr>
      <tr><td>{chip("NEEDS_REVIEW","#bf8700")}</td><td style="background:#fee2e2">Wrong</td><td style="background:#dcfce7">Correct</td><td style="background:#dcfce7">Correct</td></tr>
      <tr><td>{chip("CONFLICT","#cf222e")}</td><td style="background:#fee2e2">Wrong</td><td style="background:#dcfce7">Correct</td><td style="background:#dcfce7">Correct</td></tr>
    </table>
    <p><strong>Excluded:</strong> Author-withdrawn PRs (gardener can't predict humans leaving) and pending PRs (no outcome yet).</p>
    <p><strong>Formula:</strong> <code>(correct + 0.5 &times; partial) / scorable &times; 100</code></p>
  </div>

  {"<h4>Confusion matrix</h4><table class='confusion'><tr><th>Verdict</th>" + "".join(f"<th>{esc(OUTCOME_LABELS[o])}</th>" for o in confusion_outcomes) + "</tr>" + confusion_rows + "</table>" if confusion_rows else ""}

  {wrong_html}
  {partial_html}

  <details>
    <summary class="muted">Unscorable PRs ({acc.get('pending',0)} pending + {acc.get('withdrawn',0)} withdrawn)</summary>
    <table class="detail-table">
      <tr><th>PR</th><th>Verdict</th><th>Reason</th><th>Title</th><th>Author</th></tr>
      {unscorable_rows}
    </table>
  </details>

  <div class="methodology">
    <h4>How engagement is detected</h4>
    <p>A reply is classified as <strong>engaging with gardener</strong> if it matches one or more signals:</p>
    <ul>
      <li>{chip("mentions-gardener", "#8250df")} — mentions "gardener", "repo-gardener", "context tree", etc.</li>
      <li>{chip("references-verdict", "#0969da")} — references verdict terms (ALIGNED, NEEDS_REVIEW, severity, etc.)</li>
      <li>{chip("quotes-gardener", "#bf8700")} — markdown blockquote containing gardener text</li>
      <li>{chip("addresses-review", "#2ea44f")} — phrases like "addressed findings", "response to gardener", "update pushed"</li>
    </ul>
  </div>

  <h2>Interaction signal</h2>
  <div class="two-col">
    <div>
      <h4>Top authors reviewed by gardener</h4>
      <ul>{top_reviewed}</ul>
    </div>
    <div>
      <h4>People who engaged with gardener</h4>
      <ul>{top_engagers}</ul>
    </div>
  </div>

  <h2>All gardener comments ({total})</h2>
  <div class="controls">
    <label>Verdict
      <select id="fv" onchange="filter()">
        <option value="">all</option>
        <option>ALIGNED</option>
        <option>NEEDS_REVIEW</option>
        <option>CONFLICT</option>
        <option>INSUFFICIENT_CONTEXT</option>
        <option>NEW_TERRITORY</option>
      </select>
    </label>
    <label>Severity
      <select id="fs" onchange="filter()">
        <option value="">all</option>
        <option>low</option>
        <option>medium</option>
        <option>high</option>
      </select>
    </label>
    <label>Kind
      <select id="fk" onchange="filter()">
        <option value="">all</option>
        <option value="pr">PR</option>
        <option value="issue">Issue</option>
      </select>
    </label>
    <label>Score
      <select id="fsc" onchange="filter()">
        <option value="">all</option>
        <option value="correct">Correct</option>
        <option value="partial">Partial</option>
        <option value="wrong">Wrong</option>
        <option value="unscorable">Unscorable</option>
      </select>
    </label>
    <label><input type="checkbox" id="fe" onchange="filter()"> only with engagement</label>
    <label><input type="checkbox" id="fr" onchange="filter()"> any replies</label>
    <label>Search <input id="fq" oninput="filter()" placeholder="title, body, user..."></label>
  </div>

  {''.join(rows_html)}

<script>
function filter() {{
  const fv = document.getElementById('fv').value;
  const fs = document.getElementById('fs').value;
  const fk = document.getElementById('fk').value;
  const fsc = document.getElementById('fsc').value;
  const fe = document.getElementById('fe').checked;
  const fr = document.getElementById('fr').checked;
  const fq = document.getElementById('fq').value.toLowerCase();
  document.querySelectorAll('.card').forEach(c => {{
    let ok = true;
    if (fv && c.dataset.verdict !== fv) ok = false;
    if (fs && c.dataset.severity !== fs) ok = false;
    if (fk && c.dataset.kind !== fk) ok = false;
    if (fsc && c.dataset.score !== fsc) ok = false;
    if (fe && c.dataset.eng === '0') ok = false;
    if (fr && c.dataset.replies === '0') ok = false;
    if (fq && !c.textContent.toLowerCase().includes(fq)) ok = false;
    c.style.display = ok ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html_doc)
    print(f"Dashboard written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Build gardener-bench dashboard")
    parser.add_argument("--data-dir", required=True, help="Directory with scored data")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--output", default=None, help="Output HTML path (default: <data-dir>/dashboard.html)")
    args = parser.parse_args()

    output = args.output or os.path.join(args.data_dir, "dashboard.html")
    build_dashboard(args.data_dir, args.repo, output)


if __name__ == "__main__":
    main()
