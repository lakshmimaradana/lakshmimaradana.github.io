# AI Visibility Checker - Step 2: which wedding planners does Claude recommend?
# For each town in planners.csv, asks Claude (with live web search) 2 questions,
# then checks which planner names from planners.csv show up in each answer.
# Results are saved to a NEW dated file each run, e.g. results/2026-11-17_visibility.csv
# (KEEP HISTORY rule - old runs are never overwritten). Open it in Excel.
# Uses your Claude subscription through Claude Code - no extra API bill.

import csv
import os
import re
import shutil
import subprocess
from datetime import date

from history import new_path

# Find the Claude Code program on this computer
# (copied from the old check_claude.py experiment, now in old_experiments/)
claude = shutil.which("claude") or os.path.join(
    os.path.expanduser("~"), ".local", "bin", "claude.exe"
)


# Split an answer into (what it said, the websites it used)
# (copied from the old check_claude.py experiment, now in old_experiments/)
def split_answer(answer):
    parts = re.split(r"\n\s*\**sources\**:?", answer, maxsplit=1, flags=re.IGNORECASE)
    said = parts[0]
    links = re.findall(r"https?://[^\s)\]>\"']+", answer)
    sites = []
    for link in links:
        site = re.sub(r"^https?://(www\.)?", "", link).split("/")[0].lower()
        if site not in sites:
            sites.append(site)
    return said, sites

# How many times to ask each question. AI answers change from run to run,
# so we ask 5 times and count how often each planner shows up (Step 3).
RUNS = 5

QUESTIONS = [
    "Who are the best wedding planners near {town}, PA?",
    "Recommend a wedding planner for a small wedding near {town}, PA",
]

# Words that don't help tell businesses apart, so we ignore them when matching
FILLER_WORDS = {"llc", "inc", "co", "company", "the", "ltd"}


# 1. Read the planner list
def load_planners(path="planners.csv"):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.DictReader(f) if row["name"].strip()]


# 2. Make text easy to compare: lowercase, "&" -> "and", no punctuation, no filler words
def simplify(text):
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w not in FILLER_WORDS]
    return " " + " ".join(words) + " "   # spaces at both ends = whole-word matching


# 3. Which planner names appear in this answer?
def find_mentions(answer, planners):
    clean_answer = simplify(answer)
    return [p["name"] for p in planners if simplify(p["name"]) in clean_answer]


# 4. Ask Claude one question, allowing ONLY web search + reading web pages (nothing else)
def ask_claude(question):
    prompt = (question + " Please name specific businesses. "
              "At the end, list the web pages you used under 'Sources:'.")
    result = subprocess.run(
        [claude, "-p", prompt, "--allowedTools", "WebSearch,WebFetch"],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    if result.returncode != 0:
        return "ERROR: " + (result.stderr or result.stdout).strip()[:200]
    return result.stdout.strip()


if __name__ == "__main__":
    planners = load_planners()
    towns = list(dict.fromkeys(p["town"].strip() for p in planners))  # unique, keeps order
    total = len(towns) * len(QUESTIONS) * RUNS
    print(f"{len(planners)} planners, {len(towns)} towns -> {total} questions to ask.")
    print("Each one takes about 30-90 seconds because Claude searches the web.\n")

    # KEEP HISTORY: save to a NEW dated file, e.g. results/2026-11-17_visibility.csv
    out_path = new_path("visibility")
    print(f"Saving answers to {out_path}\n")

    fields = ["date", "town", "question", "run_number", "answer", "sources", "planners_mentioned"]
    # Write the header now, then add one row after every answer,
    # so nothing is lost if the run stops halfway.
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()

    count = 0
    for town in towns:
        for template in QUESTIONS:
            question = template.format(town=town)
            for run in range(1, RUNS + 1):
                count += 1
                print(f"[{count}/{total}] (run {run}) {question}")
                answer = ask_claude(question)
                said, sites = split_answer(answer)
                mentioned = find_mentions(said, planners)
                print("   MENTIONED:", ", ".join(mentioned) or "(none of our planners)")
                print("   SOURCES:  ", ", ".join(sites) or "(none listed)")
                print("-" * 60)
                with open(out_path, "a", newline="", encoding="utf-8-sig") as f:
                    csv.DictWriter(f, fieldnames=fields).writerow({
                        "date": date.today().isoformat(),
                        "town": town,
                        "question": question,
                        "run_number": run,
                        "answer": said.strip(),
                        "sources": " | ".join(sites),
                        "planners_mentioned": " | ".join(mentioned),
                    })

    print(f"\nDone! Saved to {out_path} (open it in Excel).")

    # Step 3 + 4: turn the answers into a score and group for each planner
    import score_planners
    scores_path = score_planners.main(out_path)

    # Step 4b: which websites the AI relied on
    import analyze_sources
    analyze_sources.main(out_path)

    # Step 5: report + DRAFT message for each hidden gem (never sent automatically)
    import make_reports
    make_reports.main(scores_path, out_path)
