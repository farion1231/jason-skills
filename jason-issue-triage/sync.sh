#!/usr/bin/env bash
# Sync GitHub issue metadata into the local triage cache.
#
#   sync.sh          incremental (uses sync-state.json's last_synced_at)
#   sync.sh --full   full refetch (first run, or recovery from a broken cache)
#
# Cache is REGENERABLE — it only mirrors GitHub facts (no verdicts live here).
# The ledger (ledger.jsonl) is never touched by this script.
set -euo pipefail

REPO="farion1231/cc-switch"
DIR="${CC_TRIAGE_DIR:-$HOME/.cc-switch-triage}"
CACHE="$DIR/cache/issues.jsonl"
STATE="$DIR/sync-state.json"
LEDGER="$DIR/ledger.jsonl"
GROUPS_FILE="$DIR/groups.jsonl"

mkdir -p "$DIR/cache"
touch "$CACHE" "$LEDGER" "$GROUPS_FILE"

SINCE=""
if [[ "${1:-}" != "--full" && -f "$STATE" ]]; then
  SINCE=$(jq -r '.last_synced_at // empty' "$STATE" 2>/dev/null || true)
fi

# Stamp BEFORE fetching so updates landing mid-fetch are re-pulled next time.
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FETCH_ARGS=(-X GET "repos/$REPO/issues" -f state=all -f per_page=100 --paginate)
if [[ -n "$SINCE" ]]; then
  FETCH_ARGS+=(-f since="$SINCE")
  echo "incremental sync since $SINCE" >&2
else
  echo "full sync (this fetches every issue — takes a minute)" >&2
fi

NEW=$(mktemp)
trap 'rm -f "$NEW"' EXIT

# The REST issues endpoint interleaves PRs — drop them via the pull_request marker.
gh api "${FETCH_ARGS[@]}" --jq '
  .[] | select(has("pull_request") | not) | {
    number, title, state,
    labels: [.labels[].name],
    author: .user.login,
    comments,
    created_at, updated_at, closed_at,
    state_reason
  }' >"$NEW"

FETCHED=$(wc -l <"$NEW" | tr -d ' ')

# Merge: newly fetched rows win over cached ones (INDEX keeps the last occurrence).
MERGED=$(mktemp)
cat "$CACHE" "$NEW" | jq -s -c 'INDEX(.number) | to_entries | sort_by(.value.number) | .[].value' >"$MERGED"
mv "$MERGED" "$CACHE"

# Merge-write: sync-state.json is shared with the PR-triage skill (pr_last_synced_at) —
# a whole-file overwrite here clobbers that key and forces the PR sync back to full mode.
if [[ -f "$STATE" ]]; then
  STMP=$(mktemp)
  jq --arg t "$NOW" '. + {last_synced_at: $t}' "$STATE" >"$STMP" && mv "$STMP" "$STATE"
else
  printf '{"last_synced_at": "%s"}\n' "$NOW" >"$STATE"
fi

TOTAL=$(wc -l <"$CACHE" | tr -d ' ')
OPEN=$(jq -s '[.[] | select(.state == "open")] | length' "$CACHE")

# Untriaged = open in cache, absent from the ledger.
UNTRIAGED=$(jq -s -c --slurpfile ledger <(jq -c '{number}' "$LEDGER" 2>/dev/null || true) '
  ([$ledger[].number | tostring | {(.): true}] | add // {}) as $done
  | [.[] | select(.state == "open" and ($done[.number | tostring] | not))]
  | sort_by(.updated_at) | reverse' "$CACHE")

UNTRIAGED_COUNT=$(jq 'length' <<<"$UNTRIAGED")

echo "== sync summary =="
echo "fetched/updated this run: $FETCHED"
echo "cache total: $TOTAL  (open: $OPEN)"
echo "untriaged open: $UNTRIAGED_COUNT"
echo
echo "== top 30 untriaged (by recent activity) =="
jq -r '.[:30][] | "#\(.number)\t\(.updated_at[:10])\t\(.labels | join(","))\t\(.title)"' <<<"$UNTRIAGED"
