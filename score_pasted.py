# AI Visibility Checker - Step 8 (part 2): score the answers you pasted.
# Reads pasted_answers/<date>/*.txt (made by open_checks.py, filled in by you), and for each
# file that has an answer:
#   - finds the official name and the old/other names (same lists as the Claude checks)
#   - finds the position: the business's number in the answer's numbered list (#1, #2 ...)
#   - finds website names and links (the "Sources" list + any in the answer text)
#   - checks whether the business's own website is among the sources
# Then adds one row per file to other_ai_checks.csv, marked "hand check (pasted)".
# A file is never added twice. Empty files (nothing pasted) are skipped.
# Afterwards, run make_reports.py (this script does it for you at the end).
#
# How to run:
#   python score_pasted.py                       (today's folder)
#   python score_pasted.py pasted_answers/2026-11-17
#   python score_pasted.py --no-reports          (don't re-make the reports)
#   python score_pasted.py pasted_answers/2026-11-18 --rescore florist
#        (score matching files again and REPLACE their old rows, e.g. after a scoring fix)
#
# Position: the business's number in the answer's numbered list. If the answer starts with
# a places/map list AND then gives a written recommendation ("My top pick is X" = #1, or a
# written shortlist), the written rank is used; if the map list differs, a note is added
# ("map list: #2").

import csv
import glob
import os
import re
import sys
from datetime import date

from check_planners import load_planners, simplify
from check_specialty import knows_business, other_names_in
from make_reports import website_domain

CHECKS_FILE = "other_ai_checks.csv"
PASTE_LINE = "--- paste the full answer below this line ---"
METHOD = "hand check (pasted)"

# File topics -> the topic names already used in other_ai_checks.csv, so they group together
TOPIC_ALIASES = {"Hollis Mansion venue": "Hollis Mansion"}

FIELDS = ["date", "tool", "business", "topic", "question", "tries", "mentioned", "rank",
          "name_used", "described_as", "category_shown", "sources", "notes",
          "method", "official_site_used", "other_names_seen", "source_file"]


# ---------- 1. Reading one pasted file ----------

def read_pasted(path):
    """-> (header dict, answer text, list of source domains), or None if nothing was pasted."""
    text = open(path, encoding="utf-8-sig").read()
    if PASTE_LINE not in text:
        return None
    head, body = text.split(PASTE_LINE, 1)
    body = body.strip()
    if not body:
        return None
    header = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            header[key.strip().lower()] = value.strip()
    # Split the answer from its "Sources" list (a line that just says "Sources")
    parts = re.split(r"(?im)^\s*sources\s*:?\s*$", body, maxsplit=1)
    answer = parts[0].strip()
    sources = []
    if len(parts) > 1:
        for line in parts[1].splitlines():
            m = re.match(r"\s*(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", line.lower())
            if m and m.group(1) not in sources:
                sources.append(m.group(1))
    return header, answer, sources


def websites_in_text(answer):
    """Website names or links written inside the answer itself (e.g. 'decor-co.example')."""
    found = re.findall(r"(?i)\b(?:https?://)?(?:www\.)?([a-z0-9-]+\.(?:com|org|net|ai|co|us|io))\b",
                       answer)
    return list(dict.fromkeys(f.lower() for f in found))


# ---------- 2. Finding the business and its position ----------

def names_for(business):
    from check_specialty import OTHER_NAMES
    return [business] + OTHER_NAMES.get(business, [])


def split_map_list(answer):
    """Some answers start with a places/map list (business, address, star rating) and THEN give
    a written recommendation. Returns (map list text, rest of the answer).
    The map list is found by a line like "(Places list shown first:)" / "(Map/places list ...)",
    or by a first numbered list whose items look like map results ("4.7 (10)")."""
    lines = answer.splitlines()
    is_item = lambda line: re.match(r"\s*\d+[.)]\s", line)

    # 1. A marker line near the top, e.g. "(Places list shown first:)"
    marker = next((i for i, l in enumerate(lines[:5])
                   if re.search(r"(?i)\b(places|map)\b.*\blist\b", l)), None)
    if marker is not None:
        start, keep_before = marker + 1, marker          # drop the marker line itself
    else:
        # 2. No marker: a numbered list right at the top whose items end in star ratings
        start = next((i for i, l in enumerate(lines[:4]) if is_item(l)), None)
        if start is None:
            return "", answer
        keep_before = start

    end = start
    while end < len(lines) and (is_item(lines[end]) or not lines[end].strip()):
        end += 1
    numbered = [l for l in lines[start:end] if is_item(l)]
    if not numbered:
        return "", answer
    if marker is None:
        ratings = sum(bool(re.search(r"\b\d\.\d\s*(\(\d+\))?\s*$", l)) for l in numbered)
        if ratings < len(numbered) / 2:
            return "", answer                            # just a normal list, not a map list
    return "\n".join(numbered), "\n".join(lines[:keep_before] + lines[end:])


TOP_PICK = re.compile(r"(?i)\b(?:my (?:top|first|#1) (?:pick|choice|recommendation)|"
                      r"i'?d start with|i would start with)\b")


def written_top_pick(text, business):
    """True if the written text names this business as its top pick, e.g. "My top pick is X".
    Only counts when the name comes right after the phrase (before the next comma / 'with'),
    so "My top pick is Petals, with X a strong second" does NOT count for X."""
    keys = [simplify(n) for n in names_for(business)]
    for m in TOP_PICK.finditer(text):
        after = re.split(r",|;|\.|\bwith\b|\band\b", text[m.end():], maxsplit=1)[0]
        if any(k in simplify(after) for k in keys):
            return True
    return False


def ranked_position(answer, business):
    """Position of the business, preferring the WRITTEN recommendation over a places/map list.
    Returns (rank, name as written, note)."""
    map_text, rest = split_map_list(answer)
    if not map_text:
        rank, name = list_position(answer, business)
        return rank, name, ""
    map_rank, map_name = list_position(map_text, business)
    list_rank, list_name = list_position(rest, business)
    written = 1 if written_top_pick(rest, business) else list_rank
    name = list_name or map_name
    if written is None:
        return map_rank, name, ("rank from the map list only" if map_rank else "")
    note = f"map list: #{map_rank}" if map_rank and map_rank != written else ""
    return written, name, note


def list_position(answer, business):
    """Number of the numbered-list item that STARTS with one of the business's names.
    Returns (rank, name as written there) or (None, None)."""
    keys = [simplify(n) for n in names_for(business)]
    for m in re.finditer(r"(?m)^\s*(\d+)[.)]\s+(.+)$", answer):
        # The business name is the part before " - " / ":" (the rest is description)
        head = re.split(r"\s+[-–—]\s+|:\s", m.group(2), maxsplit=1)[0].strip(" *")
        if any(k in simplify(head) for k in keys):
            return int(m.group(1)), head
    return None, None


def score_file(path, planners):
    parsed = read_pasted(path)
    if not parsed:
        return None, []
    header, answer, sources = parsed
    business = header.get("business", "")
    planner = planners.get(business)
    flags = []
    if not planner:
        return None, [f"business '{business}' is not in planners.csv - skipped"]
    topic = TOPIC_ALIASES.get(header.get("topic", ""), header.get("topic", ""))
    tool = header.get("platform", "")

    official = simplify(business) in simplify(answer)
    others = other_names_in(answer, business)
    # Written recommendation wins over a places/map list at the top (note if they differ)
    rank, name_in_list, rank_note = ranked_position(answer, business)

    if topic == "brand":
        # The name is in the question, so "mentioned" means "does it actually know them"
        mentioned = "YES" if knows_business(answer) in ("YES", "PARTLY") else "NO"
        rank, name_used = None, ""
    else:
        mentioned = "YES" if (official or others) else "NO"
        if name_in_list:
            name_used = name_in_list
        elif official:
            name_used = business
        else:
            name_used = " / ".join(others)
        if mentioned == "YES" and rank is None:
            flags.append("named, but not in a numbered list - rank left empty")

    domain = website_domain(planner.get("website"))
    all_sites = list(dict.fromkeys(sources + websites_in_text(answer)))
    notes = []
    if rank_note and topic != "brand" and mentioned == "YES":
        notes.append(rank_note)
    if tool.startswith("Google"):
        notes.append("Google results may be personalized")
    if not sources:
        flags.append("no 'Sources' list found")
    row = {
        "date": header.get("date", ""), "tool": tool, "business": business, "topic": topic,
        "question": header.get("question", ""), "tries": "1", "mentioned": mentioned,
        "rank": str(rank) if rank else "", "name_used": name_used, "described_as": "",
        "category_shown": "", "sources": " | ".join(all_sites), "notes": "; ".join(notes),
        "method": METHOD,
        "official_site_used": ("YES" if domain and domain in all_sites else "NO") if domain else "",
        "other_names_seen": " | ".join(others),
        "source_file": path.replace("\\", "/"),
    }
    return row, flags


# ---------- 3. Adding the rows ----------

def main():
    argv = sys.argv[1:]
    rescore = None
    if "--rescore" in argv:
        i = argv.index("--rescore")
        rescore = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    folder = args[0] if args else os.path.join("pasted_answers", date.today().isoformat())
    files = sorted(glob.glob(os.path.join(folder, "*.txt")))
    if not files:
        sys.exit(f"No .txt files in {folder}. Run open_checks.py first.")

    with open(CHECKS_FILE, newline="", encoding="utf-8-sig") as f:
        existing = list(csv.DictReader(f))

    # --rescore <part of a file name>: score those files again, replacing their old rows
    if rescore is not None:
        targets = {p.replace("\\", "/") for p in files if rescore in os.path.basename(p)}
        if not targets:
            sys.exit(f"--rescore '{rescore}' matched no file in {folder}")
        before = len(existing)
        existing = [r for r in existing if r.get("source_file", "") not in targets]
        print(f"Re-scoring {len(targets)} file(s); removed {before - len(existing)} old row(s).\n")
        files = sorted(p for p in files if p.replace("\\", "/") in targets)
    already = {r.get("source_file", "") for r in existing}
    planners = {p["name"]: p for p in load_planners()}

    new_rows, skipped_empty = [], 0
    for path in files:
        key = path.replace("\\", "/")
        if key in already:
            print(f"already added: {os.path.basename(path)}")
            continue
        row, flags = score_file(path, planners)
        if row is None:
            if flags:
                print(f"SKIPPED {os.path.basename(path)}: {flags[0]}")
            else:
                skipped_empty += 1
            continue
        new_rows.append(row)
        where = f"#{row['rank']}" if row["rank"] else ("knows you" if row["topic"] == "brand"
                                                        and row["mentioned"] == "YES" else "-")
        print(f"{row['tool']:<10} {row['topic']:<30} mentioned: {row['mentioned']:<3} {where:<9}"
              f" name: {row['name_used'] or '-':<40} own site: {row['official_site_used']}")
        for flag in flags:
            print(f"    check this: {flag}")

    if not new_rows:
        print(f"\nNothing new to add ({skipped_empty} empty file(s) skipped).")
        return
    # Keep all old rows; old rows simply have empty values in the new columns
    with open(CHECKS_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing + new_rows)
    print(f"\nAdded {len(new_rows)} row(s) to {CHECKS_FILE} as \"{METHOD}\""
          f" ({skipped_empty} empty file(s) skipped).")

    if "--no-reports" not in sys.argv:
        print()
        import make_reports
        make_reports.main()


if __name__ == "__main__":
    main()
