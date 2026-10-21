# Groww Review Pulse

An AI workflow that turns raw Play Store reviews for **Groww** (the product picked in Milestone 1) into
(1) a weekly internal product pulse and (2) a standardized, support-ready explanation of the fee users
misunderstand most — then, **only after a person approves**, logs the result to a doc and creates an
email draft through MCP.

**Live prototype (free, GitHub Pages):** https://sunildebraj.github.io/GrowwReviewPulse-NextLeap/
**Repository:** https://github.com/SunilDebraj/GrowwReviewPulse-NextLeap

Everything here is free: the web prototype runs entirely in the browser, the Python pipeline needs no packages,
and the n8n workflow runs on self-hosted n8n with a free LLM (Gemini free tier or Ollama).

| Version | Where | Approval → actions |
|---|---|---|
| Web prototype | [GitHub Pages](https://sunildebraj.github.io/GrowwReviewPulse-NextLeap/) (`docs/index.html`) | Approve → entry saved to the Pulse log in your browser (downloadable) + Gmail compose window opens pre-filled (kept in Drafts, never sent) |
| n8n workflow | `n8n/groww_review_pulse.n8n.json` | Approve button in an email → real Google Doc append + Gmail draft |
| Python CLI | `pipeline.py` | `approve` at the prompt → `out/notes_log.md` + `out/email_draft.eml` |
| Claude session (original run) | [Claude Docs log](https://claude.ai/code/artifact/4cdb319c-bb5b-4e1c-a223-ecbca8274bcd) | Claude Docs MCP append + Gmail MCP draft (see `out/mcp_actions_log.json`) |

## Fee issue identified from the reviews

**"External charges & taxes" deducted on top of brokerage.**
71 of 500 reviews (14%) discuss charges, 68% of them rated 1–2★. Among the candidate charges, this one carries the
most confusion cues ("why", "don't know", "not clear", "hidden"): 16 of its 24 mentions. Users expect "₹20 brokerage"
and do not recognise the separate statutory levies (STT, stamp duty, exchange, SEBI, IPFT, GST) and the ₹20 DP
charge on delivery sells. Example review: *"I donot know what kind of external charges and tax they are taking"* (1★).

| Candidate charge | Mentions | With confusion cue |
|---|---:|---:|
| **"External charges & taxes"** | **24** | **16** |
| Brokerage per order | 27 | 5 |
| DP charge on delivery sells | 5 | 1 |
| Account-service fees (DDPI, email change) | 1 | 1 |
| MTF interest / haircut | 2 | 0 |

## Results (run of 13 Oct 2026)

| Theme | Reviews | Share | Avg ★ | 1–2★ reviews |
|---|---:|---:|---:|---:|
| 1. App reliability (update regressions, charts, order glitches) | 189 | 38% | 2.4 | 107 |
| 2. Customer support hard to reach | 99 | 20% | 1.4 | 85 |
| 3. Charges & deductions not understood | 71 | 14% | 2.1 | 48 |
| Account, KYC & money movement | 65 | 13% | 2.1 | 44 |
| Praise: simple, beginner-friendly | 144 | 29% | 4.8 | 0 |

Top 3 = the themes with the most 1–2★ reviews. Outputs: [`out/weekly_pulse.md`](out/weekly_pulse.md) (247 words) and
[`out/fee_explainer.md`](out/fee_explainer.md) (6 bullets, 2 official links, "Last checked: 13 Oct 2026").

## How to run

Requires Python 3.10+. No packages needed for the default run.

```bash
python pipeline.py --date 2026-10-13          # steps 1–4, then stops at the approval prompt
python pipeline.py --csv path/to/reviews.csv   # any CSV with date, rating, text columns
python pipeline.py --llm                       # optional: Claude polishes the pulse prose
                                               #   (pip install anthropic; set ANTHROPIC_API_KEY;
                                               #    the rewrite is kept only if it passes the same checks)
python analyze.py                              # step 1 only → out/insights.json + out/reviews_labelled.csv
python prototype/build.py                      # rebuild the single-file prototype from template + engine + CSV
```

**On n8n, free:** import `n8n/groww_review_pulse.n8n.json` into a self-hosted n8n. It needs no subscriptions:
reviews come straight from Google Play (or a CSV upload) and the LLM is the Gemini free tier or Ollama on your
computer. See [`n8n/README_n8n.md`](n8n/README_n8n.md). Tested on n8n 2.43.7 against mock Google Play and LLM servers.

At the prompt, type `approve` to run the two actions; anything else leaves them queued in `out/pending_actions.json`.
`--yes-i-reviewed` approves non-interactively for demos and CI (the preview is still printed).

The prototype needs nothing installed: open the link, or load your own CSV with **Load another reviews CSV**.
Its JavaScript engine (`prototype/engine.js`) is a port of the Python and produces byte-identical pulse, payload and
email for the bundled CSV.

## Where MCP approval happens

Nothing is written to a doc or a mail tool before a person approves. There are three entry points, all gated:

1. **Claude session (the real run, 13 Oct 2026).** After both outputs were generated, Claude asked for approval with
   four options (approve both / doc only / email only / reject). On "Approve both", Claude called the
   **Claude Docs MCP** (`batch` to create *Groww Weekly Pulse Log*, `update` to append the entry) and the
   **Gmail MCP** (`create_draft`; no recipients, never sent). Evidence: [`out/mcp_actions_log.json`](out/mcp_actions_log.json),
   [`out/doc_export_groww_weekly_pulse_log.md`](out/doc_export_groww_weekly_pulse_log.md) (exported from the doc),
   [`out/email_draft.md`](out/email_draft.md). Gmail draft id `r-45172299571440378`.
2. **Prototype page, Step 4 "Approval required".** The page shows both queued actions with full previews (entry
   JSON, email body) and an **Approve and run** / **Reject** pair. On approval it creates the Gmail draft through the
   viewer's own Gmail connector (MCP `create_draft`; the viewer is asked to allow Gmail the first time) and appends the
   entry to the page's shared **Pulse log**. Claude Docs cannot be written from a page, so the prototype's "doc" is
   that shared log. Done actions lock so a retry never duplicates a draft or an entry.
3. **CLI, `pipeline.py` → `approval_gate()`.** Prints the queued actions and waits for `approve`. The CLI's adapters
   append to `out/notes_log.md` and save `out/email_draft.eml` (opens as an unsent draft in Outlook or Apple Mail).

4. **n8n, *Ask approver (wait)* node.** The run pauses and emails the approver the pulse, explainer and checks with
   **Approve** / **Reject** buttons (Gmail *Send and wait for response*). Only Approve continues to *Append entry to
   Google Doc* and *Create Gmail draft*; Reject or a 3-day timeout writes nothing.

Entry fields written by every path: `date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links`.

## How the analysis works

- **Input:** 500 public reviews, Google Play India, English, 21 Jul – 19 Sep 2026 (about 8.5 weeks), exported with
  Apify sorted by relevance. The free tier caps one export at 500 reviews, so weekly counts describe this sample,
  not Groww's total review volume.
- **Themes (max 5):** a fixed lexicon per theme, written after reading all 500 reviews and then frozen so weekly runs
  stay comparable. A review can match several themes; its primary theme is the one with the most hits. Praise only
  counts on 4–5★ reviews. Every assignment is auditable in `out/reviews_labelled.csv`.
- **Top 3:** ranked by the number of 1–2★ reviews mentioning the theme.
- **Quotes:** one real review per top theme, picked for being on-theme, low-star, readable length and most-helpful,
  then trimmed to a verbatim sentence. The validator rejects any pulse whose quotes don't match the CSV exactly.
- **Fee detection:** within the charges theme, each candidate charge is counted, and counted again when the review
  carries a confusion cue. The most-confused charge wins, so the explainer targets misunderstanding rather than price
  complaints.
- **Fee explainer:** generated only from a fee knowledge base whose facts were checked against official pages
  (see [`SOURCES.md`](SOURCES.md)); the model never free-writes fee facts. Checks: ≤6 bullets, 2 official links,
  neutral wording, a "Last checked" date. The worked example (1 share, ₹200 → ₹220, delivery) is recomputed by the
  prototype's contract-note calculator: ≈₹35.87 in charges against a ₹20 price gain.

## Files

| Path | What it is |
|---|---|
| `data/groww_playstore_reviews.csv` | Reviews CSV sample (500 rows: review_id, date, rating, app_version, helpful_count, source, text) |
| `analyze.py` | Step 1: themes, top 3, quotes, fee detection |
| `pipeline.py` | Steps 2–6: pulse, explainer, payload, email, approval gate, actions |
| `prototype/` | `engine.js` (browser port), `template.html`, `build.py` (builds both pages) |
| `docs/index.html` | The live web prototype served by GitHub Pages |
| `n8n/` | `groww_review_pulse.n8n.json` (importable workflow), `build_workflow.py`, `README_n8n.md` |
| `out/weekly_pulse.md` | Weekly product pulse (≤250 words) |
| `out/fee_explainer.md` | Fee explainer (≤6 bullets, 2 official links, Last checked) |
| `out/mcp_payload.json` | The structured entry appended to the doc |
| `out/doc_export_groww_weekly_pulse_log.md` | The appended entry, exported from the Claude Docs log |
| `out/email_draft.md` / `.eml` | Email draft text (subject + body) |
| `out/mcp_actions_log.json` | Approval decision and the two MCP calls with their results |
| `out/insights.json`, `out/reviews_labelled.csv` | Full analysis output and per-review labels |
| `SOURCES.md` | 6 source URLs |

## Demo script (≤3 minutes)

1. **0:00** Open the live prototype (GitHub Pages link above). Step 1: 500 reviews, 21 Jul – 19 Sep, 51% rated 1–2★.
2. **0:20** Themes: five bars, top three by pain; the week of 24–30 Aug spikes to 50% reliability complaints.
3. **0:45** Fee table: "External charges & taxes" wins on confusion (16 of 24). Read one quote.
4. **1:05** Weekly pulse: show the checks (247/250 words, quotes verbatim, 3 actions). Mention that the n8n version adds a free-LLM polish with the same checks.
5. **1:35** Fee explainer: six bullets, two official links, Last checked. Change the calculator to 10 shares to show
   the DP charge shrinking as a share of the trade.
6. **2:00** Approval gate: open both previews and click **Approve and run**. Gmail opens a pre-filled draft; close it
   and show it in Gmail → Drafts (not sent).
7. **2:30** The Pulse log gains the entry; download it. Optionally show the n8n canvas paused at *Ask approver (wait)*.
