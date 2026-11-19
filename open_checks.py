# AI Visibility Checker - Step 8 (part 1): the free "check helper".
# Opens each question as a prefilled link in your default browser, one tab per question
# per platform, and creates one empty .txt file per tab for you to paste the answer into.
#
# It does NOT read, type or click anything on ChatGPT / Perplexity / Google.
# You ask (the question is already filled in), read, and copy the answer yourself.
#
# How to run:
#   python open_checks.py --business "Decor Co" --platform perplexity
#   python open_checks.py --business "Florist" --platform chatgpt
#   python open_checks.py --business "Decor Co"                 (all 3 platforms)
#   python open_checks.py --business "Decor Co" --dry-run       (list only, open nothing)
#
# Platforms: chatgpt, perplexity, google (= Google AI Mode)
# Questions: the same ones Claude gets - the 2 planner questions for the business's town,
#            plus its rows in specialty_questions.csv and specialty_questions_2.csv.
# Answer files: pasted_answers/<date>/<platform>__<business>__<topic>.txt
#               (existing files are never overwritten)

import argparse
import os
import re
import sys
import time
import webbrowser
from datetime import date
from urllib.parse import quote_plus

from check_planners import QUESTIONS, load_planners
from check_specialty import TESTS, load_questions

PLATFORMS = {
    "chatgpt": ("ChatGPT", "https://chatgpt.com/?q={q}&hints=search"),
    "perplexity": ("Perplexity", "https://www.perplexity.ai/search?q={q}"),
    "google": ("Google AI Mode", "https://www.google.com/search?q={q}&udm=50"),
}
PASTE_LINE = "--- paste the full answer below this line ---"

# Short topic names for the 2 planner questions (same order as QUESTIONS in check_planners.py)
PLANNER_TOPICS = ["{town} wedding planners", "{town} small-wedding planner"]


def slug(text):
    text = text.lower().replace("é", "e").replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def questions_for(business):
    """All questions for one business: (topic, question)."""
    town = business["town"].strip()
    out = [(t.format(town=town), q.format(town=town)) for t, q in zip(PLANNER_TOPICS, QUESTIONS)]
    for test, path in TESTS.items():
        if not os.path.exists(path):
            continue
        for q in load_questions(path):
            if q["name"] == business["name"]:
                out.append((q.get("topic") or q["question"], q["question"].format(town=town)))
    return out


def main():
    ap = argparse.ArgumentParser(description="Open prefilled AI questions in your browser.")
    ap.add_argument("--business", required=True, help='part of the name, e.g. "Decor Co"')
    ap.add_argument("--platform", choices=list(PLATFORMS), help="leave out for all 3")
    ap.add_argument("--dry-run", action="store_true", help="list the tabs and files, open nothing")
    args = ap.parse_args()

    matches = [p for p in load_planners() if args.business.lower() in p["name"].lower()]
    if len(matches) != 1:
        names = ", ".join(p["name"] for p in load_planners())
        sys.exit(f"'{args.business}' matched {len(matches)} businesses. Choose one of: {names}")
    business = matches[0]

    platforms = [args.platform] if args.platform else list(PLATFORMS)
    folder = os.path.join("pasted_answers", date.today().isoformat())
    os.makedirs(folder, exist_ok=True)

    todo = []
    for key in platforms:
        label, url_pattern = PLATFORMS[key]
        for topic, question in questions_for(business):
            url = url_pattern.format(q=quote_plus(question))
            path = os.path.join(folder, f"{key}__{slug(business['name'])}__{slug(topic)}.txt")
            if not os.path.exists(path):   # never overwrite an answer you already pasted
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"Platform: {label}\nBusiness: {business['name']}\nTopic: {topic}\n"
                            f"Question: {question}\nDate: {date.today().isoformat()}\n"
                            f"Link: {url}\n\n{PASTE_LINE}\n")
            todo.append((label, question, url, path))

    print(f"{business['name']} - {len(todo)} tab(s):\n")
    for i, (label, question, url, path) in enumerate(todo, 1):
        print(f"{i}. [{label}] {question}")
        print(f"   paste into: {path}")
        if not args.dry_run:
            webbrowser.open_new_tab(url)
            time.sleep(1.5)   # small pause so the browser doesn't drop tabs
    print("\nNext: in each tab, wait for the full answer, copy ALL of it (including the sources),")
    print(f"paste it below the '{PASTE_LINE}' line in the matching file, and save.")
    print("Leave a file empty if you skip that question - empty files are ignored.")
    if args.dry_run:
        print("\n(Dry run: no tabs were opened.)")


if __name__ == "__main__":
    main()
