# gardener-bench

[![Live Dashboard](https://img.shields.io/badge/dashboard-live-blue)](https://gardener-report.pages.dev)
[![Accuracy](https://img.shields.io/badge/accuracy-84.6%25-brightgreen)](reports/paperclipai-paperclip/2026-04-17/accuracy.json)

Verdict accuracy benchmarking and feedback dashboard for [repo-gardener](https://github.com/agent-team-foundation/repo-gardener).

**Live dashboard:** https://gardener-report.pages.dev

## Latest results

As of **2026-04-17** on [paperclipai/paperclip](https://github.com/paperclipai/paperclip):

| Metric | Value |
|---|---|
| Verdict accuracy | **84.6%** |
| Scorable PRs | 13 |
| Correct | 11 |
| Partial | 0 |
| Wrong | 2 |
| Pending (still open) | 189 |
| Author-withdrawn | 29 |
| Governance-closed | 3 |
| Total PRs observed | 231 |

Raw data: [`reports/paperclipai-paperclip/2026-04-17/accuracy.json`](reports/paperclipai-paperclip/2026-04-17/accuracy.json).

## What this does

Gardener posts verdicts (`ALIGNED`, `NEEDS_REVIEW`, `CONFLICT`, etc.) on PRs and issues. But how accurate are those verdicts? This tool measures that by comparing gardener's calls against what actually happened.

**One number: Verdict Accuracy %** — the percentage of gardener verdicts that match the maintainer's actual decision.

## How scoring works

Each PR gets a **verdict** (what gardener said) and an **outcome** (what actually happened):

| Gardener said | Merged cleanly | Merged after revision | Maintainer rejected |
|---|---|---|---|
| ALIGNED | Correct | Partial | Wrong |
| NEEDS_REVIEW | Wrong (false alarm) | Correct | Correct |
| CONFLICT | Wrong (false alarm) | Correct | Correct |

**Excluded from scoring:**
- **Author-withdrawn PRs** — the author closed their own PR. Gardener can't predict humans leaving.
- **Pending PRs** — still open, no outcome yet. Scored when re-run later.

**Formula:** `(correct + 0.5 × partial) / scorable × 100`

## Usage

```bash
# Score a repo where gardener has commented
python3 src/score.py --repo owner/repo

# Build the HTML dashboard
python3 src/build_dashboard.py --repo owner/repo

# Run both (fetch + score + build + deploy)
./bench.sh owner/repo
```

## Reports

Each scored repo gets a directory under `reports/`:

```
reports/
  paperclipai-paperclip/
    2026-04-12/
      accuracy.json      # Structured accuracy data
      pr_scores.json     # Per-PR scoring detail
      dashboard.html     # Interactive HTML report
```

## Dashboard

Live dashboards are deployed to Cloudflare Pages:

- **paperclipai/paperclip**: https://gardener-report.pages.dev

## Feedback loop

The most valuable output is the **wrong calls list**. Each wrong call becomes a case study for improving gardener. The flow:

1. `gardener-bench` scores a repo → finds wrong/partial calls
2. Wrong calls are filed as issues on [repo-gardener](https://github.com/agent-team-foundation/repo-gardener) with the `accuracy-report` label
3. Humans review and decide what to change in gardener's prompts or tree-reading
4. Re-run scoring after changes → watch accuracy % go up

This is a **human-reviewed** feedback loop, not auto-applied.

## Engagement tracking

Beyond accuracy, the dashboard tracks how humans interact with gardener:

- **Engaging replies** — comments that reference, quote, or respond to gardener's review
- **Signal detection** — mentions-gardener, references-verdict, quotes-gardener, addresses-review
- **Engagement rate** — what % of threads have human engagement with gardener

## Related

- [repo-gardener](https://github.com/agent-team-foundation/repo-gardener) — the review bot itself
- [Feature proposal: `repo-gardener score`](https://github.com/agent-team-foundation/repo-gardener/issues/1) — integrating scoring into gardener CLI
- [First accuracy report: paperclipai/paperclip](https://github.com/agent-team-foundation/repo-gardener/issues/2)
