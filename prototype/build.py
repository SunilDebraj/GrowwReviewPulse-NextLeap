"""Assemble the single-file prototype: template + engine.js + bundled reviews CSV.

Writes two copies of the same page:
  prototype/groww_review_pulse.html  page body for the Claude artifact (the host adds <html>/<head>)
  docs/index.html                    complete web page for GitHub Pages (free hosting)
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
REPO_URL = "https://github.com/SunilDebraj/GrowwReviewPulse-NextLeap"

rows = list(csv.DictReader((ROOT / "data" / "groww_playstore_reviews.csv").open(encoding="utf-8")))
data = [[r["review_id"], r["date"], int(r["rating"]), int(r["helpful_count"] or 0), r["text"]] for r in rows]
html = (HERE / "template.html").read_text(encoding="utf-8")
html = html.replace("/*__ENGINE__*/", (HERE / "engine.js").read_text(encoding="utf-8"))
html = html.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
html = html.replace("__REPO_URL__", REPO_URL)

out = HERE / "groww_review_pulse.html"
out.write_text(html, encoding="utf-8")
print(out, f"{out.stat().st_size / 1024:.0f} KB", len(data), "reviews")

# Full document for GitHub Pages: head = title + fonts + styles, body = the rest.
cut = html.index("</style>") + len("</style>")
head, body = html[:cut], html[cut:]
page = (
    "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">\n"
    "<meta name=\"description\" content=\"Groww Play Store reviews turned into a weekly product pulse and a fee explainer, with an approval gate before anything is logged or drafted.\">\n"
    "<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
    "body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style>\n"
    + head + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"
)
docs = ROOT / "docs"
docs.mkdir(exist_ok=True)
(docs / "index.html").write_text(page, encoding="utf-8")
(docs / ".nojekyll").write_text("", encoding="utf-8")   # serve the file as-is
print(docs / "index.html", f"{(docs / 'index.html').stat().st_size / 1024:.0f} KB")
