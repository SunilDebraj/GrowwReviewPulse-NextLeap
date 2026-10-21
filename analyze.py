"""Step 1 — Review Intelligence Layer.

Reads a reviews CSV, clusters reviews into at most 5 themes, ranks the top 3,
picks 3 representative real quotes, and detects the most frequently
misunderstood fee/charge. Writes out/insights.json and out/reviews_labelled.csv.

Deterministic (lexicon + scoring), so every weekly run is reproducible and each
theme assignment can be audited row by row in reviews_labelled.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent

# ---------------------------------------------------------------------------
# Theme lexicon (max 5 themes). Built by reading the full review set once,
# then frozen so week-on-week numbers stay comparable.
# ---------------------------------------------------------------------------
THEMES = {
    "reliability": {
        "label": "App reliability: update regressions, charts & order glitches",
        "short": "App reliability",
        "patterns": [
            r"\bupdat(e|ed|es|ing)\b", r"\bbug", r"glitch", r"\blag", r"\bslow\b",
            r"\bhang", r"\bstuck\b", r"crash", r"\bfreez", r"not (opening|loading|working)",
            r"\bchart", r"\bcandle", r"scalp", r"back button", r"navigation",
            r"\brefresh", r"\bindicator", r"stop ?loss", r"\bsl\b", r"square ?off",
            r"(not|wasn't) executed", r"\bexecution\b", r"position", r"\bbuffering\b",
            r"not updat",
        ],
    },
    "support": {
        "label": "Customer support hard to reach / issues unresolved",
        "short": "Customer support",
        "patterns": [
            r"customer (care|support|service)", r"\bsupport\b", r"help ?line",
            r"\bon hold\b", r"\bhold for\b", r"\bticket", r"\bagents?\b",
            r"no (one )?(reply|response|respond)", r"not (responding|respond)",
            r"\bcall back\b", r"chat (support|option|service)", r"\bivr\b",
            r"\bmailed\b", r"waiting .*connect", r"\bai (bot|chatbot|help)\b",
        ],
    },
    "charges": {
        "label": "Charges & deductions not understood (brokerage, 'external charges & taxes', DP)",
        "short": "Charges & deductions",
        "patterns": [
            r"\bcharg(e|es|ed|ing)\b", r"brokerage", r"brokarage", r"brockerage",
            r"\bfees?\b", r"\bdp\b", r"\bdeduct", r"\btax(es)?\b", r"\bgst\b",
            r"\bstt\b", r"hidden", r"commission", r"haircut", r"\binterest\b",
            r"\bpenalty\b",
        ],
    },
    "account_money": {
        "label": "Account, KYC & money movement (activation, withdrawals, payments)",
        "short": "Account & money movement",
        "patterns": [
            r"\bkyc\b", r"account (opening|activation|reactivat|closure|is|blocked|details|creation)",
            r"(activate|reactivat|deactivat)", r"withdraw", r"\bredeem|redemption",
            r"\bpayment", r"\bupi\b", r"mandate", r"\brefund", r"\bpan\b", r"aadh?ar",
            r"e-?mail (id|address)", r"\bblocked\b", r"demat account", r"journey reset",
            r"allow permission", r"\blog ?in\b",
        ],
    },
    "ease_of_use": {
        "label": "Praise: simple, beginner-friendly investing",
        "short": "Ease of use (praise)",
        "patterns": [
            r"easy", r"simple", r"user[- ]?friendly", r"beginner", r"smooth",
            r"\bclean\b", r"intuitive", r"\bbest\b", r"\bgreat\b", r"excellent",
            r"\bnice\b", r"\bgood app\b", r"convenient",
        ],
        "min_rating": 4,  # praise only counts on 4–5★ reviews
    },
}

# Candidate fees/charges a user could be confused about.
FEE_TERMS = {
    "external_charges": [
        r"external charge", r"\btax(es)?\b", r"\bgst\b", r"\bstt\b",
        r"hidden charge", r"other charges", r"deduction", r"\bdeduct",
    ],
    "brokerage": [r"brokerage", r"brokarage", r"brockerage", r"per order"],
    "dp_charge": [r"\bdp\b", r"selling stocks", r"sell order", r"delivery sell"],
    "mtf_interest": [r"\bmtf\b", r"haircut"],
    "service_fees": [r"\bddpi\b", r"change ur email"],
}
FEE_LABELS = {
    "external_charges": "\"External charges & taxes\" deducted on top of brokerage",
    "brokerage": "Brokerage per executed order",
    "dp_charge": "DP charge on delivery sells",
    "mtf_interest": "MTF interest / haircut",
    "service_fees": "Account-service fees (DDPI, email change)",
}
# Signals that the reviewer does not understand the charge (vs. just finds it high).
CONFUSION_CUES = [
    r"not (clear|easy to understand)", r"don'?t know", r"donot know", r"hidden",
    r"without (any|ur|your) (information|use|knowledge)", r"\bwhy\b", r"\?",
    r"more th[ae]n (they|you) mention", r"you mentioned", r"not (clearly )?(informed|disclosed)",
    r"bla bla", r"silently", r"unexpected", r"misleading", r"expected",
]
REGRESSION = r"scalp|navigation|back button"


def load(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["rating"] = int(r["rating"])
        r["helpful_count"] = int(r.get("helpful_count") or 0)
        r["_t"] = r["text"].lower()
    return rows


def hits(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if re.search(p, text))


def assign_themes(rows: list[dict]) -> None:
    for r in rows:
        scores = {}
        for key, spec in THEMES.items():
            if r["rating"] < spec.get("min_rating", 0):
                continue
            s = hits(r["_t"], spec["patterns"])
            if s:
                scores[key] = s
        r["themes"] = sorted(scores, key=scores.get, reverse=True)
        r["primary_theme"] = r["themes"][0] if r["themes"] else "other"


def pick_quote(rows: list[dict], theme: str, must: list[str]) -> dict:
    """Most representative real quote: on-theme, low-star for issue themes,
    readable length, helpful votes as tie-breaker."""
    pool = [r for r in rows if r["primary_theme"] == theme]
    pool = [r for r in pool if all(re.search(m, r["_t"]) for m in must)] or pool

    def score(r):
        th = hits(r["_t"], THEMES[theme]["patterns"])
        tone = (5 - r["rating"]) if theme != "ease_of_use" else r["rating"]
        return (th >= 2, 80 <= len(r["text"]) <= 420, tone, r["helpful_count"], th)

    return max(pool, key=score)


def excerpt(text: str, anchor: str, max_words: int = 22) -> str:
    """The sentence containing the anchor, trimmed to max_words (verbatim)."""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if re.search(anchor, s.lower()):
            w = s.split()
            if len(w) > max_words:
                return " ".join(w[:max_words]) + " …"
            return s
    return " ".join(text.split()[:max_words]) + " …"


def detect_fee(rows: list[dict]) -> dict:
    charge_rows = [r for r in rows if "charges" in r["themes"]]
    mentions, confused, evidence = Counter(), Counter(), defaultdict(list)
    for r in charge_rows:
        is_confused = hits(r["_t"], CONFUSION_CUES) > 0
        for fee, pats in FEE_TERMS.items():
            if hits(r["_t"], pats):
                mentions[fee] += 1
                if is_confused:
                    confused[fee] += 1
                    evidence[fee].append(r)
    # We want the most *misunderstood* fee, so rank by confusion signal first.
    ranked = sorted(mentions, key=lambda f: (confused[f], mentions[f]), reverse=True)
    top = ranked[0]
    # Example quote: the shortest verbatim sentence that names the charge.
    named = [r for r in evidence[top] if re.search(r"external charge", r["_t"])] or evidence[top]
    example = min(named, key=lambda r: len(excerpt(r["text"], r"external charge")))
    return {
        "fee_key": top,
        "fee": FEE_LABELS[top],
        "mentions": mentions[top],
        "mentions_with_confusion_cue": confused[top],
        "charges_theme_reviews": len(charge_rows),
        "all_fee_counts": {FEE_LABELS[f]: {"mentions": mentions[f], "confused": confused[f]} for f in ranked},
        "example_quote": {"review_id": example["review_id"], "date": example["date"],
                          "rating": example["rating"], "excerpt": excerpt(example["text"], r"external charge")},
        "evidence_review_ids": [r["review_id"] for r in evidence[top]],
    }


def run(csv_path: Path) -> tuple[dict, list[dict]]:
    rows = load(csv_path)
    assign_themes(rows)
    n = len(rows)

    theme_stats = []
    for key, spec in THEMES.items():
        members = [r for r in rows if key in r["themes"]]
        if not members:
            continue
        low = sum(r["rating"] <= 2 for r in members)
        theme_stats.append({
            "key": key, "label": spec["label"], "short": spec["short"],
            "reviews_mentioning": len(members),
            "share_pct": round(100 * len(members) / n, 1),
            "primary_count": sum(r["primary_theme"] == key for r in rows),
            "avg_rating": round(sum(r["rating"] for r in members) / len(members), 2),
            "low_star_reviews": low,
            "low_star_pct": round(100 * low / len(members), 1),
        })
    # Rank by volume of 1–2★ reviews: the pulse tracks what is hurting users.
    theme_stats.sort(key=lambda t: (t["low_star_reviews"], t["reviews_mentioning"]), reverse=True)
    top3 = theme_stats[:3]

    weekly = defaultdict(Counter)
    for r in rows:
        y, w, _ = date.fromisoformat(r["date"]).isocalendar()
        tag = f"{y}-W{w:02d}"
        weekly[tag]["_total"] += 1
        for t in r["themes"]:
            weekly[tag][t] += 1

    # Peak week for the #1 theme (weeks with at least 30 reviews, to avoid noise).
    lead = top3[0]["key"]
    peak = max((k for k, v in weekly.items() if v["_total"] >= 30),
               key=lambda k: weekly[k][lead] / weekly[k]["_total"])
    y, w = int(peak[:4]), int(peak[-2:])
    peak_info = {"week": peak, "start": date.fromisocalendar(y, w, 1).isoformat(),
                 "end": date.fromisocalendar(y, w, 7).isoformat(),
                 "share_pct": round(100 * weekly[peak][lead] / weekly[peak]["_total"])}

    reg = [r for r in rows if re.search(REGRESSION, r["_t"])]
    regression = {"pattern": REGRESSION, "reviews": len(reg), "low_star": sum(r["rating"] <= 2 for r in reg)}

    quote_specs = {
        "reliability": ([r"scalp"], r"scalp"),
        "support": ([r"hold"], r"hold"),
        "charges": ([r"deduct", r"not clear"], r"not clear"),
        "account_money": ([r"withdraw"], r"withdraw"),
        "ease_of_use": ([r"beginner"], r"beginner"),
    }
    quotes = []
    for t in top3:
        must, anchor = quote_specs[t["key"]]
        r = pick_quote(rows, t["key"], must)
        quotes.append({"theme": t["short"], "review_id": r["review_id"], "date": r["date"],
                       "rating": r["rating"], "excerpt": excerpt(r["text"], anchor)})

    ratings = Counter(r["rating"] for r in rows)
    dates = sorted(r["date"] for r in rows)
    praise = next(t for t in theme_stats if t["key"] == "ease_of_use")
    insights = {
        "product": "Groww (com.nextbillion.groww)",
        "source": "Google Play Store, India, English — public reviews",
        "window": {"from": dates[0], "to": dates[-1], "reviews": n},
        "rating_mix": {str(k): ratings[k] for k in sorted(ratings)},
        "low_star_pct": round(100 * (ratings[1] + ratings[2]) / n),
        "ranking_rule": "Top 3 = themes with the most 1–2★ reviews (pain volume); ties broken by total mentions.",
        "themes": theme_stats,
        "top_3_themes": [t["label"] for t in top3],
        "praise": {"reviews": praise["reviews_mentioning"], "share_pct": praise["share_pct"],
                   "avg_rating": praise["avg_rating"]},
        "quotes": quotes,
        "lead_theme_peak": peak_info,
        "regression_signal": regression,
        "fee_issue": detect_fee(rows),
        "weekly_counts": {k: dict(v) for k, v in sorted(weekly.items())},
    }
    return insights, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(ROOT / "data" / "groww_playstore_reviews.csv"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    args = ap.parse_args()

    insights, rows = run(Path(args.csv))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "insights.json").write_text(json.dumps(insights, indent=2, ensure_ascii=False))
    with (out / "reviews_labelled.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "date", "rating", "primary_theme", "all_themes", "text"])
        for r in rows:
            w.writerow([r["review_id"], r["date"], r["rating"], r["primary_theme"], "|".join(r["themes"]), r["text"]])

    for t in insights["themes"]:
        print(f"{t['short']:<26} {t['reviews_mentioning']:>4} reviews  {t['avg_rating']}★  {t['low_star_reviews']} low-star")
    print("Top 3:", insights["top_3_themes"])
    print("Fee issue:", insights["fee_issue"]["fee"])


if __name__ == "__main__":
    main()
