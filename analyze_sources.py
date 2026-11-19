# AI Visibility Checker - Step 4b: which websites does the AI rely on?
# Reads a visibility file made by check_planners.py. Doesn't ask Claude anything.
#
# AI answers change from run to run, so we look for PATTERNS across all answers
# instead of trusting any single one.
# NOTE: the order of sources is NOT a trust ranking. It's only useful as a pattern
# across many runs (e.g. "zola.com is usually listed first").
#
# Saves (KEEP HISTORY - new dated files, old ones are never overwritten):
#   results/<date>_sources_summary.csv - one row per website: how often it appears, how often it's first
#   results/<date>_planner_sources.csv - for each planner: which websites showed up in answers
#                                        where they WERE mentioned vs where they were NOT
#
# How to run:
#   python analyze_sources.py                                      (uses the newest run)
#   python analyze_sources.py results/2026-11-17_visibility.csv    (uses a specific run)

import csv
import re
import sys
from collections import defaultdict

from check_planners import load_planners
from history import latest_path, new_path, run_date


def pct(part, whole):
    return round(100 * part / whole) if whole else 0


def clean_sources(sources_text):
    """'zola.com | zola.com:443 | m.weddingwire.com | theknot.com'
       -> ['zola.com', 'weddingwire.com', 'theknot.com']
    (":443" is just a technical port number, and "m." is the mobile version of the same site)"""
    cleaned = [re.sub(r"^m\.", "", s.split(":")[0]) for s in sources_text.split(" | ") if s]
    return list(dict.fromkeys(cleaned))  # remove repeats, keep order


def main(visibility_path=None):
    visibility_path = visibility_path or latest_path("visibility")
    print(f"\nAnalyzing sources in {visibility_path}")
    day = run_date(visibility_path)
    planners = load_planners()
    with open(visibility_path, newline="", encoding="utf-8-sig") as f:
        # Skip answers where Claude failed (they have no real content)
        answers = [r for r in csv.DictReader(f) if not r["answer"].startswith("ERROR")]
    for r in answers:
        r["source_list"] = clean_sources(r["sources"])
        r["mentioned_list"] = [m for m in r["planners_mentioned"].split(" | ") if m]

    total = len(answers)

    # ---------- Part 1: sources_summary.csv ----------
    appears = defaultdict(int)
    first = defaultdict(int)
    positions = defaultdict(list)
    for r in answers:
        for position, site in enumerate(r["source_list"], start=1):
            appears[site] += 1
            positions[site].append(position)
            if position == 1:
                first[site] += 1

    summary = []
    for site in appears:
        summary.append({
            "source": site,
            "appears_in": appears[site],
            "appears_in_percent": pct(appears[site], total),
            "first_place": first[site],
            "first_place_percent": pct(first[site], total),
            "avg_position": round(sum(positions[site]) / len(positions[site]), 1),
        })
    summary.sort(key=lambda row: (-row["appears_in"], row["avg_position"]))

    summary_path = new_path("sources_summary", day=day)
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)

    avg_sources = sum(len(r["source_list"]) for r in answers) / total if total else 0
    print(f"Looked at {total} answers. Average number of sources per answer: {avg_sources:.1f}")
    print("\nTOP WEBSITES THE AI USED (out of all answers):")
    for row in summary[:10]:
        print(f"  {row['source']:<30} in {row['appears_in']:>2} answers ({row['appears_in_percent']:>3}%)"
              f"  | listed first {row['first_place']:>2}x  | avg position {row['avg_position']}")

    # ---------- Part 2: planner_sources.csv ----------
    # For each planner we only look at answers for THEIR OWN town (same as the score),
    # so we compare like with like.
    rows = []
    print("\nWHICH SOURCES SHOWED UP WHEN EACH PLANNER WAS / WASN'T MENTIONED (own town only):")
    for p in planners:
        town_answers = [r for r in answers if r["town"] == p["town"].strip()]
        with_them = [r for r in town_answers if p["name"] in r["mentioned_list"]]
        without_them = [r for r in town_answers if p["name"] not in r["mentioned_list"]]
        print(f"\n  {p['name']} ({p['town']}): mentioned in {len(with_them)} of {len(town_answers)} answers")

        sites = sorted({s for r in town_answers for s in r["source_list"]})
        for site in sites:
            n_with = sum(site in r["source_list"] for r in with_them)
            n_without = sum(site in r["source_list"] for r in without_them)
            if not with_them:
                pattern = "planner never mentioned"
            elif not without_them:
                pattern = "planner always mentioned"
            elif n_with and not n_without:
                pattern = "ONLY when mentioned"
            elif n_without and not n_with:
                pattern = "ONLY when NOT mentioned"
            else:
                pattern = "both"
            rows.append({
                "planner": p["name"],
                "town": p["town"],
                "source": site,
                "used_when_mentioned": f"{n_with} of {len(with_them)}",
                "used_when_not_mentioned": f"{n_without} of {len(without_them)}",
                "pattern": pattern,
            })
            if pattern.startswith("ONLY"):
                print(f"     {site:<30} {pattern}  "
                      f"(used in {n_with} of {len(with_them)} mentioned / "
                      f"{n_without} of {len(without_them)} not mentioned)")

    planner_path = new_path("planner_sources", day=day)
    with open(planner_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {summary_path} and {planner_path} (open them in Excel).")
    print("Reminder: with only 10 answers per town, these are hints, not proof.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
