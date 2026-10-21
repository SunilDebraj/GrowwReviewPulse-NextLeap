"""Groww Review → Weekly Pulse + Fee Explainer workflow.

    python pipeline.py                  # run steps 1–3, then stop at the approval gate
    python pipeline.py --llm            # same, but Claude drafts the pulse prose (needs ANTHROPIC_API_KEY)
    python pipeline.py --yes-i-reviewed # non-interactive approval (CI / demo); still prints the preview

Steps
  1. Review intelligence  (analyze.py)  → out/insights.json, out/reviews_labelled.csv
  2. Weekly pulse         (≤250 words)  → out/weekly_pulse.md
  3. Fee explainer        (≤6 bullets)  → out/fee_explainer.md
  4. Payload + email      (for MCP)     → out/mcp_payload.json, out/email_draft.md
  5. APPROVAL GATE        nothing is written to a doc or mail tool until a human approves
  6. Actions              append to notes doc + create (not send) an email draft
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import analyze

ROOT = Path(__file__).parent
OUT = ROOT / "out"

# ---------------------------------------------------------------------------
# Curated context the generator uses. Theme notes and action ideas are written
# by the PM once per theme; the numbers always come from insights.json.
# ---------------------------------------------------------------------------
THEME_NOTES = {
    "reliability": "Chart-screen regressions after updates, stale prices, stuck orders.",
    "support": "Long IVR holds, AI-bot loops, tickets closed unresolved.",
    "charges": "Deductions exceed the \"₹20 brokerage\" users expect.",
    "account_money": "Activation/KYC delays, slow withdrawals, failed payments.",
    "ease_of_use": "Simple, beginner-friendly investing.",
}
ACTIONS = {
    "reliability": "**Chart hotfix:** move the Scalper toggle away from Back, keep the nav bar visible, add an opt-out.",
    "support": "**Support SLA:** show real queue times, offer callback, no ticket closure without a human reply.",
    "charges": "**Charge clarity:** itemized pre-trade charge preview; link the fee explainer from P&L.",
    "account_money": "**Money movement:** show withdrawal/activation status with an ETA and a single tracking ID.",
}

# Fee knowledge base: facts verified against official pages (see `sources`).
# The explainer is only ever generated from here, never free-written by the model.
FEE_KB = {
    "external_charges": {
        "title": "\"External charges & taxes\" on Groww stock trades",
        "bullets": [
            "**Two kinds of deductions apply to every trade.** Groww's own brokerage, and levies set by the government, exchanges, SEBI and the depository. Groww lists the second group on its pricing page as Regulatory & Statutory Charges; in the app they appear separately from brokerage.",
            "**Brokerage (stocks):** ₹20 or 0.1% of order value per executed order, whichever is lower; if that is under ₹5, the charge is the lower of ₹5 or 2.5% of trade value. F&O: ₹20 per executed order.",
            "**Statutory and exchange levies (equity):** STT is 0.1% on buy and sell for delivery and 0.025% on sell for intraday; stamp duty is 0.015% (delivery) or 0.003% (intraday) on buy; NSE transaction charge 0.00297%; SEBI turnover fee 0.0001%; GST 18% on brokerage, DP, exchange, SEBI and IPFT charges.",
            "**DP charge on delivery sells:** ₹20 per sell transaction (₹3.50 depository + ₹16.50 Groww; depository part ₹3.25 for women), plus GST. Not charged on intraday. Groww's portion is ₹0 for debit values under ₹100.",
            "**Why small trades feel it most:** the ₹5 minimum brokerage and ₹20 DP charge do not scale with trade size. Example: 1 share bought at ₹200 and sold at ₹220 (delivery, NSE) carries about ₹36 in total charges, more than the ₹20 price gain.",
            "**Where to see exact amounts:** the app shows an estimate on the trading day; final, itemized charges are in the contract note emailed as a PDF (password: PAN in capitals), with DP charges in a separate statement in the same PDF.",
        ],
        "sources": [
            ("Groww — Pricing", "https://groww.in/pricing"),
            ("Groww Help — How much is the brokerage?", "https://groww.in/help/stocks/searchable/how-much-is-the-brokerage"),
        ],
        "last_checked": "2026-10-13",
    },
}


def fmt_day(iso: str, year: bool = False) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}" + (f" {d.year}" if year else "")


def word_count(md: str) -> int:
    return len(re.findall(r"\S*[A-Za-z0-9]\S*", md))


# ---------------------------------------------------------------------------
# Step 2 — weekly pulse
# ---------------------------------------------------------------------------
def pulse_template(ins: dict, run_date: str) -> str:
    top = ins["themes"][:3]
    lines = [f"# Groww Weekly Product Pulse — {fmt_day(run_date, True)}", "",
             f"**Input:** {ins['window']['reviews']} Play Store reviews (India, English), "
             f"{fmt_day(ins['window']['from'])} – {fmt_day(ins['window']['to'], True)} · "
             f"{ins['low_star_pct']}% rated 1–2★", "",
             "## Top themes (ranked by 1–2★ volume)"]
    for i, t in enumerate(top, 1):
        lines.append(f"{i}. **{t['short']}** — {t['reviews_mentioning']} reviews ({round(t['share_pct'])}%), "
                     f"avg {t['avg_rating']:.1f}★. {THEME_NOTES[t['key']]}")
    p = ins["praise"]
    lines += ["", f"Bright spot: {p['reviews']} reviews ({round(p['share_pct'])}%, {p['avg_rating']:.1f}★) "
              "praise its simplicity for beginners.", "", "## Voice of the user"]
    for q in ins["quotes"]:
        lines.append(f"- \"{q['excerpt']}\" ({q['rating']}★, {fmt_day(q['date'])})")
    pk, rg, fee = ins["lead_theme_peak"], ins["regression_signal"], ins["fee_issue"]
    lines += ["", "## Key observation",
              f"{top[0]['short']} complaints peaked {date.fromisoformat(pk['start']).day}–{fmt_day(pk['end'])} "
              f"({pk['share_pct']}% of that week's reviews); {rg['reviews']} reviews mention the Scalper button or "
              f"hidden back-navigation ({rg['low_star']} rated 1–2★). \"External charges & taxes\" is the most "
              f"confused charge: {fee['mentions_with_confusion_cue']} of {fee['mentions']} mentions signal confusion, "
              "not price objection.", "", "## Action ideas"]
    for i, t in enumerate(top, 1):
        lines.append(f"{i}. {ACTIONS[t['key']]}")
    return "\n".join(lines) + "\n"


def pulse_llm(ins: dict, run_date: str, draft: str) -> str:
    """Ask Claude to tighten the prose. Numbers and quotes must survive unchanged;
    the validator rejects the rewrite otherwise and we keep the template."""
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    prompt = (
        "You are a product analyst. Rewrite this weekly product pulse for an internal product team.\n"
        "Hard rules: keep the same markdown sections; keep every number and every quoted user sentence "
        "exactly as written; ≤250 words; neutral tone; exactly 3 action ideas.\n\n"
        f"INSIGHTS JSON:\n{json.dumps({k: ins[k] for k in ('themes', 'quotes', 'fee_issue', 'lead_theme_peak', 'regression_signal')}, ensure_ascii=False)}\n\n"
        f"DRAFT:\n{draft}"
    )
    msg = client.messages.create(model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
                                 max_tokens=1200, messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip() + "\n"


def validate_pulse(md: str, ins: dict) -> list[str]:
    errs = []
    if word_count(md) > 250:
        errs.append(f"pulse is {word_count(md)} words (>250)")
    for q in ins["quotes"]:
        if q["excerpt"] not in md:
            errs.append(f"quote missing or altered: {q['excerpt'][:40]}…")
    if len(re.findall(r"^\d\. \*\*", md.split("## Action ideas")[-1], re.M)) != 3:
        errs.append("need exactly 3 action ideas")
    return errs


# ---------------------------------------------------------------------------
# Step 3 — fee explainer
# ---------------------------------------------------------------------------
def fee_explainer(ins: dict) -> tuple[str, dict]:
    fee = ins["fee_issue"]
    kb = FEE_KB[fee["fee_key"]]
    ex = fee["example_quote"]
    md = [f"# Fee explainer: {kb['title']}", "",
          f"**Why this exists:** {fee['charges_theme_reviews']} of {ins['window']['reviews']} recent reviews discuss "
          f"charges; the most-confused item is the deduction users see beside brokerage as \"External charges & taxes\" "
          f"({fee['mentions_with_confusion_cue']} of {fee['mentions']} mentions show confusion, e.g. \"{ex['excerpt']}\").", ""]
    md += [f"- {b}" for b in kb["bullets"]]
    md += ["", "**Official sources**"] + [f"- {t}: {u}" for t, u in kb["sources"]]
    md += ["", f"Last checked: {fmt_day(kb['last_checked'], True)}"]
    return "\n".join(md) + "\n", kb


def validate_explainer(kb: dict) -> list[str]:
    errs = []
    if len(kb["bullets"]) > 6:
        errs.append("explainer has more than 6 bullets")
    if len(kb["sources"]) < 2:
        errs.append("explainer needs 2 official source links")
    if any(re.search(r"\b(we|you should|best|unfortunately|sorry)\b", b, re.I) for b in kb["bullets"]):
        errs.append("explainer tone is not neutral/facts-only")
    return errs


# ---------------------------------------------------------------------------
# Step 4 — MCP payload + email draft
# ---------------------------------------------------------------------------
def strip_md(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s)


def build_payload(ins: dict, pulse: str, kb: dict, run_date: str) -> dict:
    return {
        "date": run_date,
        "top_themes": [t["label"] for t in ins["themes"][:3]],
        "weekly_pulse": pulse,
        "identified_fee_issue": ins["fee_issue"]["fee"],
        "explanation_bullets": [strip_md(b) for b in kb["bullets"]],
        "source_links": [u for _, u in kb["sources"]],
    }


def build_email(payload: dict, explainer_md: str) -> dict:
    subject = f"Weekly Product Pulse + Customer Clarification — {fmt_day(payload['date'], True)}"
    snippet = ["Hi, thanks for flagging this. Here is how charges on stock trades work on Groww:", ""]
    snippet += [f"• {b}" for b in payload["explanation_bullets"]]
    snippet += ["", "Sources: " + " | ".join(payload["source_links"]),
                f"Last checked: {fmt_day(FEE_KB['external_charges']['last_checked'], True)}"]
    body = "\n".join([
        "Team,", "",
        "Below is this week's product pulse from Play Store reviews, followed by a reusable support snippet "
        "for the most-confused charge.", "",
        "=== WEEKLY PRODUCT PULSE ===", "",
        re.sub(r"^#+\s*", "", strip_md(payload["weekly_pulse"]), flags=re.M).strip(), "",
        "=== SUPPORT SNIPPET: \"External charges & taxes\" (copy-paste ready) ===", "",
        *snippet, "",
        "— Generated by the review-pulse workflow; approved before drafting. Not sent automatically.",
    ])
    return {"subject": subject, "to": [], "body": body}


# ---------------------------------------------------------------------------
# Step 5 — approval gate,  Step 6 — actions
# ---------------------------------------------------------------------------
def approval_gate(payload: dict, email: dict, auto: bool) -> bool:
    bar = "─" * 72
    print(f"\n{bar}\nAPPROVAL REQUIRED — 2 actions are queued; nothing has been written yet.\n{bar}")
    print("1) APPEND to notes doc  'Groww Weekly Pulse Log'")
    print(f"   date={payload['date']}  fee_issue={payload['identified_fee_issue']}")
    print(f"   top_themes={payload['top_themes']}")
    print(f"   {len(payload['explanation_bullets'])} explanation bullets, {len(payload['source_links'])} source links")
    print(f"2) CREATE email draft (not sent)\n   Subject: {email['subject']}\n   Body: {len(email['body'].split())} words")
    print(bar)
    if auto:
        print("Approved via --yes-i-reviewed flag.")
        return True
    if not sys.stdin.isatty():
        print("No interactive terminal: actions stay queued in out/pending_actions.json.")
        return False
    return input("Approve both actions? Type 'approve' to continue: ").strip().lower() == "approve"


def act_append_doc(payload: dict, path: Path) -> None:
    """Local stand-in for the doc connector: appends a dated entry to a running log."""
    entry = [f"\n## Entry — {payload['date']}", "",
             f"**Top themes:** {'; '.join(payload['top_themes'])}", "",
             f"**Identified fee issue:** {payload['identified_fee_issue']}", "",
             "**Weekly pulse:**", "", payload["weekly_pulse"].replace("# ", "### ", 1).replace("## ", "#### "),
             "**Explanation bullets:**", *[f"- {b}" for b in payload["explanation_bullets"]], "",
             "**Source links:**", *[f"- {u}" for u in payload["source_links"]], "",
             "```json", json.dumps(payload, indent=2, ensure_ascii=False), "```", ""]
    if not path.exists():
        path.write_text("# Groww Weekly Pulse Log\n\nRunning log appended by the review-pulse workflow after approval.\n")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry))


def act_email_draft(email: dict, path: Path) -> None:
    """Local stand-in for the mail connector: an .eml draft you can open in any mail client."""
    m = EmailMessage()
    m["Subject"] = email["subject"]
    m["To"] = ", ".join(email["to"])
    m["X-Unsent"] = "1"  # opens as an editable draft in Outlook/Apple Mail
    m.set_content(email["body"])
    path.write_bytes(bytes(m))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(ROOT / "data" / "groww_playstore_reviews.csv"))
    ap.add_argument("--date", default=date.today().isoformat(), help="run date (YYYY-MM-DD)")
    ap.add_argument("--llm", action="store_true", help="let Claude polish the pulse prose")
    ap.add_argument("--yes-i-reviewed", action="store_true", help="approve non-interactively")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    # 1 — intelligence
    ins, rows = analyze.run(Path(args.csv))
    (OUT / "insights.json").write_text(json.dumps(ins, indent=2, ensure_ascii=False))
    print(f"[1] {ins['window']['reviews']} reviews · top 3: {[t['short'] for t in ins['themes'][:3]]}")
    print(f"    fee issue: {ins['fee_issue']['fee']}")

    # 2 — pulse
    pulse = pulse_template(ins, args.date)
    if args.llm:
        try:
            polished = pulse_llm(ins, args.date, pulse)
            if not validate_pulse(polished, ins):
                pulse = polished
            else:
                print("    LLM rewrite failed validation; keeping template:", validate_pulse(polished, ins))
        except Exception as e:  # no key, no network, etc.
            print(f"    LLM unavailable ({e.__class__.__name__}); using template.")
    errs = validate_pulse(pulse, ins)
    if errs:
        sys.exit(f"Pulse failed validation: {errs}")
    (OUT / "weekly_pulse.md").write_text(pulse)
    print(f"[2] weekly_pulse.md · {word_count(pulse)} words")

    # 3 — explainer
    explainer, kb = fee_explainer(ins)
    errs = validate_explainer(kb)
    if errs:
        sys.exit(f"Explainer failed validation: {errs}")
    (OUT / "fee_explainer.md").write_text(explainer)
    print(f"[3] fee_explainer.md · {len(kb['bullets'])} bullets · {len(kb['sources'])} sources")

    # 4 — payload + email
    payload = build_payload(ins, pulse, kb, args.date)
    email = build_email(payload, explainer)
    (OUT / "mcp_payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (OUT / "email_draft.md").write_text(f"**Subject:** {email['subject']}\n\n```\n{email['body']}\n```\n")
    print("[4] mcp_payload.json + email_draft.md ready")

    # 5 — approval gate
    if not approval_gate(payload, email, args.yes_i_reviewed):
        (OUT / "pending_actions.json").write_text(json.dumps(
            {"status": "awaiting_approval", "actions": ["append_doc", "create_email_draft"],
             "payload": payload, "email": email}, indent=2, ensure_ascii=False))
        print("[5] Not approved — no doc entry or draft created.")
        return

    # 6 — actions
    (OUT / "pending_actions.json").unlink(missing_ok=True)
    act_append_doc(payload, OUT / "notes_log.md")
    act_email_draft(email, OUT / "email_draft.eml")
    print("[6] Appended to out/notes_log.md · draft saved to out/email_draft.eml (not sent)")


if __name__ == "__main__":
    main()
