"""Build the importable n8n workflow from the shared engine (prototype/engine.js).

    python n8n/build_workflow.py                       # writes n8n/groww_review_pulse.n8n.json
    python n8n/build_workflow.py --test DIR \
        --mock-llm http://127.0.0.1:8766/v1 --mock-play http://127.0.0.1:8765   # + test variants

Free by design: self-hosted n8n (Community Edition), reviews fetched straight from Google Play
(no Apify), any OpenAI-compatible LLM (Gemini free tier by default, or Ollama on your own
computer), and a personal Google account for Gmail + Google Docs.

The Code nodes embed the same engine the Python pipeline and the prototype use, so all three
produce identical themes, quotes, fee issue, pulse and email for the same CSV.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def nid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "groww-review-pulse/" + name))


def engine_src() -> str:
    """engine.js as a plain block that defines `const E = {...}` (no module/window wrapper)."""
    src = (ROOT / "prototype" / "engine.js").read_text(encoding="utf-8")
    head = "(function (root) {"
    tail = ('if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PulseEngine = api;\n'
            '})(typeof window !== "undefined" ? window : globalThis);')
    assert head in src and tail in src, "engine.js wrapper changed; update build_workflow.py"
    body = src[src.index(head):].replace(head, "const E = (function () {", 1).replace(tail, "return api;\n})();", 1)
    return "// ---- shared review-pulse engine (same as prototype/engine.js) ----\n" + body


ENGINE = engine_src()

# ---------------------------------------------------------------------------
# Code node bodies
# ---------------------------------------------------------------------------
FETCH_PLAY = r"""// ---- Fetch reviews from Google Play (free, no account) -----------------------
// Uses the public endpoint the Play Store web page itself calls, the same request as the
// open-source google-play-scraper (v10.1.4). Pages through "most relevant" (or newest)
// reviews, keeps those from the last `recentDays`, stops at `maxReviews` or `maxPages`.
const cfg = $("Config").first().json;
const BASE = String(cfg.playBaseUrl || "https://play.google.com").replace(/\/$/, "");
const RPC = "oCPfdb";
const SORT = { most_relevant: 1, newest: 2, rating: 3 }[cfg.playSort] || 1;
const cutoff = new Date(cfg.runDate + "T00:00:00Z").getTime() - cfg.recentDays * 864e5;
const url = `${BASE}/_/PlayStoreUi/data/batchexecute?rpcids=${RPC}&hl=${encodeURIComponent(cfg.lang)}&gl=${encodeURIComponent(cfg.country)}`;

const out = [];
let token = null, pages = 0, scanned = 0;
while (out.length < cfg.maxReviews && pages < cfg.maxPages) {
  const paging = token ? [150, null, token] : [150];
  const request = [null, [2, SORT, paging, null, [null, null, null, null, null, null, null, null, null]], [cfg.appId, 7]];
  const body = "f.req=" + encodeURIComponent(JSON.stringify([[[RPC, JSON.stringify(request), null, "generic"]]]));
  let raw;
  try {
    raw = await this.helpers.httpRequest({
      method: "POST", url, body, json: false, encoding: "text", timeout: 30000,
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
    });
  } catch (e) {
    if (pages === 0) throw new Error("Google Play did not answer (" + (e.message || e) + "). Upload a CSV through the form instead.");
    break;                                        // keep what we already have
  }
  const text = typeof raw === "string" ? raw : Buffer.isBuffer(raw) ? raw.toString("utf8") : JSON.stringify(raw);
  let data = null;
  try { const outer = JSON.parse(text.substring(text.indexOf("["))); data = outer[0] && outer[0][2] ? JSON.parse(outer[0][2]) : null; }
  catch (e) { throw new Error("Google Play changed its response format, so reviews could not be read. Upload a CSV through the form instead."); }
  pages++;
  if (!data || !Array.isArray(data[0])) break;
  for (const r of data[0]) {
    scanned++;
    const when = r[5] ? Number(r[5][0]) * 1000 : NaN;
    if (!r[4] || !(when >= cutoff)) continue;
    out.push({ review_id: String(r[0]), date: new Date(when).toISOString().slice(0, 10), rating: Number(r[2]) || 0,
               helpful_count: Number(r[6]) || 0, app_version: r[10] || "", text: String(r[4]) });
    if (out.length >= cfg.maxReviews) break;
  }
  token = data[1] && data[1][1];
  if (!token) break;
  if (SORT === 2 && out.length && data[0].length && Number((data[0][data[0].length - 1][5] || [0])[0]) * 1000 < cutoff) break;
  await new Promise((r) => setTimeout(r, 400));   // be polite: one request at a time
}
const source = `Google Play (${cfg.appId}, ${cfg.country}/${cfg.lang}, ${cfg.playSort}): ${out.length} of ${scanned} reviews scanned in ${pages} page(s)`;
return out.map((r) => ({ json: { ...r, source } }));
"""

NORMALIZE = ENGINE + r"""
// ---- Normalize reviews --------------------------------------------------
// Accepts an uploaded CSV (form) or review items from the Google Play fetch and returns
// ONE item holding a clean list: {review_id, date, rating, helpful_count, text}.
const items = $input.all();
const reviews = [];
let source = "";
for (let i = 0; i < items.length; i++) {
  const it = items[i];
  const files = Object.keys(it.binary || {});
  if (files.length) {
    for (const key of files) {
      const buf = await this.helpers.getBinaryDataBuffer(i, key);
      reviews.push(...E.parseCSV(buf.toString("utf8").replace(/^﻿/, "")));
      source = "CSV upload: " + (it.binary[key].fileName || key);
    }
    continue;
  }
  const j = it.json || {};
  const text = j.body || j.text || j.content || j.review;
  if (!text) continue;
  reviews.push({
    review_id: String(j.reviewId || j.review_id || j.id || "item-" + (i + 1)),
    date: String(j.date || j.at || j.timestamp || "").slice(0, 10),
    rating: Number(j.rating ?? j.score ?? j.stars) || 0,
    helpful_count: Number(j.helpfulCounts ?? j.helpful_count ?? j.thumbsUpCount ?? j.thumbsUp ?? 0) || 0,
    text: String(text).replace(/\s+/g, " ").trim(),
  });
  source = j.source || "Google Play reviews";
}
const seen = new Set();
const clean = reviews.filter((r) => {
  if (!r.text || !/^\d{4}-\d{2}-\d{2}$/.test(r.date) || r.rating < 1 || r.rating > 5 || seen.has(r.review_id)) return false;
  seen.add(r.review_id);
  return true;
});
if (clean.length < 20) {
  throw new Error(`Only ${clean.length} usable reviews found. Upload a CSV with date, rating and text columns through the form.`);
}
return [{ json: { source, reviews: clean } }];
"""

INTELLIGENCE = ENGINE + r"""
// ---- Step 1: review intelligence ------------------------------------------
// Max 5 themes, top 3 by 1–2★ volume, 3 verbatim quotes, the most-confused fee.
const cfg = $("Config").first().json;
const { source, reviews } = $input.first().json;
const full = E.analyze(reviews);
const { rows, ...insights } = full;            // drop per-review rows from the item
const templatePulse = E.pulseMarkdown(full, cfg.runDate);

const llmPrompt =
  "Rewrite the DRAFT below for clarity. Hard rules: output Markdown only, nothing before or after it; keep the exact section headings " +
  "(# title, ## Top themes (ranked by 1–2★ volume), ## Voice of the user, ## Key observation, ## Action ideas); keep every number unchanged; " +
  "keep each quoted user sentence exactly as written inside double quotes; exactly 3 numbered action ideas, each starting with a **bold label:**; " +
  "at most 230 words; neutral tone; add no new facts.\n\n" +
  "DATA (JSON): " + JSON.stringify({ themes: insights.themes, quotes: insights.quotes, fee_issue: insights.fee_issue && {
    fee: insights.fee_issue.fee, mentions: insights.fee_issue.mentions, confused: insights.fee_issue.mentions_with_confusion_cue },
    peak: insights.lead_theme_peak, regression: insights.regression_signal }) +
  "\n\nDRAFT:\n" + templatePulse;

return [{ json: { runDate: cfg.runDate, source, insights, templatePulse, llmPrompt } }];
"""

VALIDATE = r"""// ---- Step 2 guardrail: keep the LLM's draft only if it passes every check ----
// Same rules as pipeline.py: ≤250 words, the 3 quotes verbatim, exactly 3 action
// ideas, and every number from the data-driven template still present.
const base = $("Review intelligence").first().json;
const out = $input.first().json;

let draft = "";
if (Array.isArray(out.choices) && out.choices[0]) {                    // OpenAI-compatible (Gemini, Ollama, Groq, OpenRouter…)
  const c = out.choices[0].message && out.choices[0].message.content;
  draft = Array.isArray(c) ? c.map((p) => p.text || "").join("") : String(c || "");
} else if (Array.isArray(out.content)) {                               // Anthropic shape
  draft = out.content.filter((b) => b.type === "text").map((b) => b.text).join("\n");
}
draft = draft.replace(/<think>[\s\S]*?<\/think>/gi, "")                 // local reasoning models
  .replace(/^\s*```(?:markdown|md)?\s*/i, "").replace(/```\s*$/, "").trim();
if (draft) draft += "\n";

const words = (md) => (md.match(/\S*[A-Za-z0-9]\S*/g) || []).length;
const numbers = (md) => new Set(md.match(/\d+(?:\.\d+)?%?/g) || []);
function checks(md) {
  const list = [{ ok: words(md) <= 250, label: words(md) + " / 250 words" }];
  const missingQuotes = base.insights.quotes.filter((q) => !md.includes(q.excerpt));
  list.push({ ok: !missingQuotes.length, label: missingQuotes.length ? missingQuotes.length + " quote(s) altered" : "3 quotes verbatim from the CSV" });
  const acts = (md.split("## Action ideas")[1] || "").match(/^\d\. \*\*/gm) || [];
  list.push({ ok: acts.length === 3, label: acts.length + " action ideas" });
  const have = numbers(md);
  const lost = [...numbers(base.templatePulse)].filter((n) => !have.has(n));
  list.push({ ok: !lost.length, label: lost.length ? "numbers changed: " + lost.slice(0, 5).join(", ") : "all numbers kept" });
  return list;
}

const model = $("Config").first().json.llmModel;
let pulse = base.templatePulse, pulseSource = "template", note = "";
if (draft) {
  const c = checks(draft);
  if (c.every((x) => x.ok)) { pulse = draft; pulseSource = "LLM (" + model + ")"; }
  else note = "LLM draft rejected (" + c.filter((x) => !x.ok).map((x) => x.label).join("; ") + "); template used.";
} else if (out.error) {
  const e = out.error, status = typeof e === "object" ? String(e.status || e.httpCode || "") : "";
  const why = { "429": "free-tier rate limit reached", "401": "API key missing or wrong", "403": "API key not allowed for this model",
                "404": "model name or base URL not found" }[status];
  const msg = why || (typeof e === "string" ? e : e.message || JSON.stringify(e));
  note = "LLM step failed (" + (status ? "HTTP " + status + ": " : "") + msg.slice(0, 160) + "); template used.";
} else {
  note = "LLM step skipped; template used.";
}
const pulseChecks = checks(pulse);
if (!pulseChecks.every((x) => x.ok)) throw new Error("Pulse failed validation: " + JSON.stringify(pulseChecks));
return [{ json: { pulse, pulseSource, pulseChecks, note } }];
"""

BUILD = ENGINE + r"""
// ---- Step 3 + 4: fee explainer, MCP payload, email draft, approval message ----
const cfg = $("Config").first().json;
const base = $("Review intelligence").first().json;
const v = $input.first().json;
const ins = base.insights;

const ex = E.feeExplainer(ins);
if (!ex) throw new Error("No fee or charge confusion found in these reviews, so there is no explainer to send.");
if (ex.missing) throw new Error(`Detected fee issue "${ex.fee.fee}" has no verified explainer yet. Add it to FEE_KB (with 2 official sources) before support uses it.`);
if (!ex.checks.every((c) => c.ok)) throw new Error("Explainer failed validation: " + JSON.stringify(ex.checks));

const payload = E.payload(ins, v.pulse, base.runDate);   // {date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links}
const email = E.email(payload);                          // {subject, to: [], body}
const plainPulse = v.pulse.replace(/\*\*(.+?)\*\*/g, "$1").replace(/^#+\s*/gm, "").trim();
const lastChecked = E.fmtDay(ex.kb.lastChecked, true);

const docText = [
  "",
  "────────────────────────────────────────",
  "Entry — " + E.fmtDay(payload.date, true),
  "────────────────────────────────────────",
  "date: " + payload.date,
  "top_themes:",
  ...payload.top_themes.map((t, i) => "  " + (i + 1) + ". " + t),
  "identified_fee_issue: " + payload.identified_fee_issue,
  "",
  "weekly_pulse:",
  plainPulse,
  "",
  "explanation_bullets:",
  ...payload.explanation_bullets.map((b) => "  • " + b),
  "Last checked: " + lastChecked,
  "",
  "source_links:",
  ...payload.source_links.map((u) => "  • " + u),
  "",
  `Input: ${ins.window.reviews} reviews, ${E.fmtDay(ins.window.from)} – ${E.fmtDay(ins.window.to, true)} (${base.source}). Pulse text: ${v.pulseSource}. Approved in n8n by ${cfg.approverEmail}.`,
  "",
].join("\n");

const approvalSubject = "Approve: " + email.subject;
const approvalMessage = [
  "Two actions are queued and nothing has been written yet:",
  "1. Append this week's entry to the Google Doc " + (cfg.googleDocId.startsWith("http") ? cfg.googleDocId : "https://docs.google.com/document/d/" + cfg.googleDocId),
  "2. Create a Gmail draft (no recipients, never sent): \"" + email.subject + "\"",
  "",
  `Input: ${ins.window.reviews} reviews, ${E.fmtDay(ins.window.from)} – ${E.fmtDay(ins.window.to, true)} · ${base.source}`,
  "Pulse text: " + v.pulseSource,
  "Checks: " + [...v.pulseChecks, ...ex.checks].map((c) => (c.ok ? "✓ " : "✕ ") + c.label).join(" · "),
  v.note ? "Note: " + v.note : "",
  "",
  "━━ WEEKLY PRODUCT PULSE ━━",
  plainPulse,
  "",
  "━━ FEE EXPLAINER: " + ex.kb.title + " ━━",
  ...payload.explanation_bullets.map((b) => "• " + b),
  "Sources: " + payload.source_links.join(" | "),
  "Last checked: " + lastChecked,
].filter((l, i, a) => l !== "" || a[i - 1] !== "").join("\n");

return [{ json: {
  payload, email, docText, approvalSubject, approvalMessage,
  pulseSource: v.pulseSource, checks: [...v.pulseChecks, ...ex.checks],
} }];
"""

SUMMARY = r"""// ---- Run summary (what the approved actions did) ----
const b = $("Build outputs").first().json;
const draft = $input.first().json;
const docId = $("Config").first().json.googleDocId;
return [{ json: {
  status: "approved and completed",
  date: b.payload.date,
  identified_fee_issue: b.payload.identified_fee_issue,
  doc: docId.startsWith("http") ? docId : "https://docs.google.com/document/d/" + docId,
  gmail_draft_id: draft.id || null,
  gmail_draft_sent: false,
  pulse_source: b.pulseSource,
} }];
"""

LOAD_SAMPLE_TEMPLATE = r"""// TEST ONLY: turn the bundled CSV into a file item, as the upload form would.
const csv = __CSV__;
const bin = await this.helpers.prepareBinaryData(Buffer.from(csv, "utf8"), "groww_playstore_reviews.csv", "text/csv");
return [{ json: {}, binary: { Reviews_CSV: bin } }];
"""

SYSTEM_PROMPT = ("You edit internal product updates for Groww's product team. Follow the user's hard rules exactly; "
                 "never invent numbers or quotes; reply with the Markdown pulse only.")

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def code(name, js, pos, **extra):
    n = {"parameters": {"jsCode": js}, "id": nid(name), "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": pos}
    n.update(extra)
    return n


def sticky(name, content, pos, w, h, color):
    return {"parameters": {"content": content, "height": h, "width": w, "color": color}, "id": nid(name), "name": name,
            "type": "n8n-nodes-base.stickyNote", "typeVersion": 1, "position": pos}


def assign(name, value, typ="string"):
    return {"id": nid("cfg-" + name), "name": name, "value": value, "type": typ}


CFG = "$('Config').first().json"
BUILT = "$('Build outputs').first().json"
LLM_NODE = "Free LLM: polish pulse"
FETCH_NODE = "Fetch reviews (Google Play, free)"

nodes = [
    sticky("Note: overview",
           "## Groww Review Pulse (free stack)\nPlay Store reviews → themes → weekly pulse + fee explainer → **human approval** → Google Doc entry + Gmail draft.\n\n"
           "Runs on **self-hosted n8n (free)**. No Apify, no paid LLM.\n**Setup:** fill in **Config**; add credentials on *Free LLM* "
           "(Gemini free key, or any text for Ollama), both Gmail nodes and Google Docs.",
           [-260, -400], 520, 240, 7),
    sticky("Note: step 1", "### Step 1 · Review intelligence\nUpload a CSV (form), or every Monday fetch the last 12 weeks straight from Google Play (free). "
           "Max 5 themes, top 3 by 1–2★ volume, 3 real quotes, the most-confused fee.", [300, -400], 780, 160, 5),
    sticky("Note: step 2-3", "### Step 2–3 · Pulse + fee explainer\nA free LLM (Gemini free tier, or Ollama on your computer) may tighten the pulse. "
           "A validator keeps its draft only if it is ≤250 words, keeps the 3 quotes verbatim, keeps every number and has 3 actions; "
           "otherwise the data-driven template is used. Fee facts come only from the verified knowledge base.",
           [1120, -400], 700, 180, 4),
    sticky("Note: approval", "### Step 4 · APPROVAL GATE\nThe workflow **pauses** here and emails the approver the full pulse and explainer with **Approve / Reject** buttons. "
           "Nothing is written to the doc or Gmail until someone clicks Approve. Times out after 3 days → nothing written.",
           [1860, -400], 560, 180, 3),
    sticky("Note: actions", "### Step 5 · Actions after approval\n1. Append {date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links} to the Google Doc.\n"
           "2. Create a Gmail **draft** (no recipients; never sent).", [2460, -400], 640, 160, 6),

    {"parameters": {"rule": {"interval": [{"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}]}},
     "id": nid("Every Monday 09:00 IST"), "name": "Every Monday 09:00 IST", "type": "n8n-nodes-base.scheduleTrigger",
     "typeVersion": 1.2, "position": [0, 0]},
    {"parameters": {
        "formTitle": "Groww Review Pulse",
        "formDescription": "Upload a Play Store reviews CSV (columns: date, rating, text; review_id and helpful_count optional). "
                           "The pulse and fee explainer are emailed to the approver before anything is logged or drafted.",
        "formFields": {"values": [{"fieldLabel": "Reviews CSV", "fieldName": "Reviews_CSV", "fieldType": "file", "multipleFiles": False,
                                   "acceptFileTypes": ".csv", "requiredField": True}]},
        "responseMode": "onReceived",
        "options": {"respondWithOptions": {"values": {"respondWith": "text",
                    "formSubmittedText": "Got it. The pulse is being generated; the approver will get an email to approve or reject."}}}},
     "id": nid("Upload reviews CSV"), "name": "Upload reviews CSV", "type": "n8n-nodes-base.formTrigger", "typeVersion": 2.6,
     "position": [0, 220], "webhookId": nid("form-webhook")},

    {"parameters": {"assignments": {"assignments": [
        assign("approverEmail", "you@example.com"),
        assign("googleDocId", "PASTE_GOOGLE_DOC_ID_OR_URL"),
        assign("llmBaseUrl", "https://generativelanguage.googleapis.com/v1beta/openai"),
        assign("llmModel", "gemini-3.8-flash"),
        assign("appId", "com.nextbillion.groww"),
        assign("country", "in"),
        assign("lang", "en"),
        assign("playSort", "most_relevant"),
        assign("recentDays", 84, "number"),
        assign("maxReviews", 500, "number"),
        assign("maxPages", 30, "number"),
        assign("playBaseUrl", "https://play.google.com"),
        assign("runDate", "={{ $now.setZone('Asia/Kolkata').toISODate() }}")]},
        "includeOtherFields": True, "include": "all", "options": {"stripBinary": False}},
     "id": nid("Config"), "name": "Config", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [240, 100]},

    {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{"id": nid("if-csv"), "leftValue": "={{ Object.keys($binary || {}).length > 0 }}", "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"},
        "looseTypeValidation": True, "options": {}},
     "id": nid("CSV uploaded?"), "name": "CSV uploaded?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [460, 100]},

    code(FETCH_NODE, FETCH_PLAY, [680, 220], alwaysOutputData=True),
    code("Normalize reviews", NORMALIZE, [900, 100]),
    code("Review intelligence", INTELLIGENCE, [1120, 100]),

    {"parameters": {"method": "POST",
        "url": "={{ " + CFG + ".llmBaseUrl.replace(/\\/$/, '') }}/chat/completions",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ model: " + CFG + ".llmModel, temperature: 0.2, max_tokens: 4096, stream: false, "
                    "messages: [{ role: 'system', content: " + json.dumps(SYSTEM_PROMPT) + " }, "
                    "{ role: 'user', content: $json.llmPrompt }] }) }}",
        "options": {"timeout": 180000}},
     "id": nid(LLM_NODE), "name": LLM_NODE, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
     "position": [1340, 100], "onError": "continueRegularOutput",
     "credentials": {"httpHeaderAuth": {"id": "", "name": "Free LLM key (Authorization: Bearer …)"}}},

    code("Validate pulse", VALIDATE, [1560, 100]),
    code("Build outputs", BUILD, [1780, 100]),

    {"parameters": {"operation": "sendAndWait",
        "sendTo": "={{ " + CFG + ".approverEmail }}",
        "subject": "={{ $json.approvalSubject }}",
        "message": "={{ $json.approvalMessage }}",
        "responseType": "approval",
        "approvalOptions": {"values": {"approvalType": "double", "approveLabel": "Approve: log + create draft", "disapproveLabel": "Reject"}},
        "options": {"limitWaitTime": {"values": {"limitType": "afterTimeInterval", "resumeAmount": 3, "resumeUnit": "days"}},
                    "appendAttribution": False}},
     "id": nid("Ask approver (wait)"), "name": "Ask approver (wait)", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1,
     "position": [2000, 100], "webhookId": nid("approval-webhook"), "credentials": {"gmailOAuth2": {"id": "", "name": "Gmail account"}}},

    {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
        "conditions": [{"id": nid("if-approved"), "leftValue": "={{ $json.data?.approved === true }}", "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"},
        "options": {}},
     "id": nid("Approved?"), "name": "Approved?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [2220, 100]},

    {"parameters": {"operation": "update", "documentURL": "={{ " + CFG + ".googleDocId }}",
        "actionsUi": {"actionFields": [{"object": "text", "action": "insert", "locationChoice": "endOfSegmentLocation",
                                        "text": "={{ " + BUILT + ".docText }}"}]}},
     "id": nid("Append entry to Google Doc"), "name": "Append entry to Google Doc", "type": "n8n-nodes-base.googleDocs", "typeVersion": 2,
     "position": [2480, 0], "credentials": {"googleDocsOAuth2Api": {"id": "", "name": "Google Docs account"}}},

    {"parameters": {"resource": "draft", "operation": "create",
        "subject": "={{ " + BUILT + ".email.subject }}", "emailType": "text",
        "message": "={{ " + BUILT + ".email.body }}", "options": {}},
     "id": nid("Create Gmail draft"), "name": "Create Gmail draft", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1,
     "position": [2700, 0], "credentials": {"gmailOAuth2": {"id": "", "name": "Gmail account"}}},

    code("Run summary", SUMMARY, [2920, 0]),
    {"parameters": {}, "id": nid("Rejected: nothing written"), "name": "Rejected: nothing written", "type": "n8n-nodes-base.noOp",
     "typeVersion": 1, "position": [2480, 220]},
]

connections = {
    "Every Monday 09:00 IST": {"main": [[{"node": "Config", "type": "main", "index": 0}]]},
    "Upload reviews CSV": {"main": [[{"node": "Config", "type": "main", "index": 0}]]},
    "Config": {"main": [[{"node": "CSV uploaded?", "type": "main", "index": 0}]]},
    "CSV uploaded?": {"main": [[{"node": "Normalize reviews", "type": "main", "index": 0}],
                               [{"node": FETCH_NODE, "type": "main", "index": 0}]]},
    FETCH_NODE: {"main": [[{"node": "Normalize reviews", "type": "main", "index": 0}]]},
    "Normalize reviews": {"main": [[{"node": "Review intelligence", "type": "main", "index": 0}]]},
    "Review intelligence": {"main": [[{"node": LLM_NODE, "type": "main", "index": 0}]]},
    LLM_NODE: {"main": [[{"node": "Validate pulse", "type": "main", "index": 0}]]},
    "Validate pulse": {"main": [[{"node": "Build outputs", "type": "main", "index": 0}]]},
    "Build outputs": {"main": [[{"node": "Ask approver (wait)", "type": "main", "index": 0}]]},
    "Ask approver (wait)": {"main": [[{"node": "Approved?", "type": "main", "index": 0}]]},
    "Approved?": {"main": [[{"node": "Append entry to Google Doc", "type": "main", "index": 0}],
                           [{"node": "Rejected: nothing written", "type": "main", "index": 0}]]},
    "Append entry to Google Doc": {"main": [[{"node": "Create Gmail draft", "type": "main", "index": 0}]]},
    "Create Gmail draft": {"main": [[{"node": "Run summary", "type": "main", "index": 0}]]},
}

workflow = {
    "name": "Groww Review Pulse (free)",
    "nodes": nodes,
    "connections": connections,
    "active": False,
    "settings": {"executionOrder": "v1", "timezone": "Asia/Kolkata", "saveManualExecutions": True},
    "pinData": {},
    "tags": [],
}


def strip_empty_credentials(wf):
    """Credentials are left as named placeholders; n8n asks you to pick/create them on first open."""
    for n in wf["nodes"]:
        for c in (n.get("credentials") or {}).values():
            c.pop("id", None)
    return wf


def test_variants(wf, mock_llm, mock_play):
    """Credential-free copies for local testing against mock servers. Each stops after 'Build outputs'
    (or after 'Approved?' with a simulated approval), so no Google account is needed."""
    csv_text = (ROOT / "data" / "groww_playstore_reviews.csv").read_text(encoding="utf-8")
    keep = {"Config", "CSV uploaded?", FETCH_NODE, "Normalize reviews", "Review intelligence", LLM_NODE,
            "Validate pulse", "Build outputs", "Approved?", "Rejected: nothing written"}

    def make(tag, *, upload, llm_url, approved):
        t = json.loads(json.dumps(wf))
        t["nodes"] = [n for n in t["nodes"] if n["name"] in keep]
        for n in t["nodes"]:
            if n["name"] == "Config":
                for a in n["parameters"]["assignments"]["assignments"]:
                    a["value"] = {"runDate": "2026-10-13", "approverEmail": "approver@example.com", "googleDocId": "TEST_DOC_ID",
                                  "llmBaseUrl": llm_url, "llmModel": "mock-model", "playBaseUrl": mock_play}.get(a["name"], a["value"])
            if n["name"] == LLM_NODE:                        # mock server needs no key
                n["parameters"]["authentication"] = "none"
                n["parameters"].pop("genericAuthType", None)
                n.pop("credentials", None)
        t["nodes"] += [
            {"parameters": {}, "id": nid("test-manual"), "name": "Test run", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [-200, 100]},
            code("Fake approval", "return [{json:{data:{approved:%s}}}];" % ("true" if approved else "false"), [2000, 100]),
            {"parameters": {}, "id": nid("test-would"), "name": "Would append + draft", "type": "n8n-nodes-base.noOp", "typeVersion": 1, "position": [2480, 0]},
        ]
        c = {k: v for k, v in t["connections"].items() if k in keep and k not in ("Build outputs", "Approved?")}
        if upload:
            t["nodes"].append(code("Load sample CSV", LOAD_SAMPLE_TEMPLATE.replace("__CSV__", json.dumps(csv_text)), [0, 100]))
            c["Test run"] = {"main": [[{"node": "Load sample CSV", "type": "main", "index": 0}]]}
            c["Load sample CSV"] = {"main": [[{"node": "Config", "type": "main", "index": 0}]]}
        else:
            c["Test run"] = {"main": [[{"node": "Config", "type": "main", "index": 0}]]}
        c["Build outputs"] = {"main": [[{"node": "Fake approval", "type": "main", "index": 0}]]}
        c["Fake approval"] = {"main": [[{"node": "Approved?", "type": "main", "index": 0}]]}
        c["Approved?"] = {"main": [[{"node": "Would append + draft", "type": "main", "index": 0}],
                                   [{"node": "Rejected: nothing written", "type": "main", "index": 0}]]}
        t["connections"] = c
        t["name"] = f"Groww Review Pulse test {tag}"
        t["id"] = f"GrowwFreeTest{tag}"
        return t

    return [
        make("U1", upload=True, llm_url=mock_llm + "/good", approved=True),       # CSV + valid LLM draft + approve
        make("U2", upload=True, llm_url=mock_llm + "/numbers", approved=True),    # LLM changes a number → template
        make("U3", upload=True, llm_url=mock_llm + "/ratelimit", approved=False), # LLM 429 → template; reject
        make("P1", upload=False, llm_url=mock_llm + "/good", approved=True),      # Google Play fetch path
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="directory for the test variants")
    ap.add_argument("--mock-llm", default="http://127.0.0.1:8766/v1")
    ap.add_argument("--mock-play", default="http://127.0.0.1:8765")
    args = ap.parse_args()
    out = HERE / "groww_review_pulse.n8n.json"
    out.write_text(json.dumps(strip_empty_credentials(json.loads(json.dumps(workflow))), indent=2, ensure_ascii=False), encoding="utf-8")
    print(out, f"{out.stat().st_size / 1024:.0f} KB", len(workflow["nodes"]), "nodes")
    if args.test:
        for t in test_variants(workflow, args.mock_llm, args.mock_play):
            p = Path(args.test) / f"{t['id']}.json"
            p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            print(p)


if __name__ == "__main__":
    main()
