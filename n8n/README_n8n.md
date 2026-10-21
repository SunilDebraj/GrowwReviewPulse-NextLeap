# Groww Review Pulse on n8n: free version

`groww_review_pulse.n8n.json` runs the whole workflow with **no subscriptions**: reviews → themes → weekly pulse
\+ fee explainer → human approval → Google Doc entry + Gmail draft. It uses the same engine as the Python pipeline
and the prototype, so the same CSV gives the same themes, quotes, fee issue, pulse and email.

## What costs money, and what replaces it

| Piece | Paid option | Free option used here |
|---|---|---|
| n8n | n8n Cloud has no free plan, only a trial (Starter from €20/month) | **Self-hosted n8n** on your own computer (Docker or npm) |
| Review data | Apify (free credits; this scraper caps free users at 500 reviews total) | **Direct Google Play fetch** (no account), or **CSV upload** |
| LLM | Claude / OpenAI API | **Gemini API free tier** (default, no card), or **Ollama** on your computer (no account, offline) |
| Doc + email | n/a | Your personal **Gmail + Google Docs**, through a free Google Cloud OAuth client |

The LLM step is optional. The pulse is generated from the data first; the LLM only tightens the wording. Its draft is
kept only if it is ≤250 words, keeps the 3 quotes verbatim, keeps every number and has 3 actions. If the LLM is
missing, rate-limited or wrong, the data-driven pulse is used.

## The flow

```
Every Monday 09:00 IST ─┐                       ┌─(no file)─ Fetch reviews (Google Play, free) ─┐
                        ├─ Config ─ CSV uploaded? ┤                                               ├─ Normalize reviews
Upload reviews CSV ─────┘                       └─(file)────────────────────────────────────────┘
                                                                                                     │
Review intelligence → Free LLM: polish pulse → Validate pulse → Build outputs → Ask approver (wait) → Approved?
                                                                                                    ├─ yes → Append entry to Google Doc → Create Gmail draft → Run summary
                                                                                                    └─ no  → Rejected: nothing written
```

## Set it up (about 20 minutes, all free)

### 1. Run n8n on your computer

**Docker** (Docker Desktop is free for personal use):

```bash
docker volume create n8n_data
docker run -it --rm --name n8n -p 5678:5678 \
  -e GENERIC_TIMEZONE="Asia/Kolkata" -e TZ="Asia/Kolkata" \
  --add-host=host.docker.internal:host-gateway \
  -v n8n_data:/home/node/.n8n n8nio/n8n
```

**Or npm** (needs Node.js 24 or newer): `npx n8n`

Open http://localhost:5678 and create the local owner account. Then *Workflows → Import from File* →
`groww_review_pulse.n8n.json`.

### 2. Connect Gmail and Google Docs (free Google Cloud OAuth client)

Self-hosted n8n needs your own OAuth client. It's free, and no billing account is needed.

1. Go to https://console.cloud.google.com, create a project, and enable the **Gmail API** and the **Google Docs API**.
2. On the **OAuth consent screen**, choose *External*, keep it in *Testing*, and add your Gmail address as a test user.
3. Under **Credentials → Create credentials → OAuth client ID → Web application**, add the redirect URL that n8n
   shows when you create the credential (usually `http://localhost:5678/rest/oauth2-credential/callback`).
4. In n8n, open *Ask approver (wait)* and create a **Gmail OAuth2** credential. Paste the client ID and secret, then
   sign in. Pick the same credential on *Create Gmail draft*. Do the same with a **Google Docs OAuth2** credential on
   *Append entry to Google Doc*.

While the Google app stays in *Testing*, Google expires the sign-in after 7 days. Click *Reconnect* on the
credential before a weekly run.

### 3. Pick a free LLM

The *Free LLM: polish pulse* node calls any OpenAI-compatible chat API. Choose one and set the two Config fields
plus one credential:

| Option | `llmBaseUrl` | `llmModel` | Credential (*Header Auth*: name `Authorization`) |
|---|---|---|---|
| **Gemini free tier** (default) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.8-flash` (or `gemini-3.5-flash-lite`) | `Bearer <your key>`. Get the key free at https://aistudio.google.com |
| **Ollama, local** | `http://localhost:11434/v1` (npm n8n) or `http://host.docker.internal:11434/v1` (Docker n8n) | a model you pulled, e.g. `ollama pull gemma3` → `gemma3` | `Bearer ollama` (any value works) |
| No LLM | leave as is | leave as is | any value; the call fails and the data-driven pulse is used |

Gemini's free tier needs no card. Google may use free-tier prompts to improve its products; the prompts here contain
only public review text. Other OpenAI-compatible services with free models, such as Groq or OpenRouter, work too:
set their base URL and model.

### 4. Fill in Config

- `approverEmail`: who approves each run (your own Gmail is fine).
- `googleDocId`: URL of an empty Google Doc, for example "Groww Weekly Pulse Log".
- `llmBaseUrl`, `llmModel`: from step 3.
- Google Play fetch: `appId`, `country` (`in`), `lang` (`en`), `playSort` (`most_relevant` or `newest`),
  `recentDays` (84 = 12 weeks), `maxReviews` (500), `maxPages` (30 pages of 150).

Save, then **Activate**.

## Run it

**Demo with the CSV.** Open the *Upload reviews CSV* node, copy its production URL (`http://localhost:5678/form/…`),
and upload `data/groww_playstore_reviews.csv`. The approver gets an email with the pulse, the fee explainer and every
check. Click **Approve: log + create draft**; the entry is added to the end of the Google Doc and a draft appears in
Gmail → Drafts.

**Weekly.** Every Monday at 09:00 India time, the workflow fetches the last 12 weeks of Groww reviews straight from
Google Play and emails the approver. Your computer and n8n must be running at that time. Otherwise, open *Every Monday
09:00 IST* and click *Execute workflow* whenever you like.

## Where approval happens

In the **Ask approver (wait)** node. The run pauses (shown as *Waiting* under Executions) and nothing is written until
someone clicks **Approve** in the email. **Reject**, or no answer within 3 days, ends at *Rejected: nothing written*.
The customer-facing email is only ever saved as a draft.

On a local n8n, the Approve and Reject buttons point to `http://localhost:5678`, so click them on the computer running
n8n. To approve from your phone, expose n8n with a free tunnel (for example `cloudflared tunnel --url
http://localhost:5678`) and restart n8n with `-e WEBHOOK_URL=<tunnel URL>`.

## What was tested

In a local n8n 2.43.7, against mock servers that imitate Google Play and an OpenAI-compatible LLM:

| Scenario | Result |
|---|---|
| CSV upload, LLM returns a valid draft (wrapped in `<think>` tags and a code fence) | Draft cleaned and used; every other field identical to the Python run |
| LLM changes one number (189 → 190) | Draft rejected; pulse, payload and email identical to the Python run |
| LLM returns HTTP 429 (free-tier limit) | "HTTP 429: free-tier rate limit reached"; data-driven pulse used |
| Google Play fetch: 530 reviews over 4 pages, 30 older than 12 weeks | 30 old reviews dropped; 500 kept; same analysis as the CSV |
| Header Auth credential | Arrives as `Authorization: Bearer …`, as Gemini and Ollama expect |
| Approve / Reject | Approve reaches the doc + draft branch; Reject reaches *Rejected: nothing written* |
| n8n parameter checker on every node | No issues |

Not tested from here: live calls to Google Play, Gemini, Ollama, Gmail and Google Docs. My test environment can't
reach those services, so the first real run happens on your machine. If Google Play returns nothing or changes its
format, the run stops with a clear message to use the CSV upload instead.

## Notes

- **Google Play fetch is unofficial.** It calls the public endpoint the Play Store web page uses, the same request as
  the open-source google-play-scraper. It is fine for light weekly use (one request at a time, with a short pause),
  but Google can change it without notice. The CSV upload always works.
- **New fee issues.** If reviews point to a charge with no verified explainer, *Build outputs* stops before approval.
  Add the charge to `FEE_KB` in `prototype/engine.js` with two official sources, then rebuild.
- **Rebuild.** The Code nodes are generated from `prototype/engine.js`: `python n8n/build_workflow.py`, then re-import.
  `--test DIR` also writes the test workflows used above.

## Sources

- [n8n pricing](https://n8n.io/pricing/): Cloud plans and trial; self-hosted version on GitHub
- [n8n Docker install](https://docs.n8n.io/hosting/installation/docker/)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing): free-tier models and data use
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai): base URL and Bearer key
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility): local `/v1/chat/completions`
- [google-play-scraper](https://www.npmjs.com/package/google-play-scraper) v10.1.4: the review request this workflow mirrors
