#!/usr/bin/env bash
# Usage: ./bench.sh owner/repo [--deploy]
#
# Fetches gardener data, scores verdicts, builds dashboard.
# With --deploy, deploys to Cloudflare Pages.

set -euo pipefail

REPO="${1:?Usage: ./bench.sh owner/repo [--deploy]}"
DEPLOY="${2:-}"
DATE=$(date +%Y-%m-%d)
SLUG=$(echo "$REPO" | tr '/' '-')
DATA_DIR="reports/$SLUG/$DATE"

echo "=== gardener-bench: $REPO ==="
echo "Date: $DATE"
echo "Output: $DATA_DIR"
echo

# Step 1: Fetch
echo "--- Fetching data ---"
python3 src/fetch.py --repo "$REPO" --out-dir "$DATA_DIR"
echo

# Step 2: Score
echo "--- Scoring verdicts ---"
python3 src/score.py --data-dir "$DATA_DIR"
echo

# Step 3: Build dashboard
echo "--- Building dashboard ---"
python3 src/build_dashboard.py --data-dir "$DATA_DIR" --repo "$REPO"
echo

echo "Done. Dashboard: $DATA_DIR/dashboard.html"

# Step 4: Deploy (optional)
if [ "$DEPLOY" = "--deploy" ]; then
    echo
    echo "--- Deploying to Cloudflare Pages ---"
    DEPLOY_DIR=$(mktemp -d)
    cp "$DATA_DIR/dashboard.html" "$DEPLOY_DIR/index.html"
    PROJECT="gardener-bench-${SLUG}"
    # Create project if it doesn't exist (will fail silently if exists)
    wrangler pages project create "$PROJECT" --production-branch=main 2>/dev/null || true
    wrangler pages deploy "$DEPLOY_DIR" --project-name="$PROJECT" --commit-dirty=true --branch=main
    rm -rf "$DEPLOY_DIR"
    echo "Live at: https://${PROJECT}.pages.dev"
fi
