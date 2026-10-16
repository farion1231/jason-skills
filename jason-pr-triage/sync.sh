#!/usr/bin/env bash
# Sync GitHub PR metadata into the local PR-triage cache, then print action queues
# derived from cache × ledger (待合并/候拍板/待重验/待发布/待深审/候作者/待感谢/未分诊).
#
#   sync.sh          incremental (uses sync-state.json's pr_last_synced_at)
#   sync.sh --full   full refetch (first run, or recovery from a broken cache)
#
# Cache is REGENERABLE — it only mirrors GitHub facts (no verdicts live here).
# The ledger (pr-ledger.jsonl) is never touched by this script.
set -euo pipefail

REPO="farion1231/cc-switch"
DIR="${CC_TRIAGE_DIR:-$HOME/.cc-switch-triage}"
CACHE="$DIR/cache/prs.jsonl"
STATE="$DIR/sync-state.json"
LEDGER="$DIR/pr-ledger.jsonl"

mkdir -p "$DIR/cache"
touch "$CACHE" "$LEDGER"

SINCE=""
if [[ "${1:-}" != "--full" && -f "$STATE" ]]; then
  SINCE=$(jq -r '.pr_last_synced_at // empty' "$STATE" 2>/dev/null || true)
fi

# Stamp BEFORE fetching so updates landing mid-fetch are re-pulled next time.
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FIELDS="number,title,state,isDraft,author,headRefOid,baseRefName,additions,deletions,changedFiles,labels,body,createdAt,updatedAt,mergedAt,mergeCommit"

# Fixes/Refs are parsed out of the body here so the cache stays lean (bodies are not
# stored) and the issue-ledger merge-writeback can consume them directly.
# HTML comments are stripped first: the PR template's example ("Fixes #123") lives in a
# comment, and 120+ PRs keep it verbatim — scanning raw bodies poisons the parse.
TRANSFORM='.[] | (.body // "" | gsub("<!--.*?-->"; ""; "m")) as $b | {
  number, title, state, draft: .isDraft, author: .author.login,
  head: .headRefOid, base: .baseRefName,
  adds: .additions, dels: .deletions, files: .changedFiles,
  labels: [.labels[].name],
  fixes: ([$b | scan("(?i)\\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?):?\\s*#(\\d+)")] | map(.[0] | tonumber) | unique),
  refs:  ([$b | scan("(?i)\\brefs?:?\\s*#(\\d+)")] | map(.[0] | tonumber) | unique),
  created_at: .createdAt, updated_at: .updatedAt, merged_at: .mergedAt,
  merged_as: (.mergeCommit.oid // null)
}'

NEW=$(mktemp)
trap 'rm -f "$NEW"' EXIT

if [[ -n "$SINCE" ]]; then
  echo "incremental sync since $SINCE" >&2
  # Search API caps at 1000 results — fine for incremental windows (day granularity).
  gh pr list -R "$REPO" --state all --search "updated:>=${SINCE%%T*}" --limit 1000 \
    --json "$FIELDS" | jq -c "$TRANSFORM" >"$NEW"
else
  echo "full sync (fetches every PR — takes a few minutes)" >&2
  gh pr list -R "$REPO" --state all --limit 10000 --json "$FIELDS" | jq -c "$TRANSFORM" >"$NEW"
fi

FETCHED=$(wc -l <"$NEW" | tr -d ' ')

# Merge: newly fetched rows win over cached ones (INDEX keeps the last occurrence).
MERGETMP=$(mktemp)
cat "$CACHE" "$NEW" | jq -s -c 'INDEX(.number) | to_entries | sort_by(.value.number) | .[].value' >"$MERGETMP"
mv "$MERGETMP" "$CACHE"

# ---- Reconcile deletions -------------------------------------------------------
# A PR removed from GitHub (author account banned/deleted) never comes back from any
# fetch — incremental or --full — so a cached OPEN row would haunt every bucket forever.
# Compare cached OPEN numbers with the live open list; re-query each missing one:
# 404 ⇒ state "DELETED" (row kept so the ledger entry still resolves), else fresh state.
LIVE_OPEN=$(gh pr list -R "$REPO" --state open --limit 3000 --json number | jq -c '[.[].number]')
GHOSTS=$(jq -r --argjson live "$LIVE_OPEN" \
  'select(.state == "OPEN") | select(.number as $n | ($live | index($n)) == null) | .number' "$CACHE")
if [[ -n "$GHOSTS" ]]; then
  RECON=$(mktemp)
  for n in $GHOSTS; do
    if ! gh api "repos/$REPO/pulls/$n" \
        --jq '{number: .number, state: (if .merged_at then "MERGED" elif .state == "closed" then "CLOSED" else "OPEN" end),
               merged_at: .merged_at, merged_as: (if .merged_at then .merge_commit_sha else null end),
               updated_at: .updated_at, head: .head.sha}' >>"$RECON" 2>/dev/null; then
      jq -cn --argjson n "$n" --arg t "$NOW" '{number: $n, state: "DELETED", deleted_at: $t}' >>"$RECON"
    fi
  done
  MERGETMP=$(mktemp)
  jq -s -c --slurpfile recon "$RECON" '
    (INDEX($recon[]; .number)) as $R
    | .[] | . + ($R[(.number | tostring)] // {})' "$CACHE" >"$MERGETMP"
  mv "$MERGETMP" "$CACHE"
  rm -f "$RECON"
  echo "reconciled $(echo "$GHOSTS" | wc -l | tr -d ' ') PR(s) missing from live open list" >&2
fi

if [[ -f "$STATE" ]]; then
  STMP=$(mktemp)
  jq --arg t "$NOW" '. + {pr_last_synced_at: $t}' "$STATE" >"$STMP" && mv "$STMP" "$STATE"
else
  printf '{"pr_last_synced_at": "%s"}\n' "$NOW" >"$STATE"
fi

TOTAL=$(wc -l <"$CACHE" | tr -d ' ')
echo "== sync summary =="
echo "fetched/updated this run: $FETCHED"
echo "cache total: $TOTAL"
echo

# ---- Action queues: pure derivation from cache × ledger. Nothing is written.  ----
# Staleness (head moved since review) and every bucket below are DERIVED states —
# they must never be persisted into the ledger.
QUEUE_JQ='
def prio: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[.row.priority // "P3"] // 3;
def line: "  #\(.number)\t\(.row.priority // "-")\t\(.row.category // "-")\t+\(.adds)/-\(.dels)\t\(.title[0:70])";
def section(name; items; cap):
  ["── \(name)（\(items | length)）──"] + ([items[] | line] | .[0:cap]) + [""];
def section(name; items): section(name; items; 999);
def anchored: (.row.review.head_sha // "") as $a | ($a != "") and (.head | startswith($a));
(INDEX($ledger[]; .number)) as $L
| map(. + {row: ($L[(.number | tostring)] // null)})
| (map(select(.state == "OPEN"))) as $open
| section("🟢 待合并：已审 approve、sha 未动，动作在 Jason";
    [$open[] | select(.row.review != null and .row.review.verdict == "approve" and anchored)] | sort_by(prio))
+ section("🟠 候拍板：代码没拦路，等方向决策";
    [$open[] | select(.row.review != null and .row.review.verdict == "pending-direction" and anchored)])
+ section("🔁 待重验：审后有新 push，旧结论已 stale（/jason-review）";
    [$open[] | select(.row.review != null and (anchored | not))])
+ section("📮 待发布：有裁决未发出（/jason-post-review）";
    [$open[] | select(.row.review != null and anchored and .row.published == null
                      and (.row.review.verdict == "approve-with-nits" or .row.review.verdict == "request-changes" or .row.review.verdict == "reject"))])
+ section("🔍 待深审：已分诊未深审，按优先级（/jason-review）";
    ([$open[] | select(.draft == false and .row != null and .row.review == null)] | sort_by(prio)); 15)
+ section("⏳ 候作者：意见已发且 sha 未动，球在作者";
    [$open[] | select(.row.review != null and anchored and .row.published != null
                      and (.row.review.verdict == "approve-with-nits" or .row.review.verdict == "request-changes"))])
+ section("🙏 待感谢：已合并未发感谢（/jason-post-review）";
    [.[] | select(.state == "MERGED" and .row.review != null and .row.thanks == null)])
+ section("🆕 未分诊：按最近活跃（本 skill 批量分诊）";
    ([$open[] | select(.draft == false and .row == null)] | sort_by(.updated_at) | reverse); 20)
+ ["draft PR（不催审）: \([$open[] | select(.draft == true)] | length)"]
| .[]
'
echo "== PR action queues =="
jq -s -r --slurpfile ledger "$LEDGER" "$QUEUE_JQ" "$CACHE"
