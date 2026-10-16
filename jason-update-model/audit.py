#!/usr/bin/env python3
"""Audit CC Switch's seeded pricing table (schema.rs::seed_model_pricing) against models.dev.

Stdlib only. Run from anywhere:

    python3 .claude/skills/jason-update-model/audit.py [--days 180] [--api-json cached.json]

Outputs a markdown report:
  A. price mismatches   (seed row vs models.dev first-party price, beyond tolerance)
  B. missing models     (recent first-party coding models with no seed row)
  C. seed rows absent from models.dev (informational, NOT errors)

models.dev cost.* is already USD per million tokens — compared as-is, no unit conversion.
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCHEMA_RS = REPO / "src-tauri" / "src" / "database" / "schema.rs"
API_URL = "https://models.dev/api.json"

# First-party providers, in lookup-priority order. When the same normalized model id
# appears under several providers, the earliest match here supplies the reference price;
# aggregators/resellers (opencode, iflowcn, openrouter, ...) are never used — their
# prices are their own retail, not the vendor's list price.
FIRST_PARTY = [
    "anthropic",
    "openai",
    "google",
    "xai",
    "deepseek",
    "zai",
    "zhipuai",
    "moonshotai",
    "moonshotai-cn",
    "alibaba",
    "alibaba-cn",
    "minimax",
    "minimax-cn",
    "mistral",
    "meta",
    "stepfun",
    "xiaomi",
    "longcat",
]
FIRST_PARTY_RANK = {p: i for i, p in enumerate(FIRST_PARTY)}

# A model's own vendor beats any other first-party host (e.g. minimax/MiniMax-M2.5
# must win over alibaba-cn's hosted resale of the same model). Prefix -> home providers.
# International site only — CN twins (zhipuai, moonshotai-cn, ...) stay ordinary
# first-party fallbacks: their entries sometimes carry CNY-ish or stale numbers
# (seen: zhipuai/glm-5v-turbo 5/22 vs official $1.2/$4).
FAMILY_HOME = [
    ("claude", {"anthropic"}),
    ("gpt-", {"openai"}),
    ("gemini", {"google"}),
    ("grok", {"xai"}),
    ("deepseek", {"deepseek"}),
    ("glm", {"zai"}),
    ("kimi", {"moonshotai"}),
    ("qwen", {"alibaba"}),
    ("qwq", {"alibaba"}),
    ("minimax", {"minimax"}),
    ("mimo", {"xiaomi"}),
    ("step", {"stepfun"}),
]

# Providers scanned for MISSING coding models (subset of FIRST_PARTY: the vendors whose
# new releases CC Switch users actually route to). Extend deliberately, not by reflex.
MISSING_SCAN = [
    "anthropic",
    "openai",
    "google",
    "xai",
    "deepseek",
    "zai",
    "moonshotai",
    "alibaba",
    "minimax",
]

# Vendors that publish CNY list prices; the seed table converts at ~7.14, so small
# deltas vs models.dev's own USD figure can be FX rounding, not an error.
CNY_HINT = {"zhipuai", "moonshotai-cn", "alibaba-cn", "minimax-cn", "iflowcn", "xiaomi"}

# Mirrors modelsDevPricing.ts::isTextPricingModel
NON_TEXT_MARKERS = (
    "audio", "deprecated", "embedding", "image", "moderation",
    "realtime", "transcribe", "tts", "video",
)
NON_TEXT_OUTPUT = {"audio", "image", "video"}

# Relative + absolute tolerance for price comparison ($/M)
REL_TOL = 0.02
ABS_TOL = 0.005


def normalize(model_id: str) -> str:
    """Mirrors normalizeModelIdForPricing (TS) / clean_model_id_for_pricing (Rust)."""
    s = model_id[model_id.rfind("/") + 1:]
    s = s.split(":")[0].strip().replace("@", "-").lower()
    if s.endswith("[1m]"):
        s = s[: -len("[1m]")].strip()
    return s


def claude_variants(nid: str):
    """The DB lookup maps '.' <-> '-' for claude- ids; index both spellings."""
    out = {nid}
    if nid.startswith("claude-"):
        out.add("claude-" + nid[len("claude-"):].replace(".", "-"))
    return out


def effective_rank(nid: str, pid: str):
    """Home vendor of the model family always outranks other first-party hosts."""
    for prefix, homes in FAMILY_HOME:
        if nid.startswith(prefix):
            return -1 if pid in homes else FIRST_PARTY_RANK[pid]
    return FIRST_PARTY_RANK[pid]


def parse_seed_rows(text: str):
    """Extract 6-string tuples from seed_model_pricing's pricing_data array.

    Handles both rustfmt layouts (single-line and one-field-per-line tuples).
    Returns list of (id, name, input, output, cache_read, cache_write) preserving order.
    """
    m = re.search(r"fn seed_model_pricing\b.*?let pricing_data = \[", text, re.S)
    if not m:
        sys.exit("ERROR: could not locate seed_model_pricing / pricing_data in schema.rs")
    start = m.end()
    end = text.find("];", start)
    if end < 0:
        sys.exit("ERROR: could not find end of pricing_data array")
    block = text[start:end]
    rows = re.findall(
        r'\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"'
        r'\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,?\s*\)',
        block,
    )
    if not rows:
        sys.exit("ERROR: pricing_data matched but no 6-tuples parsed — format changed?")
    return rows


def is_text_model(model_id: str, model: dict) -> bool:
    if str(model.get("status", "")).lower() == "deprecated":
        return False
    mods = model.get("modalities") or {}
    outs = [m.lower() for m in (mods.get("output") or []) if isinstance(m, str)]
    if outs and ("text" not in outs or any(m in NON_TEXT_OUTPUT for m in outs)):
        return False
    hay = f"{model_id} {model.get('name', '')}".lower()
    return not any(marker in hay for marker in NON_TEXT_MARKERS)


def cost_tuple(model: dict):
    c = model.get("cost") or {}
    def num(k):
        v = c.get(k)
        return float(v) if isinstance(v, (int, float)) else 0.0
    if not isinstance(c.get("input"), (int, float)) and not isinstance(c.get("output"), (int, float)):
        return None
    return (num("input"), num("output"), num("cache_read"), num("cache_write"))


def fmt(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def differs(seed: float, ref: float) -> bool:
    d = abs(seed - ref)
    return d > ABS_TOL and d > REL_TOL * max(abs(ref), 1e-9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180,
                    help="missing-model scan: only flag models released within N days (0 = all)")
    ap.add_argument("--api-json", type=Path, default=None,
                    help="use a local copy of models.dev api.json instead of downloading")
    args = ap.parse_args()

    if args.api_json:
        data = json.loads(args.api_json.read_text())
    else:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "cc-switch-pricing-audit"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)

    seed_rows = parse_seed_rows(SCHEMA_RS.read_text())
    seed = {}  # id -> (name, in, out, cr, cw); first occurrence wins (dup ids would be a bug)
    for rid, name, i, o, cr, cw in seed_rows:
        seed.setdefault(rid, (name, float(i), float(o), float(cr), float(cw)))

    # Known-intentional divergences (e.g. promo prices deliberately kept out of seed).
    # audit-ignore.json next to this script: { "<seed id>": "<reason>" }.
    ignore_path = Path(__file__).with_name("audit-ignore.json")
    ignored = json.loads(ignore_path.read_text()) if ignore_path.exists() else {}

    # Index models.dev: normalized id -> best (rank, provider, model_id, model)
    index = {}
    for pid, prov in data.items():
        if pid not in FIRST_PARTY_RANK:
            continue  # aggregators never supply reference prices
        for mid, model in (prov.get("models") or {}).items():
            if not isinstance(model, dict) or not is_text_model(mid, model):
                continue
            if cost_tuple(model) is None:
                continue
            nid = normalize(mid)
            rank = effective_rank(nid, pid)
            for key in claude_variants(nid):
                cur = index.get(key)
                if cur is None or rank < cur[0]:
                    index[key] = (rank, pid, mid, model)

    # --- A. price mismatches -------------------------------------------------
    mismatches, waived, absent = [], [], []
    for rid, (name, si, so, scr, scw) in seed.items():
        hit = None
        for key in claude_variants(rid):
            if key in index and (hit is None or index[key][0] < hit[0]):
                hit = index[key]
        if hit is None:
            absent.append((rid, name))
            continue
        _, pid, mid, model = hit
        ci, co, ccr, ccw = cost_tuple(model)
        diffs = []
        for label, sv, rv in (("input", si, ci), ("output", so, co),
                              ("cache_read", scr, ccr), ("cache_write", scw, ccw)):
            if differs(sv, rv):
                diffs.append(f"{label}: seed {fmt(sv)} vs {fmt(rv)}")
        if diffs:
            if rid in ignored:
                waived.append((rid, ignored[rid]))
                continue
            fx = " *(CNY-vendor: may be FX rounding)*" if pid in CNY_HINT else ""
            mismatches.append((rid, f"{pid}/{mid}", "; ".join(diffs) + fx))

    # --- B. missing recent models -------------------------------------------
    seed_keys = set()
    for rid in seed:
        seed_keys |= claude_variants(rid)
    missing = {}
    for pid in MISSING_SCAN:
        prov = data.get(pid)
        if not prov:
            continue
        for mid, model in (prov.get("models") or {}).items():
            if not isinstance(model, dict) or not is_text_model(mid, model):
                continue
            if "robotics" in mid.lower():  # not coding models
                continue
            costs = cost_tuple(model)
            if costs is None:
                continue
            nid = normalize(mid)
            if claude_variants(nid) & seed_keys:
                continue
            rel = model.get("release_date") or ""
            key = nid
            if key in missing and FIRST_PARTY_RANK[missing[key][0]] <= FIRST_PARTY_RANK[pid]:
                continue
            ctx = (model.get("limit") or {}).get("context")
            missing[key] = (pid, mid, model.get("name") or mid, rel, costs, ctx)

    cutoff = ""
    if args.days > 0:
        import datetime
        cutoff = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat()
    recent = {k: v for k, v in missing.items() if v[3] >= cutoff} if cutoff else missing
    older_count = len(missing) - len(recent)

    # --- report --------------------------------------------------------------
    print(f"# Pricing audit — seed table ({len(seed)} ids) vs models.dev\n")

    print(f"## A. Price mismatches ({len(mismatches)})\n")
    if mismatches:
        print("| seed id | models.dev ref | difference |")
        print("|---|---|---|")
        for rid, ref, d in sorted(mismatches):
            print(f"| `{rid}` | `{ref}` | {d} |")
        print("\n> models.dev is NOT automatically right — confirm against the vendor's "
              "official list price before writing seed+repair. CNY vendors: seed uses "
              "~7.14 CNY/USD, small deltas are expected.")
    else:
        print("None beyond tolerance (2% rel & $0.005/M abs).")

    if waived:
        print(f"\n### Waived — known-intentional divergences ({len(waived)})\n")
        for rid, reason in sorted(waived):
            print(f"- `{rid}`: {reason}")

    print(f"\n## B. Missing recent models — released ≥ {cutoff or 'beginning'} "
          f"({len(recent)}; +{older_count} older not shown)\n")
    if recent:
        print("| provider/model | name | released | input | output | cache_r | cache_w | context |")
        print("|---|---|---|---|---|---|---|---|")
        for nid, (pid, mid, name, rel, (ci, co, ccr, ccw), ctx) in sorted(
                recent.items(), key=lambda kv: kv[1][3], reverse=True):
            print(f"| `{pid}/{mid}` | {name} | {rel or '?'} | {fmt(ci)} | {fmt(co)} "
                  f"| {fmt(ccr)} | {fmt(ccw)} | {ctx or '?'} |")
        print("\n> Candidates, not automatic additions — CC Switch only seeds models its "
              "users actually route (coding-relevant). Skip niche/preview SKUs deliberately.")
    else:
        print("None — seed table covers all recent first-party releases in scope.")

    print(f"\n## C. Seed rows with no models.dev entry ({len(absent)}) — informational\n")
    if absent:
        for rid, name in sorted(absent):
            print(f"- `{rid}` ({name})")
        print("\n> Expected for tier-suffixed rows (e.g. `-low`), gateway-only ids, and "
              "vendors models.dev doesn't track. Not errors.")


if __name__ == "__main__":
    main()
