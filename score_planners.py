# AI Visibility Checker - Step 3 + 4: give each planner a visibility score and a group.
# Reads a visibility file made by check_planners.py and works out:
#   score = times the planner was mentioned / total questions asked for THEIR town
# Doesn't ask Claude anything, so you can run it any time.
#
# KEEP HISTORY: it saves to a NEW dated file, e.g. results/2026-11-17_scores.csv
# (same date as the visibility run it came from). Old files are never overwritten.
#
# How to run:
#   python score_planners.py                                      (uses the newest run)
#   python score_planners.py results/2026-11-17_visibility.csv    (uses a specific run)

import csv
import sys

from check_planners import load_planners
from history import latest_path, new_path, run_date


# Step 4: sort each planner into ONE group, checking the rules in this order.
# (A 5.0 rating from only 3 reviews is weak proof, so few-review planners get their own group.)
def pick_group(rating, reviews, score_percent):
    if rating >= 4.5 and reviews >= 10 and score_percent < 30:
        return "hidden gem"
    if rating >= 4.5 and reviews >= 10 and score_percent >= 30:
        return "already winning"
    if rating >= 4.5 and reviews < 10:
        return "new - needs more reviews"
    return "skip"


# Step 7: "near hidden gem" = great rating, ALMOST enough reviews (7-9), low AI score.
# A few more reviews and they'd count as a hidden gem. This is an extra label - it doesn't
# change the group above, so groups stay comparable with older runs.
def near_hidden_gem(rating, reviews, score_percent):
    return rating >= 4.5 and 7 <= reviews <= 9 and score_percent < 30


def to_number(text):
    """Turn '4.8' or '1,200' into a number. Empty cell -> 0."""
    text = (text or "").replace(",", "").strip()
    return float(text) if text else 0


def main(visibility_path=None):
    visibility_path = visibility_path or latest_path("visibility")
    print(f"\nScoring answers from {visibility_path}")
    planners = load_planners()

    with open(visibility_path, newline="", encoding="utf-8-sig") as f:
        results = list(csv.DictReader(f))

    rows = []
    for p in planners:
        town = p["town"].strip()
        town_answers = [r for r in results if r["town"] == town]
        mentioned = sum(
            p["name"] in r["planners_mentioned"].split(" | ") for r in town_answers
        )
        asked = len(town_answers)
        percent = round(100 * mentioned / asked) if asked else 0
        rating, reviews = to_number(p["google_rating"]), to_number(p["review_count"])
        rows.append({
            "name": p["name"],
            "town": town,
            "times_mentioned": mentioned,
            "total_asked": asked,
            "score_percent": percent,
            "group": pick_group(rating, reviews, percent),
            "label": "near hidden gem" if near_hidden_gem(rating, reviews, percent) else "",
        })

    out_path = new_path("scores", day=run_date(visibility_path))
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nVISIBILITY SCORES (how often Claude mentioned them for their own town):")
    for r in rows:
        print(f"  {r['name']:<28} {r['town']:<16} "
              f"{r['times_mentioned']}/{r['total_asked']} = {r['score_percent']:>3}%   -> {r['group']}"
              + (f"  ({r['label']})" if r["label"] else ""))
    print(f"Saved to {out_path} (open it in Excel).")
    return out_path


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
