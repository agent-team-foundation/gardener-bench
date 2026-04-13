#!/usr/bin/env python3
"""Score gardener verdicts against actual PR outcomes.

Usage: python3 src/score.py --data-dir reports/owner-repo/YYYY-MM-DD
"""
import argparse
import json
import os
import re


STATE_RE = re.compile(r"verdict=(?P<verdict>[A-Z_]+)")

OUTCOME_LABELS = {
    "merged_clean": "Merged cleanly",
    "merged_after_revision": "Merged after revision",
    "maintainer_rejected": "Maintainer rejected",
    "author_withdrawn": "Author withdrawn",
    "pending": "Still open",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def score_prs(data_dir):
    gardener_comments = load_json(os.path.join(data_dir, "gardener_comments.json"))
    targets = load_json(os.path.join(data_dir, "targets.json"))
    pr_data = load_json(os.path.join(data_dir, "pr_data.json"))
    closers = load_json(os.path.join(data_dir, "closers.json"))

    # Map target_n -> gardener verdict + timestamp
    g_by_n = {}
    for c in gardener_comments:
        n = int(c["issue_url"].rsplit("/", 1)[-1])
        m = STATE_RE.search(c["body"])
        if m:
            g_by_n[n] = {"verdict": m.group("verdict"), "commented_at": c["created_at"]}

    targets_by_n = {t["n"]: t for t in targets}
    pr_nums = [t["n"] for t in targets if t.get("is_pr")]

    results = []
    for n in pr_nums:
        if n not in g_by_n:
            continue
        n_str = str(n)
        pd = pr_data.get(n_str, pr_data.get(n, {}))
        pr = pd.get("pr", {})
        reviews = pd.get("reviews", [])
        commits = pd.get("commits", [])

        verdict = g_by_n[n]["verdict"]
        g_time = g_by_n[n]["commented_at"]
        author = pr.get("user", "")
        merged = pr.get("merged", False)
        state = pr.get("state", "open")

        post_commits = [c for c in commits if c.get("date", "") > g_time]
        maintainer_reviews = [
            r for r in reviews
            if r.get("user") != author and not r.get("user", "").endswith("[bot]")
        ]
        changes_requested = any(r.get("state") == "CHANGES_REQUESTED" for r in maintainer_reviews)
        approved = any(r.get("state") == "APPROVED" for r in maintainer_reviews)
        revised = len(post_commits) > 0 and (changes_requested or len(maintainer_reviews) > 0)

        # Close context
        closer = closers.get(str(n), closers.get(n, ""))
        close_reason = ""
        if state == "closed" and not merged:
            if closer == author:
                close_reason = "author_withdrawn"
            elif not changes_requested and not any(
                r.get("state") in ("CHANGES_REQUESTED", "APPROVED")
                for r in maintainer_reviews
            ):
                # Closed by maintainer without any code review feedback —
                # governance/cleanup action, not a code quality rejection.
                # Gardener evaluates code-tree alignment, not contributor
                # trust or maintainer backlog decisions.
                close_reason = "governance_closed"
            else:
                close_reason = "maintainer_rejected"

        # Outcome
        if state == "open":
            outcome = "pending"
        elif merged:
            outcome = "merged_after_revision" if revised else "merged_clean"
        elif close_reason == "author_withdrawn":
            outcome = "author_withdrawn"
        elif close_reason == "governance_closed":
            outcome = "governance_closed"
        else:
            outcome = "maintainer_rejected"

        # Score
        # author_withdrawn, governance_closed, pending = unscorable
        if outcome in ("pending", "author_withdrawn", "governance_closed"):
            score = "unscorable"
            score_reason = outcome
        elif verdict == "ALIGNED":
            if outcome == "merged_clean":
                score, score_reason = "correct", "ALIGNED → merged cleanly"
            elif outcome == "merged_after_revision":
                score, score_reason = "partial", "ALIGNED but required revision"
            elif outcome == "maintainer_rejected":
                score, score_reason = "wrong", "ALIGNED but maintainer rejected"
            else:
                score, score_reason = "unknown", f"unexpected: {outcome}"
        elif verdict in ("NEEDS_REVIEW", "CONFLICT", "INSUFFICIENT_CONTEXT", "NEW_TERRITORY"):
            if outcome == "maintainer_rejected":
                score, score_reason = "correct", f"{verdict} → maintainer rejected"
            elif outcome == "merged_after_revision":
                score, score_reason = "correct", f"{verdict} → merged after revision"
            elif outcome == "merged_clean":
                score, score_reason = "wrong", f"{verdict} but merged cleanly — false alarm"
            else:
                score, score_reason = "unknown", f"unexpected: {outcome}"
        else:
            score, score_reason = "unknown", f"unknown verdict: {verdict}"

        results.append({
            "n": n,
            "verdict": verdict,
            "outcome": outcome,
            "close_reason": close_reason,
            "closer": closer,
            "score": score,
            "score_reason": score_reason,
            "title": pr.get("title", ""),
            "author": author,
            "state": state,
            "merged": merged,
            "post_commits": len(post_commits),
            "changes_requested": changes_requested,
            "approved": approved,
            "revised": revised,
        })

    # Summary
    scorable = [r for r in results if r["score"] in ("correct", "partial", "wrong")]
    correct = sum(1 for r in scorable if r["score"] == "correct")
    partial = sum(1 for r in scorable if r["score"] == "partial")
    wrong = sum(1 for r in scorable if r["score"] == "wrong")
    pending = sum(1 for r in results if r["outcome"] == "pending")
    withdrawn = sum(1 for r in results if r["outcome"] == "author_withdrawn")
    governance = sum(1 for r in results if r["outcome"] == "governance_closed")

    accuracy = (correct + 0.5 * partial) / len(scorable) * 100 if scorable else 0

    summary = {
        "total_prs": len(results),
        "scorable": len(scorable),
        "correct": correct,
        "partial": partial,
        "wrong": wrong,
        "unscorable": len(results) - len(scorable),
        "pending": pending,
        "withdrawn": withdrawn,
        "governance_closed": governance,
        "accuracy": round(accuracy, 1),
    }

    return results, summary


def main():
    parser = argparse.ArgumentParser(description="Score gardener verdicts")
    parser.add_argument("--data-dir", required=True, help="Directory with fetched data")
    args = parser.parse_args()

    results, summary = score_prs(args.data_dir)

    with open(os.path.join(args.data_dir, "pr_scores.json"), "w") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(args.data_dir, "accuracy.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Scored {summary['total_prs']} PRs:")
    print(f"  Scorable: {summary['scorable']}")
    print(f"  Correct: {summary['correct']}, Partial: {summary['partial']}, Wrong: {summary['wrong']}")
    print(f"  Accuracy: {summary['accuracy']}%")
    print(f"  Pending: {summary['pending']}, Withdrawn: {summary['withdrawn']}")

    for r in results:
        if r["score"] == "wrong":
            print(f"  WRONG: #{r['n']} {r['verdict']}→{r['outcome']} \"{r['title'][:60]}\"")
    for r in results:
        if r["score"] == "partial":
            print(f"  PARTIAL: #{r['n']} {r['verdict']}→{r['outcome']} \"{r['title'][:60]}\"")


if __name__ == "__main__":
    main()
