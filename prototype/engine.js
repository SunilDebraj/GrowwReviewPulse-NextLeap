/* Review-pulse engine — browser port of analyze.py + pipeline.py (same lexicon, same rules).
   Exposes window.PulseEngine in the browser and module.exports under Node (for the parity test). */
(function (root) {
  "use strict";

  const THEMES = {
    reliability: {
      label: "App reliability: update regressions, charts & order glitches", short: "App reliability",
      patterns: [/\bupdat(e|ed|es|ing)\b/, /\bbug/, /glitch/, /\blag/, /\bslow\b/, /\bhang/, /\bstuck\b/, /crash/,
        /\bfreez/, /not (opening|loading|working)/, /\bchart/, /\bcandle/, /scalp/, /back button/, /navigation/,
        /\brefresh/, /\bindicator/, /stop ?loss/, /\bsl\b/, /square ?off/, /(not|wasn't) executed/, /\bexecution\b/,
        /position/, /\bbuffering\b/, /not updat/],
    },
    support: {
      label: "Customer support hard to reach / issues unresolved", short: "Customer support",
      patterns: [/customer (care|support|service)/, /\bsupport\b/, /help ?line/, /\bon hold\b/, /\bhold for\b/,
        /\bticket/, /\bagents?\b/, /no (one )?(reply|response|respond)/, /not (responding|respond)/, /\bcall back\b/,
        /chat (support|option|service)/, /\bivr\b/, /\bmailed\b/, /waiting .*connect/, /\bai (bot|chatbot|help)\b/],
    },
    charges: {
      label: "Charges & deductions not understood (brokerage, 'external charges & taxes', DP)", short: "Charges & deductions",
      patterns: [/\bcharg(e|es|ed|ing)\b/, /brokerage/, /brokarage/, /brockerage/, /\bfees?\b/, /\bdp\b/, /\bdeduct/,
        /\btax(es)?\b/, /\bgst\b/, /\bstt\b/, /hidden/, /commission/, /haircut/, /\binterest\b/, /\bpenalty\b/],
    },
    account_money: {
      label: "Account, KYC & money movement (activation, withdrawals, payments)", short: "Account & money movement",
      patterns: [/\bkyc\b/, /account (opening|activation|reactivat|closure|is|blocked|details|creation)/,
        /(activate|reactivat|deactivat)/, /withdraw/, /\bredeem|redemption/, /\bpayment/, /\bupi\b/, /mandate/,
        /\brefund/, /\bpan\b/, /aadh?ar/, /e-?mail (id|address)/, /\bblocked\b/, /demat account/, /journey reset/,
        /allow permission/, /\blog ?in\b/],
    },
    ease_of_use: {
      label: "Praise: simple, beginner-friendly investing", short: "Ease of use (praise)",
      patterns: [/easy/, /simple/, /user[- ]?friendly/, /beginner/, /smooth/, /\bclean\b/, /intuitive/, /\bbest\b/,
        /\bgreat\b/, /excellent/, /\bnice\b/, /\bgood app\b/, /convenient/],
      minRating: 4,
    },
  };

  const FEE_TERMS = {
    external_charges: [/external charge/, /\btax(es)?\b/, /\bgst\b/, /\bstt\b/, /hidden charge/, /other charges/, /deduction/, /\bdeduct/],
    brokerage: [/brokerage/, /brokarage/, /brockerage/, /per order/],
    dp_charge: [/\bdp\b/, /selling stocks/, /sell order/, /delivery sell/],
    mtf_interest: [/\bmtf\b/, /haircut/],
    service_fees: [/\bddpi\b/, /change ur email/],
  };
  const FEE_LABELS = {
    external_charges: "\"External charges & taxes\" deducted on top of brokerage",
    brokerage: "Brokerage per executed order",
    dp_charge: "DP charge on delivery sells",
    mtf_interest: "MTF interest / haircut",
    service_fees: "Account-service fees (DDPI, email change)",
  };
  const CONFUSION_CUES = [/not (clear|easy to understand)/, /don'?t know/, /donot know/, /hidden/,
    /without (any|ur|your) (information|use|knowledge)/, /\bwhy\b/, /\?/, /more th[ae]n (they|you) mention/,
    /you mentioned/, /not (clearly )?(informed|disclosed)/, /bla bla/, /silently/, /unexpected/, /misleading/, /expected/];
  const REGRESSION = /scalp|navigation|back button/;

  const THEME_NOTES = {
    reliability: "Chart-screen regressions after updates, stale prices, stuck orders.",
    support: "Long IVR holds, AI-bot loops, tickets closed unresolved.",
    charges: "Deductions exceed the \"₹20 brokerage\" users expect.",
    account_money: "Activation/KYC delays, slow withdrawals, failed payments.",
    ease_of_use: "Simple, beginner-friendly investing.",
  };
  const ACTIONS = {
    reliability: ["Chart hotfix:", "move the Scalper toggle away from Back, keep the nav bar visible, add an opt-out."],
    support: ["Support SLA:", "show real queue times, offer callback, no ticket closure without a human reply."],
    charges: ["Charge clarity:", "itemized pre-trade charge preview; link the fee explainer from P&L."],
    account_money: ["Money movement:", "show withdrawal/activation status with an ETA and a single tracking ID."],
  };
  const QUOTE_SPECS = {
    reliability: [[/scalp/], /scalp/], support: [[/hold/], /hold/], charges: [[/deduct/, /not clear/], /not clear/],
    account_money: [[/withdraw/], /withdraw/], ease_of_use: [[/beginner/], /beginner/],
  };

  // Facts verified against official pages on 13 Oct 2026 (see sources).
  const FEE_KB = {
    external_charges: {
      title: "\"External charges & taxes\" on Groww stock trades",
      bullets: [
        ["Two kinds of deductions apply to every trade.", "Groww's own brokerage, and levies set by the government, exchanges, SEBI and the depository. Groww lists the second group on its pricing page as Regulatory & Statutory Charges; in the app they appear separately from brokerage."],
        ["Brokerage (stocks):", "₹20 or 0.1% of order value per executed order, whichever is lower; if that is under ₹5, the charge is the lower of ₹5 or 2.5% of trade value. F&O: ₹20 per executed order."],
        ["Statutory and exchange levies (equity):", "STT is 0.1% on buy and sell for delivery and 0.025% on sell for intraday; stamp duty is 0.015% (delivery) or 0.003% (intraday) on buy; NSE transaction charge 0.00297%; SEBI turnover fee 0.0001%; GST 18% on brokerage, DP, exchange, SEBI and IPFT charges."],
        ["DP charge on delivery sells:", "₹20 per sell transaction (₹3.50 depository + ₹16.50 Groww; depository part ₹3.25 for women), plus GST. Not charged on intraday. Groww's portion is ₹0 for debit values under ₹100."],
        ["Why small trades feel it most:", "the ₹5 minimum brokerage and ₹20 DP charge do not scale with trade size. Example: 1 share bought at ₹200 and sold at ₹220 (delivery, NSE) carries about ₹36 in total charges, more than the ₹20 price gain."],
        ["Where to see exact amounts:", "the app shows an estimate on the trading day; final, itemized charges are in the contract note emailed as a PDF (password: PAN in capitals), with DP charges in a separate statement in the same PDF."],
      ],
      sources: [["Groww — Pricing", "https://groww.in/pricing"],
        ["Groww Help — How much is the brokerage?", "https://groww.in/help/stocks/searchable/how-much-is-the-brokerage"]],
      lastChecked: "2026-10-13",
    },
  };

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function parseISO(s) { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); }
  function fmtDay(iso, year) { const d = parseISO(iso); return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + (year ? " " + d.getUTCFullYear() : ""); }
  function isoWeek(iso) {
    const d = parseISO(iso); const day = d.getUTCDay() || 7; d.setUTCDate(d.getUTCDate() + 4 - day);
    const y = d.getUTCFullYear(); const w = Math.ceil(((d - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
    return [y, w];
  }
  function weekBounds(y, w) {
    const jan4 = new Date(Date.UTC(y, 0, 4)); const day = jan4.getUTCDay() || 7;
    const mon = new Date(jan4); mon.setUTCDate(jan4.getUTCDate() - day + 1 + (w - 1) * 7);
    const sun = new Date(mon); sun.setUTCDate(mon.getUTCDate() + 6);
    const f = (x) => x.toISOString().slice(0, 10); return [f(mon), f(sun)];
  }
  const round1 = (x) => Math.round(x * 10) / 10;
  const pyRound = (x) => { const f = Math.floor(x); const r = x - f; return r > 0.5 || (r === 0.5 && f % 2 === 1) ? f + 1 : f; };
  const hits = (t, pats) => pats.reduce((n, p) => n + (p.test(t) ? 1 : 0), 0);

  function excerpt(text, anchor, maxWords) {
    maxWords = maxWords || 22;
    for (const s of text.split(/(?<=[.!?])\s+/)) {
      if (anchor.test(s.toLowerCase())) {
        const w = s.split(/\s+/).filter(Boolean);
        return w.length > maxWords ? w.slice(0, maxWords).join(" ") + " …" : s;
      }
    }
    return text.split(/\s+/).slice(0, maxWords).join(" ") + " …";
  }

  // --- CSV ------------------------------------------------------------------
  function parseCSV(src) {
    const rows = []; let row = [], f = "", q = false;
    for (let i = 0; i < src.length; i++) {
      const c = src[i];
      if (q) { if (c === '"') { if (src[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n" || c === "\r") { if (c === "\r" && src[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
      else f += c;
    }
    if (f.length || row.length) { row.push(f); rows.push(row); }
    const head = rows.shift().map((h) => h.trim().toLowerCase());
    const col = (names) => names.map((n) => head.indexOf(n)).find((i) => i >= 0);
    const ix = { id: col(["review_id", "reviewid", "id"]), date: col(["date", "at", "review_date"]),
      rating: col(["rating", "score", "stars"]), text: col(["text", "body", "content", "review"]),
      helpful: col(["helpful_count", "thumbsupcount", "helpful", "thumbsup"]) };
    if (ix.date === undefined || ix.rating === undefined || ix.text === undefined)
      throw new Error("The CSV needs date, rating and text columns (found: " + head.join(", ") + ").");
    return rows.filter((r) => r.length > 1 && (r[ix.text] || "").trim()).map((r, n) => ({
      review_id: ix.id !== undefined ? r[ix.id] : "row-" + (n + 1),
      date: (r[ix.date] || "").slice(0, 10), rating: parseInt(r[ix.rating], 10) || 0,
      helpful_count: ix.helpful !== undefined ? parseInt(r[ix.helpful], 10) || 0 : 0,
      text: r[ix.text].replace(/\s+/g, " ").trim(),
    }));
  }

  // --- Step 1: review intelligence -------------------------------------------
  function analyze(input) {
    const rows = input.map((r) => Object.assign({}, r, { _t: r.text.toLowerCase() }));
    for (const r of rows) {
      const scores = {};
      for (const [k, spec] of Object.entries(THEMES)) {
        if (r.rating < (spec.minRating || 0)) continue;
        const s = hits(r._t, spec.patterns); if (s) scores[k] = s;
      }
      r.themes = Object.keys(scores).sort((a, b) => scores[b] - scores[a]); // stable: ties keep THEMES order
      r.primary = r.themes[0] || "other";
    }
    const n = rows.length;
    const themes = [];
    for (const [k, spec] of Object.entries(THEMES)) {
      const m = rows.filter((r) => r.themes.includes(k)); if (!m.length) continue;
      const low = m.filter((r) => r.rating <= 2).length;
      themes.push({ key: k, label: spec.label, short: spec.short, reviews_mentioning: m.length,
        share_pct: round1(100 * m.length / n), primary_count: rows.filter((r) => r.primary === k).length,
        avg_rating: Math.round(100 * m.reduce((s, r) => s + r.rating, 0) / m.length) / 100,
        low_star_reviews: low, low_star_pct: round1(100 * low / m.length) });
    }
    themes.sort((a, b) => (b.low_star_reviews - a.low_star_reviews) || (b.reviews_mentioning - a.reviews_mentioning));
    const top3 = themes.slice(0, 3);

    const weekly = {};
    for (const r of rows) {
      const [y, w] = isoWeek(r.date); const tag = y + "-W" + String(w).padStart(2, "0");
      weekly[tag] = weekly[tag] || { _total: 0 }; weekly[tag]._total++;
      for (const t of r.themes) weekly[tag][t] = (weekly[tag][t] || 0) + 1;
    }
    const lead = top3[0].key;
    const eligible = Object.keys(weekly).filter((k) => weekly[k]._total >= 30);
    const pool = eligible.length ? eligible : Object.keys(weekly);
    const peak = pool.reduce((best, k) => (!best || (weekly[k][lead] || 0) / weekly[k]._total > (weekly[best][lead] || 0) / weekly[best]._total) ? k : best, null);
    const [py, pw] = [Number(peak.slice(0, 4)), Number(peak.slice(-2))];
    const [ps, pe] = weekBounds(py, pw);
    const peakInfo = { week: peak, start: ps, end: pe, share_pct: pyRound(100 * (weekly[peak][lead] || 0) / weekly[peak]._total) };

    const reg = rows.filter((r) => REGRESSION.test(r._t));
    const regression = { reviews: reg.length, low_star: reg.filter((r) => r.rating <= 2).length };

    const quotes = top3.map((t) => {
      const [must, anchor] = QUOTE_SPECS[t.key];
      let cand = rows.filter((r) => r.primary === t.key);
      const narrowed = cand.filter((r) => must.every((m) => m.test(r._t))); if (narrowed.length) cand = narrowed;
      const score = (r) => { const th = hits(r._t, THEMES[t.key].patterns);
        const tone = t.key !== "ease_of_use" ? 5 - r.rating : r.rating;
        return [th >= 2 ? 1 : 0, r.text.length >= 80 && r.text.length <= 420 ? 1 : 0, tone, r.helpful_count, th]; };
      const cmp = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0; };
      let best = cand[0], bs = score(best);
      for (const r of cand.slice(1)) { const s = score(r); if (cmp(s, bs) > 0) { best = r; bs = s; } }
      return { theme: t.short, review_id: best.review_id, date: best.date, rating: best.rating, excerpt: excerpt(best.text, anchor) };
    });

    const fee = detectFee(rows);
    const ratings = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }; rows.forEach((r) => { ratings[r.rating] = (ratings[r.rating] || 0) + 1; });
    const dates = rows.map((r) => r.date).sort();
    const praise = themes.find((t) => t.key === "ease_of_use") || { reviews_mentioning: 0, share_pct: 0, avg_rating: 0 };
    return {
      window: { from: dates[0], to: dates[dates.length - 1], reviews: n }, rating_mix: ratings,
      low_star_pct: pyRound(100 * (ratings[1] + ratings[2]) / n), themes, top_3_themes: top3.map((t) => t.label),
      praise: { reviews: praise.reviews_mentioning, share_pct: praise.share_pct, avg_rating: praise.avg_rating },
      quotes, lead_theme_peak: peakInfo, regression_signal: regression, fee_issue: fee, weekly_counts: weekly, rows,
    };
  }

  function detectFee(rows) {
    const charge = rows.filter((r) => r.themes.includes("charges"));
    const mentions = {}, confused = {}, evidence = {};
    for (const r of charge) {
      const isConf = hits(r._t, CONFUSION_CUES) > 0;
      for (const [fee, pats] of Object.entries(FEE_TERMS)) {
        if (hits(r._t, pats)) {
          mentions[fee] = (mentions[fee] || 0) + 1;
          if (isConf) { confused[fee] = (confused[fee] || 0) + 1; (evidence[fee] = evidence[fee] || []).push(r); }
        }
      }
    }
    const ranked = Object.keys(mentions).sort((a, b) => ((confused[b] || 0) - (confused[a] || 0)) || (mentions[b] - mentions[a]));
    if (!ranked.length) return null;
    const top = ranked[0];
    const ev = evidence[top] || [];
    const named = ev.filter((r) => /external charge/.test(r._t)); const pool = named.length ? named : ev;
    let ex = pool[0];
    for (const r of pool) if (excerpt(r.text, /external charge/).length < excerpt(ex.text, /external charge/).length) ex = r;
    return {
      fee_key: top, fee: FEE_LABELS[top], mentions: mentions[top], mentions_with_confusion_cue: confused[top] || 0,
      charges_theme_reviews: charge.length,
      all_fee_counts: ranked.map((f) => ({ key: f, label: FEE_LABELS[f], mentions: mentions[f], confused: confused[f] || 0 })),
      example_quote: ex ? { review_id: ex.review_id, date: ex.date, rating: ex.rating, excerpt: excerpt(ex.text, /external charge/) } : null,
      evidence_review_ids: ev.map((r) => r.review_id),
    };
  }

  // --- Step 2: weekly pulse (markdown, same template as pipeline.py) ---------
  function pulseMarkdown(ins, runDate) {
    const top = ins.themes.slice(0, 3);
    const L = ["# Groww Weekly Product Pulse — " + fmtDay(runDate, true), "",
      "**Input:** " + ins.window.reviews + " Play Store reviews (India, English), " + fmtDay(ins.window.from) + " – " +
      fmtDay(ins.window.to, true) + " · " + ins.low_star_pct + "% rated 1–2★", "", "## Top themes (ranked by 1–2★ volume)"];
    top.forEach((t, i) => L.push((i + 1) + ". **" + t.short + "** — " + t.reviews_mentioning + " reviews (" + pyRound(t.share_pct) +
      "%), avg " + t.avg_rating.toFixed(1) + "★. " + THEME_NOTES[t.key]));
    const p = ins.praise;
    L.push("", "Bright spot: " + p.reviews + " reviews (" + pyRound(p.share_pct) + "%, " + p.avg_rating.toFixed(1) + "★) praise its simplicity for beginners.", "", "## Voice of the user");
    ins.quotes.forEach((q) => L.push("- \"" + q.excerpt + "\" (" + q.rating + "★, " + fmtDay(q.date) + ")"));
    const pk = ins.lead_theme_peak, rg = ins.regression_signal, fee = ins.fee_issue;
    L.push("", "## Key observation", top[0].short + " complaints peaked " + parseISO(pk.start).getUTCDate() + "–" + fmtDay(pk.end) +
      " (" + pk.share_pct + "% of that week's reviews); " + rg.reviews + " reviews mention the Scalper button or hidden back-navigation (" +
      rg.low_star + " rated 1–2★). " + (fee ? "\"External charges & taxes\" is the most confused charge: " + fee.mentions_with_confusion_cue +
      " of " + fee.mentions + " mentions signal confusion, not price objection." : ""), "", "## Action ideas");
    top.forEach((t, i) => { const a = ACTIONS[t.key] || ["Follow-up:", "review this theme with the owning team."]; L.push((i + 1) + ". **" + a[0] + "** " + a[1]); });
    return L.join("\n") + "\n";
  }
  const wordCount = (md) => (md.match(/\S*[A-Za-z0-9]\S*/g) || []).length;
  function validatePulse(md, ins) {
    const checks = [{ ok: wordCount(md) <= 250, label: wordCount(md) + " / 250 words" }];
    const missing = ins.quotes.filter((q) => !md.includes(q.excerpt));
    checks.push({ ok: !missing.length, label: missing.length ? missing.length + " quote(s) altered" : "3 quotes verbatim from the CSV" });
    const acts = (md.split("## Action ideas")[1] || "").match(/^\d\. \*\*/gm) || [];
    checks.push({ ok: acts.length === 3, label: acts.length + " action ideas" });
    return checks;
  }

  // --- Step 3: fee explainer -------------------------------------------------
  function feeExplainer(ins) {
    const fee = ins.fee_issue; if (!fee) return null;
    const kb = FEE_KB[fee.fee_key]; if (!kb) return { missing: true, fee };
    const checks = [{ ok: kb.bullets.length <= 6, label: kb.bullets.length + " bullets (max 6)" },
      { ok: kb.sources.length >= 2, label: kb.sources.length + " official source links" },
      { ok: !kb.bullets.some((b) => /\b(we|you should|best|unfortunately|sorry)\b/i.test(b.join(" "))), label: "Neutral, facts-only wording" },
      { ok: !!kb.lastChecked, label: "Last checked: " + fmtDay(kb.lastChecked, true) }];
    return { kb, fee, checks };
  }

  // --- Step 4: payload + email ----------------------------------------------
  function payload(ins, pulseMd, runDate) {
    const ex = feeExplainer(ins);
    return { date: runDate, top_themes: ins.themes.slice(0, 3).map((t) => t.label), weekly_pulse: pulseMd,
      identified_fee_issue: ins.fee_issue ? ins.fee_issue.fee : null,
      explanation_bullets: ex && ex.kb ? ex.kb.bullets.map((b) => b.join(" ")) : [],
      source_links: ex && ex.kb ? ex.kb.sources.map((s) => s[1]) : [] };
  }
  function email(p) {
    const plain = p.weekly_pulse.replace(/\*\*(.+?)\*\*/g, "$1").replace(/^#+\s*/gm, "").trim();
    const kb = FEE_KB.external_charges;
    const body = ["Team,", "", "Below is this week's product pulse from Play Store reviews, followed by a reusable support snippet for the most-confused charge.", "",
      "=== WEEKLY PRODUCT PULSE ===", "", plain, "", "=== SUPPORT SNIPPET: \"External charges & taxes\" (copy-paste ready) ===", "",
      "Hi, thanks for flagging this. Here is how charges on stock trades work on Groww:", "",
      ...p.explanation_bullets.map((b) => "• " + b), "", "Sources: " + p.source_links.join(" | "), "Last checked: " + fmtDay(kb.lastChecked, true), "",
      "— Generated by the review-pulse workflow; approved before drafting. Not sent automatically."].join("\n");
    return { subject: "Weekly Product Pulse + Customer Clarification — " + fmtDay(p.date, true), to: [], body };
  }

  const api = { THEMES, FEE_KB, parseCSV, analyze, pulseMarkdown, validatePulse, wordCount, feeExplainer, payload, email, fmtDay, excerpt };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PulseEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
