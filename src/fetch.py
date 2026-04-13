#!/usr/bin/env python3
"""Fetch gardener comments and thread data from a GitHub repo.

Usage: python3 src/fetch.py --repo owner/repo --out-dir reports/owner-repo/YYYY-MM-DD
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime


def gh_api(endpoint, jq_filter=None):
    cmd = ["gh", "api", endpoint]
    if jq_filter:
        cmd += ["--jq", jq_filter]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: gh api {endpoint}: {result.stderr}", file=sys.stderr)
        return None
    return result.stdout.strip()


def gh_api_json(endpoint):
    raw = gh_api(endpoint)
    if raw is None:
        return []
    return json.loads(raw)


def fetch_all_comments(repo, max_pages=50):
    """Paginate all issue comments, return those with gardener markers."""
    all_gardener = []
    for page in range(1, max_pages + 1):
        comments = gh_api_json(
            f"repos/{repo}/issues/comments?per_page=100&page={page}&sort=created&direction=desc"
        )
        print(f"  page {page}: {len(comments)} comments")
        gardener = [c for c in comments if c.get("body", "").startswith("<!-- gardener:state")]
        all_gardener.extend(gardener)
        if len(comments) < 100:
            break
    return all_gardener


def fetch_target(repo, n):
    """Fetch issue/PR metadata."""
    raw = gh_api(
        f"repos/{repo}/issues/{n}",
        '{n:.number, title:.title, state:.state, user:.user.login, url:.html_url, '
        'is_pr:(.pull_request != null), comments:.comments, created_at:.created_at}',
    )
    if raw:
        return json.loads(raw)
    return None


def fetch_pr_data(repo, n):
    """Fetch PR-specific data: metadata, reviews, commits."""
    pr = gh_api(
        f"repos/{repo}/pulls/{n}",
        '{n:.number, state:.state, merged:.merged, merged_at:.merged_at, '
        'closed_at:.closed_at, created_at:.created_at, updated_at:.updated_at, '
        'user:.user.login, title:.title, commits:.commits, '
        'changed_files:.changed_files, additions:.additions, deletions:.deletions, '
        'review_comments:.review_comments}',
    )
    reviews = gh_api(
        f"repos/{repo}/pulls/{n}/reviews",
        '[.[] | {user:.user.login, state:.state, submitted_at:.submitted_at, body:(.body[:200])}]',
    )
    commits = gh_api(
        f"repos/{repo}/pulls/{n}/commits?per_page=100",
        '[.[] | {sha:.sha, date:.commit.committer.date, message:(.commit.message[:100])}]',
    )
    return {
        "pr": json.loads(pr) if pr else {},
        "reviews": json.loads(reviews) if reviews else [],
        "commits": json.loads(commits) if commits else [],
    }


def fetch_thread_comments(repo, n):
    return gh_api_json(f"repos/{repo}/issues/{n}/comments?per_page=100")


def get_closer(repo, n):
    raw = gh_api(
        f"repos/{repo}/issues/{n}/timeline?per_page=100",
        '[.[] | select(.event=="closed")] | .[0] | .actor.login',
    )
    return raw or ""


def main():
    parser = argparse.ArgumentParser(description="Fetch gardener data from a repo")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--out-dir", help="Output directory (default: reports/<owner-repo>/<date>)")
    args = parser.parse_args()

    repo = args.repo
    date = datetime.now().strftime("%Y-%m-%d")
    out_dir = args.out_dir or f"reports/{repo.replace('/', '-')}/{date}"
    os.makedirs(out_dir, exist_ok=True)

    print(f"Fetching gardener data for {repo} → {out_dir}")

    # 1. Fetch all gardener comments
    print("Fetching comments...")
    gardener_comments = fetch_all_comments(repo)
    print(f"  Found {len(gardener_comments)} gardener comments")
    with open(os.path.join(out_dir, "gardener_comments.json"), "w") as f:
        json.dump(gardener_comments, f, indent=2)

    if not gardener_comments:
        print("No gardener comments found. Exiting.")
        return

    # 2. Extract unique target numbers
    targets_nums = sorted(
        {int(c["issue_url"].rsplit("/", 1)[-1]) for c in gardener_comments}
    )
    print(f"  {len(targets_nums)} unique targets")

    # 3. Fetch target metadata
    print("Fetching target metadata...")
    targets = []
    for n in targets_nums:
        t = fetch_target(repo, n)
        if t:
            targets.append(t)
    with open(os.path.join(out_dir, "targets.json"), "w") as f:
        json.dump(targets, f, indent=2)

    # 4. Fetch PR-specific data
    pr_nums = [t["n"] for t in targets if t.get("is_pr")]
    print(f"Fetching PR data for {len(pr_nums)} PRs...")
    pr_data = {}
    for n in pr_nums:
        pr_data[n] = fetch_pr_data(repo, n)
    with open(os.path.join(out_dir, "pr_data.json"), "w") as f:
        json.dump(pr_data, f, indent=2)

    # 5. Fetch thread comments
    print("Fetching thread comments...")
    threads = {}
    for n in targets_nums:
        threads[n] = fetch_thread_comments(repo, n)
    with open(os.path.join(out_dir, "threads.json"), "w") as f:
        json.dump(threads, f, indent=2)

    # 6. Fetch closers for closed non-merged PRs
    print("Fetching close context...")
    closers = {}
    for n in pr_nums:
        pd = pr_data[n]["pr"]
        if pd.get("state") == "closed" and not pd.get("merged"):
            closers[n] = get_closer(repo, n)
    with open(os.path.join(out_dir, "closers.json"), "w") as f:
        json.dump(closers, f, indent=2)

    print(f"Done. Data saved to {out_dir}/")


if __name__ == "__main__":
    main()
