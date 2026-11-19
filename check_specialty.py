# AI Visibility Checker - Step 7: specialty questions.
# Some businesses are mainly florists/designers or small-wedding specialists, so asking only
# "wedding planner" questions may miss them. This asks the extra questions listed in
# specialty_questions.csv (edit that file to change them) and gives a SEPARATE specialty score.
#
# The normal planner scores are NOT changed - we only read them to compare.
# Same setup as check_planners.py: Claude with WebSearch,WebFetch, 5 runs per question.
#
# Saves (KEEP HISTORY - new dated files, old ones never overwritten):
#   results/<date>_specialty_visibility.csv - every answer
#   results/<date>_specialty_scores.csv     - specialty score vs planner score per business
# Then it re-makes the reports so they include the comparison.
#
# How to run:
#   python check_specialty.py               (asks Claude - takes a while)
#   python check_specialty.py --score-only  (just re-scores the newest specialty run, no Claude)
#
# Second test (Decor Co only: brand, vintage decor and Hollis Mansion questions):
#   python check_specialty.py --test specialty2
#   python check_specialty.py --test specialty2 --score-only
#   Questions: specialty_questions_2.csv
#   Saves:     results/<date>_specialty2_visibility.csv and results/<date>_specialty2_scores.csv
#              (one score per QUESTION, so the report can show each one separately)

import csv
import re
import sys
from collections import defaultdict
from datetime import date

from check_planners import ask_claude, find_mentions, load_planners, simplify, split_answer
from history import latest_path, new_path, run_date
from score_planners import near_hidden_gem, to_number

RUNS = 5

# Each test: its question file. Results are saved as results/<date>_<test>_visibility.csv
TESTS = {
    "specialty": "specialty_questions.csv",
    "specialty2": "specialty_questions_2.csv",
}

# Other names a business may be known by (we record these separately - they do NOT
# count towards the normal "mentioned by name" score)
OTHER_NAMES = {
    "Decor Co": ["Old Name Rentals", "Old Name Decor", "Old Name",
                                 "Decor Co Design", "Ellen Events & Design"],
}

# Brand questions ("What do you know about X?"): Claude repeats the name from the question
# even when it knows nothing, so instead we check whether it says it couldn't find them.
DONT_KNOW = [
    "couldn't find", "could not find", "can't find", "cannot find", "wasn't able to find",
    "was not able to find", "unable to find", "no information", "not find any", "didn't find",
    "did not find", "don't have", "do not have", "no record", "not familiar", "couldn't verify",
    "could not verify", "couldn't confirm", "could not confirm", "little information",
    "limited information", "no results", "doesn't appear", "does not appear", "not aware",
]


def knows_business(said):
    """YES    = talks about them, with no 'couldn't find' wording
    PARTLY = gives real details, but says information about them is thin
             (Claude often starts with "I found very little..." and then gives facts)
    NO     = says it couldn't find them, with hardly any details"""
    text = said.lower()
    if not any(p in text for p in DONT_KNOW):
        return "YES"
    return "PARTLY" if len(said) > 700 else "NO"


def knows_at_least_partly(value):
    # "UNSURE" is the older name for "PARTLY" (used in the first run's file)
    return value in ("YES", "PARTLY", "UNSURE")


def other_names_in(said, name):
    """Other names Claude used for this business: known ones from OTHER_NAMES, plus
    anything after 'also known as', 'formerly', 'operating as', 'doing business as'."""
    # Remove the official name first, so "Ellen Events & Design" isn't found inside
    # "Decor Co"
    text = simplify(said).replace(simplify(name), " ")
    found = [n for n in OTHER_NAMES.get(name, []) if simplify(n) in text]
    # Keep only the longest version (e.g. "Old Name Rentals", not also "Old Name")
    found = [n for n in found if not any(n != m and simplify(n) in simplify(m) for m in found)]
    # A name = 1-5 Capitalised words (so we don't grab the rest of the sentence)
    for m in re.finditer(r"\b(?:[Aa]lso known as|[Aa]\.?[Kk]\.?[Aa]\.?|[Ff]ormerly(?: known as)?|"
                         r"[Oo]perat(?:es|ing) as|[Dd]oing business as|[Dd]/[Bb]/[Aa])\s+[\"“*]*"
                         r"([A-Z][\w'’.-]*(?:\s+(?:&|and|of|[A-Z][\w'’.-]*)){0,4})", said):
        alias = m.group(1).strip(" .")
        if simplify(alias) in (simplify(name), "") or any(simplify(alias) == simplify(f)
                                                          for f in found):
            continue
        found.append(alias)
    return found


def load_questions(path="specialty_questions.csv"):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r["name"].strip()]


def ask_all(test="specialty"):
    planners = {p["name"]: p for p in load_planners()}
    all_planners = list(planners.values())
    questions = load_questions(TESTS[test])
    unknown = {q["name"] for q in questions} - set(planners)
    if unknown:
        sys.exit(f"These names in {TESTS[test]} aren't in planners.csv: {unknown}")

    out_path = new_path(f"{test}_visibility")
    fields = ["date", "name", "town", "specialty", "topic", "question", "run_number",
              "answer", "sources", "planners_mentioned", "this_business_mentioned",
              "knows_business", "other_names", "score_hit"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()

    total = len(questions) * RUNS
    print(f"{total} specialty questions to ask (about 30-90 seconds each).")
    print(f"Saving answers to {out_path}\n")
    count = 0
    for q in questions:
        town = planners[q["name"]]["town"].strip()
        question = q["question"].format(town=town)
        topic = q.get("topic", "")
        for run in range(1, RUNS + 1):
            count += 1
            print(f"[{count}/{total}] {q['name']} - (run {run}) {question}")
            said, sites = split_answer(ask_claude(question))
            mentioned = find_mentions(said, all_planners)
            hit = q["name"] in mentioned
            knows = knows_business(said) if topic == "brand" else ""
            others = other_names_in(said, q["name"])
            # What counts towards the score: for brand questions "does it know them",
            # for everything else "did it mention them by name"
            score_hit = knows_at_least_partly(knows) if topic == "brand" else hit
            print("   " + (f"KNOWS THEM: {knows}" if topic == "brand"
                           else f"THIS BUSINESS MENTIONED: {'YES' if hit else 'no'}")
                  + (f" | other names: {', '.join(others)}" if others else "")
                  + " | sources: " + (", ".join(sites) or "(none)"))
            with open(out_path, "a", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=fields).writerow({
                    "date": date.today().isoformat(), "name": q["name"], "town": town,
                    "specialty": q["specialty"], "topic": topic, "question": question,
                    "run_number": run, "answer": said.strip(), "sources": " | ".join(sites),
                    "planners_mentioned": " | ".join(mentioned),
                    "this_business_mentioned": "YES" if hit else "NO",
                    "knows_business": knows,
                    "other_names": " | ".join(others),
                    "score_hit": "YES" if score_hit else "NO",
                })
    print(f"\nDone! Saved to {out_path}")
    return out_path


def score_per_question(test, visibility_path=None):
    """One score per business per question (used for the second test)."""
    visibility_path = visibility_path or latest_path(f"{test}_visibility")
    print(f"\nScoring {visibility_path} (one score per question)")
    with open(visibility_path, newline="", encoding="utf-8-sig") as f:
        answers = [r for r in csv.DictReader(f) if not r["answer"].startswith("ERROR")]

    groups = defaultdict(list)
    for r in answers:
        # Re-check from the saved answer text, so improved rules apply to old runs too
        if r["topic"] == "brand":
            r["knows_business"] = knows_business(r["answer"])
        r["other_names"] = " | ".join(other_names_in(r["answer"], r["name"]))
        groups[(r["name"], r["topic"], r["question"])].append(r)

    rows = []
    for (name, topic, question), rs in groups.items():
        if topic == "brand":
            hits = sum(knows_at_least_partly(r["knows_business"]) for r in rs)
        else:
            hits = sum(r["this_business_mentioned"] == "YES" for r in rs)
        names_seen = sorted({n for r in rs for n in r["other_names"].split(" | ") if n})
        # Mentioned under ANY of their names (official name, or one of their other names)
        any_name = ("" if topic == "brand" else
                    sum(r["this_business_mentioned"] == "YES" or bool(r["other_names"]) for r in rs))
        rows.append({
            "name": name, "town": rs[0]["town"], "topic": topic, "question": question,
            "measures": ("knows the business (clearly or partly)" if topic == "brand"
                         else "mentioned by official name"),
            "hits": hits, "asked": len(rs), "score_percent": round(100 * hits / len(rs)),
            "mentioned_any_name": any_name,
            "knows_clearly_partly_no": (" / ".join(str(sum(r["knows_business"] == k for r in rs))
                                                   for k in ("YES", "PARTLY", "NO"))
                                        if topic == "brand" else ""),
            "answers_with_other_names": sum(bool(r["other_names"]) for r in rs),
            "other_names_seen": " | ".join(names_seen),
        })

    out_path = new_path(f"{test}_scores", day=run_date(visibility_path))
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nSCORE PER QUESTION:")
    for r in rows:
        print(f"  {r['name']} | {r['topic']:<17} {r['measures']:<26} "
              f"{r['hits']}/{r['asked']} = {r['score_percent']:>3}%"
              + (f"  | under any of their names: {r['mentioned_any_name']}/{r['asked']}"
                 if r["mentioned_any_name"] != "" else "")
              + (f"  | other names: {r['other_names_seen']}" if r["other_names_seen"] else ""))
    print(f"Saved to {out_path} (open it in Excel).")
    return out_path


def score(visibility_path=None, planner_scores_path=None):
    visibility_path = visibility_path or latest_path("specialty_visibility")
    planner_scores_path = planner_scores_path or latest_path("scores")
    print(f"\nScoring {visibility_path}\n(comparing with planner scores in {planner_scores_path})")

    with open(visibility_path, newline="", encoding="utf-8-sig") as f:
        answers = [r for r in csv.DictReader(f) if not r["answer"].startswith("ERROR")]
    with open(planner_scores_path, newline="", encoding="utf-8-sig") as f:
        planner_scores = {r["name"]: r for r in csv.DictReader(f)}
    planners = {p["name"]: p for p in load_planners()}

    by_name = defaultdict(list)
    for r in answers:
        by_name[r["name"]].append(r)

    rows = []
    for name, rs in by_name.items():
        hits = sum(r["this_business_mentioned"] == "YES" for r in rs)
        ps = planner_scores.get(name, {})
        p_percent = int(ps.get("score_percent", 0))
        p = planners[name]
        rows.append({
            "name": name,
            "town": rs[0]["town"],
            "specialty": rs[0]["specialty"],
            "specialty_mentioned": hits,
            "specialty_asked": len(rs),
            "specialty_score_percent": round(100 * hits / len(rs)),
            "planner_mentioned": ps.get("times_mentioned", ""),
            "planner_asked": ps.get("total_asked", ""),
            "planner_score_percent": p_percent,
            "planner_group": ps.get("group", ""),
            "label": "near hidden gem" if near_hidden_gem(
                to_number(p["google_rating"]), to_number(p["review_count"]), p_percent) else "",
        })

    out_path = new_path("specialty_scores", day=run_date(visibility_path))
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nSPECIALTY SCORE vs PLANNER SCORE:")
    for r in rows:
        print(f"  {r['name']:<26} {r['specialty']:<24} specialty "
              f"{r['specialty_mentioned']}/{r['specialty_asked']} = {r['specialty_score_percent']:>3}%"
              f"  | planner {r['planner_mentioned']}/{r['planner_asked']} = {r['planner_score_percent']:>3}%"
              + (f"  ({r['label']})" if r["label"] else ""))
    print(f"Saved to {out_path} (open it in Excel).")
    return out_path


if __name__ == "__main__":
    test = sys.argv[sys.argv.index("--test") + 1] if "--test" in sys.argv else "specialty"
    if test not in TESTS:
        sys.exit(f"Unknown test '{test}'. Choose one of: {', '.join(TESTS)}")
    path = None if "--score-only" in sys.argv else ask_all(test)
    if test == "specialty":
        score(path)
    else:
        score_per_question(test, path)
    import make_reports
    make_reports.main()
