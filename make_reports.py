# AI Visibility Checker - Step 5: a report + a draft first message for each hidden gem.
# Reads the newest scores file and visibility file in results/. Doesn't ask Claude anything.
#
# Step 7: if a specialty run exists (check_specialty.py), the report also compares the
# specialty score with the planner score. "Near hidden gems" get a report too.
#
# For each hidden gem / near hidden gem it makes:
#   reports/<date>_<planner>.html  - score, who AI recommended instead, which websites AI used,
#                                    2-3 honest suggested fixes. Open it in your browser.
#   messages/<date>_<planner>.txt  - a short, friendly DRAFT first message.
#                                    It is NEVER sent automatically - you read it and send it yourself.
# Everything in them comes from the real results - no made-up numbers or stories.
# KEEP HISTORY: one report + one message per business per DAY. Re-making them on the same day
# replaces that day's file; a different day gets its own dated file. (Raw results in results/
# are never replaced.) Older same-day versions from before this rule are in */old_versions/.
#
# How to run:
#   python make_reports.py                      (uses the newest results)
#   python make_reports.py results/2026-11-17_scores.csv results/2026-11-17_visibility.csv

import csv
import html
import re
import sys
from collections import Counter

from analyze_sources import clean_sources
from check_planners import load_planners, simplify
from history import day_path, latest_path, run_date
from score_planners import near_hidden_gem, to_number

TOP_N = 8  # how many names / websites to show in each list


# ---------- 1. Reading the results ----------

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# Claude writes each business as a bold list item, e.g. "- **Evviva Studio**: rated 5.0..."
# We pull out those bold names. Headings like "**Tips:**" or "**Other options**" are skipped.
NAME_AT_LINE_START = re.compile(r"^\s*(?:[-*]|\d+\.|\|)\s*\*\*(.+?)\*\*", re.M)
NOT_A_NAME = (
    "other", "before", "tips", "typical", "price", "ask", "check", "budget", "how", "if ",
    "free", "lower", "question", "caveat", "review", "cost", "service", "address", "why",
    "best", "you", "small", "day-of", "consider", "fit", "pick", "shortlist", "reputation",
    "next", "top", "where", "when", "what", "venue", "rated", "based", "closest", "in ",
    "nearby", "planners", "highly", "my ", "one", "all ", "mid", "higher", "cheaper", "good",
    "two", "things", "well", "most", "for ", "featured", "local", "starting", "listed", "on ",
)


# Bold headings that are a single topic word, not a business
GENERIC_HEADINGS = {"catering", "outside vendors", "flowers", "florals", "decor", "décor",
                    "rentals", "photography", "venue", "lighting", "linens", "portfolios",
                    "portfolio"}


def first_upper(text):
    """'Hollis Mansion venue' -> 'Hollis Mansion venue' (unlike .capitalize(), keeps other capitals)"""
    return text[:1].upper() + text[1:]


def business_names(answer):
    """Business names Claude listed in one answer -> {matching key: name as written}"""
    found = {}
    for raw in NAME_AT_LINE_START.findall(answer):
        name = re.sub(r"\s*\(.*?\)\s*", " ", raw).strip(" :.-")   # drop "(Susan Norcross)"
        low = name.lower()
        if (not name or len(name.split()) > 7 or low.startswith(NOT_A_NAME)
                or "$" in name or name[0].isdigit() or low in GENERIC_HEADINGS):
            continue
        found.setdefault(simplify(name).replace(" ", ""), name)
    return found


def website_domain(url):
    """'https://www.florist-event-co.example/about' -> 'florist-event-co.example'"""
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).split("/")[0]


# ---------- 2. Working out the facts for one planner ----------

def who_and_where(answers, own_name, top=TOP_N):
    """From a set of answers: who Claude named instead (each name counted once per answer),
    and which websites it used. The business itself (under any of its names) is left out."""
    from check_specialty import OTHER_NAMES
    own_keys = [simplify(n).replace(" ", "") for n in [own_name] + OTHER_NAMES.get(own_name, [])]
    name_counts, labels = Counter(), {}
    for r in answers:
        for key, name in business_names(r["answer"]).items():
            if not any(k in key for k in own_keys):
                name_counts[key] += 1
                labels.setdefault(key, name)
    instead = [(labels[k], n) for k, n in name_counts.most_common(top)]
    site_counts = Counter(s for r in answers for s in clean_sources(r["sources"]))
    return instead, site_counts.most_common(top)


def specialty_facts(name, spec_row, spec_answers):
    """Step 7: the separate specialty score (None if this business had no specialty questions)."""
    if not spec_row:
        return None
    mine = [r for r in spec_answers if r["name"] == name]
    instead, sites = who_and_where(mine, name, top=5)

    # Score per topic (e.g. "florist" and "event design"), using the topic column in
    # specialty_questions.csv to know which question is which
    from check_specialty import load_questions
    topic_of = {q["question"].format(town=r["town"]): q.get("topic") or q["question"]
                for q in load_questions() if q["name"] == name for r in mine[:1]}
    by_topic = {}
    for r in mine:
        topic = topic_of.get(r["question"], r["question"])
        hit, asked = by_topic.get(topic, (0, 0))
        by_topic[topic] = (hit + (r["this_business_mentioned"] == "YES"), asked + 1)
    topics = [{"topic": t, "mentioned": m, "total": n, "percent": round(100 * m / n)}
              for t, (m, n) in by_topic.items()]

    return {
        "label": spec_row["specialty"],
        "mentioned": int(spec_row["specialty_mentioned"]),
        "total": int(spec_row["specialty_asked"]),
        "percent": int(spec_row["specialty_score_percent"]),
        "topics": topics,
        "answers": mine,
        "questions": list(dict.fromkeys(r["question"] for r in mine)),
        "runs": max((int(r["run_number"]) for r in mine), default=0),
        "day": mine[0]["date"] if mine else "",
        "instead": instead, "sites": sites,
    }


def facts_for(planner, score, all_answers, all_scores, kind="hidden gem",
              spec_row=None, spec_answers=()):
    town = planner["town"].strip()
    town_answers = [r for r in all_answers if r["town"] == town]
    total = len(town_answers)

    # Who Claude named instead, and which websites it used for this town
    instead, sites = who_and_where(town_answers, planner["name"])

    # Was their own website ever used as a source (in ANY answer, any town)?
    domain = website_domain(planner.get("website"))
    own_site_uses = sum(domain in clean_sources(r["sources"]) for r in all_answers) if domain else 0

    # Were they mentioned in answers about OTHER towns?
    mentioned_anywhere = sum(planner["name"] in r["planners_mentioned"].split(" | ")
                             for r in all_answers)

    # The most-mentioned planner from our own list (for an honest comparison of reviews)
    reviews = {p["name"]: p for p in load_planners()}
    leader = max(all_scores, key=lambda s: int(s["score_percent"]))

    return {
        "name": planner["name"], "town": town, "specialty": planner.get("specialty", ""),
        "rating": planner["google_rating"], "reviews": planner["review_count"],
        "mentioned": int(score["times_mentioned"]), "total": total,
        "percent": int(score["score_percent"]),
        "questions": list(dict.fromkeys(r["question"] for r in town_answers)),
        "runs": max((int(r["run_number"]) for r in town_answers), default=0),
        "instead": instead, "sites": sites,
        "domain": domain, "own_site_uses": own_site_uses, "all_answers": len(all_answers),
        "planner_answers": all_answers,
        "mentioned_anywhere": mentioned_anywhere,
        "leader": leader, "leader_reviews": reviews.get(leader["name"], {}).get("review_count", ""),
        "kind": kind,
        "spec": specialty_facts(planner["name"], spec_row, spec_answers),
    }


# How to describe EACH business in the suggested fixes (per business, not per category).
#   words:           what we suggest they call themselves, e.g. "... in Malvern, PA"
#   offers_planning: True only when we've CONFIRMED they do full planning (not just guessed)
# Any business not listed here is described as "wedding planner".
SPECIALTY_WORDS = {
    # Full-service planning confirmed in a King of Prussia business interview
    "Florist & Event Co": {
        "words": "full-service wedding and event planning, design and florals",
        "offers_planning": True,
        # Checked by hand on 2026-11-18 (WeddingWire listing + a local business interview)
        "listing_fixes": [
            ("Move your WeddingWire listing to King of Prussia",
             "Your WeddingWire listing (4.8 stars from 13 reviews) is labeled Ardmore, even though "
             "its address is [street address], King of Prussia, PA. When HubSpot's AI "
             "grader looked you up through Perplexity, it refused to count those 13 reviews "
             "because it couldn't confirm the Ardmore listing was the same business. WeddingWire "
             "also lists you under Ardmore wedding planners, so that planner listing points to "
             "the wrong town. Change the city to King of Prussia so AI tools "
             "can connect those reviews and that planner listing to you. While you're at it, "
             "your own website's contact page lists your ZIP code as 19046 instead of 19406."),
        ],
        # Shown right after the "Add planning ..." fix
        "extra_fixes": [
            ("Show your Best of Philly award",
             "Philadelphia Magazine named you its Best of Philly 2025 wedding florist. Put it on "
             "your homepage and profiles with a link to the Philly Mag page. AI tools trust "
             "well-known local sources like this, and Perplexity already uses phillymag.com "
             "when it answers florist questions about King of Prussia."),
        ],
        "message_extra": (
            "I also found something easy to fix: your WeddingWire listing (4.8 stars from 13 "
            "reviews) is labeled Ardmore, even though its address is in King of Prussia, and WeddingWire is "
            "one of the sites Claude relied on most. When an AI grader looked you up through Perplexity, it wouldn't count those reviews "
            "because it couldn't tell whether the Ardmore listing was you."),
    },
    "Decor Co": {
        "words": "wedding florist and event design",
        "offers_planning": False,
        # Other names that belong to the same business
        "linked_names": ["Old Name Rentals"],
        "linked_names_confirmed": True,
        # It's a NAME CHANGE: Old Name Rentals is the old name
        "old_name": "Old Name Rentals",
        "old_name_variants": ["Old Name Rentals", "Old Name Decor", "Old Name"],
        "old_handle": "@oldnamerentals",
        # Listings that may be teaching AI the wrong thing. The "used in X of Y answers" number
        # is counted from the data each time.
        "bad_listings": [{
            "site": "salon-directory.example",
            "title": "Fix the salon-directory listing that shows your old name",
            "text": ("{site}, a hair-salon directory, was used in {used} of {total} answers and "
                     "lists you with old Old Name Rentals posts. Ask them to update or remove "
                     "the listing, since it may be teaching AI your old name."),
        }],
        "name_evidence": ("Google lists Decor Co as the new name of Old Name "
                          "Rentals, and your Facebook page is titled “Decor Co "
                          "(@oldnamerentals)”."),
        # GROUPED FIXES: 3 numbered fixes with steps underneath (replaces the separate fixes).
        # Words in {curly brackets} are filled in from the data every time, e.g.
        # {old_name_count} = how many answers used the old name. See fix_numbers() below.
        # Steps marked "checked by hand" come from our own checks, not from the scripts.
        "fix_groups": [
            {
                "title": "Fix your name everywhere",
                "intro": ("Claude still credits you under your old name: “{old_name}” (or a "
                          "short form of it) came up in {old_name_count} of {spec2_total} answers. "
                          "{other_tools_names}"),
                "steps": [
                    "Say “formerly {old_name}” on your website and every profile, and "
                    "merge or link old listings and reviews.",
                    "Update the Facebook handle {old_handle}.",
                    # checked by hand
                    "Ask Hollis Mansion to use “Decor Co” in its "
                    "gallery credits. It currently credits your work under several names (VB "
                    "Ellen Design, Old Name Decor, Old Name Rentals).",
                    "Ask {bad_site}, a hair-salon directory, to update or remove its listing. It "
                    "was used in {bad_used} of {spec_total} answers and lists you with old "
                    "{old_name} posts, so it may be teaching AI your old name.",
                    "{other_tools_category} Change your Google Business Profile category to "
                    "match what you do now: event design, décor and florals.",
                ],
            },
            {
                "title": "Lead with your niche and your venue",
                "intro": "Claude already recommends you {every_time}.",
                "steps": [
                    "Put your vintage and antique décor and your Hollis Mansion weddings "
                    "first on your profiles and homepage.",
                    # checked by hand (Perplexity)
                    "Keep adding venue-named portfolio entries. Your portfolio page, which names "
                    "each venue and wedding style, was the top source Perplexity used. Claude "
                    "used your website in only {site_used} of {site_pool} answers.",
                ],
            },
            {
                "title": "Strengthen your listings and reviews",
                "intro": "",
                "steps": [
                    "Get {reviews_needed} more Google reviews. You have {reviews} (rated "
                    "{rating}); at 10 you’d meet our “hidden gem” bar. Ask couples "
                    "to mention their wedding and {town} in the review.",
                    "Complete your profiles on {top_sites}, saying “{what} in {town}, "
                    "PA”, with photos and prices if you’re comfortable sharing them.",
                ],
            },
        ],
        "fix_groups_lead": "Start with Fix 1: it has the biggest impact.",
        # "In short": 3 short sentences (Claude's old-name use, other tools' #1s, venue credits)
        "summary_style": "short",
        "summary_extra": ("Hollis Mansion’s gallery credits you under mixed names (Decor Co "
                          "Design, Old Name Decor, Old Name Rentals)."),
        # Message style: good news first, then one risk, then the offer (under 120 words)
        "message_style": "protect_top_spot",
        # The risk sentence's hand-checked part
        "message_risk_extra": "Hollis Mansion’s gallery credits you under three different names",
    },
}

# How each second-test topic reads in a sentence ("recommended ... for vintage wedding décor")
TOPIC_TEXT = {
    "vintage décor": "for vintage wedding décor",
    "Hollis Mansion venue": "for weddings at Hollis Mansion",
}


def old_name_answers(f, answers):
    """How many of these answers used the business's OLD name (any variant)."""
    from check_specialty import other_names_in
    variants = settings(f).get("old_name_variants", [])
    return sum(any(v in other_names_in(a["answer"], f["name"]) for v in variants)
               for a in answers)


def own_answers_2(f):
    return [a for a in f.get("spec2_answers", []) if a["name"] == f["name"]]


def settings(f):
    return SPECIALTY_WORDS.get(f["name"], {})


def name_story(f):
    """Second test, in numbers: where AI recommends them, and under which names.
    Returns None if there's no second test for this business."""
    t = f.get("spec2")
    if not t:
        return None
    asks = [q for q in t["questions"] if q["topic"] != "brand"]
    brand = next((q for q in t["questions"] if q["topic"] == "brand"), None)
    total = sum(q["asked"] for q in t["questions"])
    top_alias = t["other_names"][0] if t["other_names"] else None
    return {
        "brand": brand, "asks": asks, "total": total, "top_alias": top_alias,
        "answers_with_other_names": t["answers_with_other_names"],
        # every time = mentioned under some name in every answer
        "every_time": [q for q in asks if q["any"] == q["asked"]],
        # official name used less often than other names
        "weak": [q for q in asks if q["hits"] < q["any"]],
    }


def topic_text(q):
    return TOPIC_TEXT.get(q["topic"], f"for {q['topic']}")


def recommended_part(q):
    """'for vintage wedding décor (5 of 5 answers)' or 'at Hollis Mansion (5 of 5 under any name)'"""
    if q["hits"] == q["any"]:
        return f"{topic_text(q)} ({q['any']} of {q['asked']} answers)"
    return f"{topic_text(q)} ({q['any']} of {q['asked']} under any name)"


def join_and(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def short_summary(f):
    """3 short sentences: (1) Claude often uses the old name, (2) which other tools ranked them
    #1 for which topic, (3) a hand-checked extra (e.g. venue credits)."""
    cfg, n = settings(f), name_story(f)
    k = old_name_answers(f, own_answers_2(f))
    sentences = [f"Claude often credits you under your old name: “{cfg['old_name']}” or a "
                 f"short form of it came up in {k} of {n['total']} of its answers."]
    topics = list(dict.fromkeys(r["topic"] for r in other_rows(f)
                                if r["rank"] == "1" and r["topic"] in OTHER_TOPIC_TEXT))
    by_topic = sorted(((t, other_tools_number_one(f, t)) for t in topics), key=lambda x: -len(x[1]))
    if by_topic:
        t, tools = by_topic[0]
        s = f"{join_and(tools)} picked you #1 for {t}"
        rest = [f"{join_and(tl)} also for {tp}" for tp, tl in by_topic[1:]]
        if rest:
            s += ", and " + join_and(rest)
        sentences.append(s + ".")
    if cfg.get("summary_extra"):
        sentences.append(cfg["summary_extra"])
    return " ".join(sentences)


def summary_text(f):
    """Opening summary for businesses with a second test (uses only measured numbers)."""
    n = name_story(f)
    if not n:
        return ""
    cfg = settings(f)
    if cfg.get("summary_style") == "short" and cfg.get("old_name"):
        return short_summary(f)
    b = n["brand"]
    knows = ("Claude knows you" if b and b["hits"] == b["asked"]
             else f"Claude knew you in {b['hits']} of {b['asked']} answers" if b else "Claude knows you")
    text = knows
    cfg = settings(f)
    if cfg.get("old_name") and cfg.get("linked_names_confirmed"):
        # Confirmed name change: explain that AI often credits them under the OLD name
        k = old_name_answers(f, own_answers_2(f))
        text += (f", but often credits you under your old name, {cfg['old_name']}: "
                 f"it came up in {k} of {n['total']} answers")
    elif n["top_alias"]:
        alias, count = n["top_alias"]
        text += f", but often under other names ({alias} in {count} of {n['total']} answers)"
    text += "."
    rec = [q for q in n["asks"] if q["any"] > 0]
    if rec:
        text += f" Claude recommends you {join_and([recommended_part(q) for q in rec])}"
        if n["weak"]:
            weak = [f"{topic_text(q)} only {q['hits']} of {q['asked']} answers" for q in n["weak"]]
            renamed = cfg.get("old_name") and cfg.get("linked_names_confirmed")
            text += f", but {join_and(weak)} used your {'new' if renamed else 'official'} name"
        text += "."
    # Other AI tools (hand checks), clearly separated from the Claude numbers
    others = other_tools_summary(f)
    if others:
        text += " " + others
    return text


def what_you_do(f):
    return SPECIALTY_WORDS.get(f["name"], {}).get("words", "wedding planner")


def offers_planning(f):
    return SPECIALTY_WORDS.get(f["name"], {}).get("offers_planning", False)


def is_florist(f):
    return bool(f["spec"]) and "florist" in f["spec"]["label"]


def second_test_fixes(f):
    """Fixes based on the second test (names + niche). Empty if there's no second test."""
    n, cfg = name_story(f), settings(f)
    if not n:
        return []
    fixes = []
    linked = cfg.get("linked_names", [])
    if cfg.get("old_name") and cfg.get("linked_names_confirmed"):
        k = old_name_answers(f, own_answers_2(f))
        handle = cfg.get("old_handle")
        fixes.append((
            "Connect your old and new names",
            f"Claude still credits you under your old name: \"{cfg['old_name']}\" (or a short form "
            f"of it) came up in {k} of {n['total']} answers. Say \"formerly {cfg['old_name']}\" on your "
            f"website and every profile"
            + (f", update the Facebook handle {handle}" if handle else "")
            + ", and merge or link old listings and reviews, so AI credits one business."))
        # Right after the name fix: specific listings that still show the old name
        s = f["spec"]
        pool = (s["answers"] if s else []) + own_answers_2(f)
        for bad in cfg.get("bad_listings", []):
            used = sum(bad["site"] in clean_sources(a["sources"]) for a in pool)
            if used:
                fixes.append((bad["title"], bad["text"].format(site=bad["site"], used=used,
                                                               total=len(pool))))
        # Name fixes from things checked by hand (e.g. how a venue credits them)
        fixes.extend(cfg.get("manual_fixes", []))
    elif n["top_alias"] and linked:
        alias, count = n["top_alias"]
        fixes.append((
            "Use one name everywhere",
            f"Claude used other names for you in {n['answers_with_other_names']} of {n['total']} "
            f"answers, most often \"{alias}\" ({count} of {n['total']}). Make sure your profiles, "
            f"website and Google clearly connect {f['name']} and {join_and(linked)}, so AI "
            f"credits one business."))
    if n["every_time"] and cfg.get("niche_title"):
        fixes.append((
            cfg["niche_title"],
            f"Claude already recommends you there: "
            f"{join_and([recommended_part(q) for q in n['every_time']])}. "
            + cfg.get("niche_action", "")))
    return fixes


# Sources that are clearly NOT about wedding vendors. They stay in the data and in the
# report's websites lists (labeled), but are never used in the suggested fixes.
UNRELATED_SITES = {
    "job posting": ["icims.com", "greenhouse.io", "lever.co", "myworkdayjobs.com",
                    "workday.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
                    "monster.com", "simplyhired.com", "smartrecruiters.com", "jobvite.com",
                    "bamboohr.com", "applytojob.com", "careerbuilder.com"],
}


def unrelated_kind(site):
    """'c-5311-...-www-cortevents-com.i.icims.com' -> 'job posting'; normal sites -> ''"""
    for kind, domains in UNRELATED_SITES.items():
        if any(site == d or site.endswith("." + d) for d in domains):
            return kind
    return ""


def related_only(sites):
    """Drop unrelated pages from a [(site, count), ...] list (used for the fixes)."""
    return [(site, n) for site, n in sites if not unrelated_kind(site)]


def specialty_sources(f):
    """Websites Claude used across this business's specialty + second-test answers
    (their own website left out). Returns (top sites, number of answers, topic names)."""
    s = f["spec"]
    pool = (s["answers"] if s else []) + own_answers_2(f)
    counts = Counter(site for a in pool for site in clean_sources(a["sources"])
                     if site != f["domain"])
    topics = [t["topic"] for t in s["topics"]] if s else []
    topics += [q["topic"] for q in f["spec2"]["questions"]] if f.get("spec2") else []
    return counts.most_common(TOP_N), len(pool), topics


def fix_numbers(f):
    """The measured numbers that grouped-fix wording can use, e.g. {old_name_count}."""
    cfg, s = settings(f), f["spec"]
    spec_pool = (s["answers"] if s else []) + own_answers_2(f)
    n = name_story(f)
    spec_sites, spec_total, _ = specialty_sources(f)
    top3 = related_only(spec_sites)[:3]
    site_pool = f["planner_answers"] + spec_pool
    bad = (cfg.get("bad_listings") or [{}])[0]
    return {
        "name": f["name"], "town": f["town"], "what": what_you_do(f),
        "rating": f["rating"], "reviews": f["reviews"],
        "reviews_needed": max(0, 10 - int(float(f["reviews"]))),
        "old_name": cfg.get("old_name", ""), "old_handle": cfg.get("old_handle", ""),
        "old_name_count": old_name_answers(f, own_answers_2(f)),
        "spec2_total": n["total"] if n else 0,
        "spec_total": len(spec_pool),
        "bad_site": bad.get("site", ""),
        "bad_used": sum(bad.get("site", "-") in clean_sources(a["sources"]) for a in spec_pool),
        "every_time": join_and([recommended_part(q) for q in n["every_time"]]) if n else "",
        "site_used": sum(f["domain"] in clean_sources(a["sources"]) for a in site_pool)
                     if f["domain"] else 0,
        "site_pool": len(site_pool),
        "top_sites": join_and([f"{site} ({c} of {spec_total} answers)" for site, c in top3]),
        # From the hand checks of other AI tools (other_ai_checks.csv)
        "other_tools_names": other_tools_names(f),
        "other_tools_category": other_tools_category(f),
    }


def grouped_fixes(f):
    """3 numbered fixes with steps underneath, for businesses that have "fix_groups" in their
    settings. Returns None for everyone else (they get the normal list of fixes)."""
    groups = settings(f).get("fix_groups")
    if not groups:
        return None
    nums = fix_numbers(f)
    return [{"title": g["title"].format(**nums),
             "intro": g.get("intro", "").format(**nums),
             "steps": [step.format(**nums) for step in g["steps"]]} for g in groups]


def suggested_fixes(f):
    """2-4 honest suggestions, each based on something we actually measured.
    Listed in order of importance. Usually the first 3 are used; businesses with a
    second test get up to 5 (name + niche fixes first, then reviews, directories, website)."""
    front = second_test_fixes(f)
    # Fixes checked by hand (e.g. a listing in the wrong town) come first
    fixes = list(settings(f).get("listing_fixes", []))

    # Near hidden gem: the clearest, most measurable fix is a few more reviews
    if f["kind"] == "near hidden gem":
        needed = 10 - int(float(f["reviews"]))
        fixes.append((
            f"Get {needed} more Google review{'s' if needed != 1 else ''}",
            f"You have a {f['rating']} rating from {f['reviews']} reviews. With {needed} more "
            f"(10 in total) you'd meet our \"hidden gem\" bar: a great rating backed by enough "
            f"reviews to be convincing. Ask recent couples, and ask them to mention their wedding "
            f"and {f['town']} in the review."))

    # The words we suggest they use to describe themselves, e.g.
    # "wedding florist and event design in Malvern, PA" instead of "wedding planner in Malvern, PA"
    what = what_you_do(f)
    s = f["spec"]

    # Step 7: AI knows them as a florist, and we've confirmed they also plan events
    topic = {t["topic"]: t for t in s["topics"]} if s else {}
    if (s and s["percent"] > f["percent"] and is_florist(f) and offers_planning(f)
            and "florist" in topic and "event design" in topic):
        fl, de = topic["florist"], topic["event design"]
        florist_part = (f"all {fl['total']} florist answers" if fl["mentioned"] == fl["total"]
                        else f"{fl['mentioned']} of {fl['total']} florist answers")
        fixes.append((
            "Add planning to your florist reputation",
            f"Claude mentioned you in {florist_part}, but only {de['mentioned']} of {de['total']} "
            f"event design answers and {f['mentioned']} of {f['total']} planner answers. "
            f"Say clearly on your profiles and homepage that you design and plan events, "
            f"not only flowers."
            + (" " + other_tools_mentions(f, f"{f['town']} wedding planners")
               if other_tools_mentions(f, f"{f['town']} wedding planners") else "")))
    # Step 7: AI already knows them for their specialty - build on it
    elif s and s["percent"] > f["percent"] and what != "wedding planner":
        fixes.append((
            f"Build on your {s['label']} reputation",
            f"Claude already mentions you for {s['label']} ({s['mentioned']} of {s['total']} "
            f"answers), but not for planner questions ({f['mentioned']} of {f['total']}). "
            f"Use the same words, \"{what} in {f['town']}, PA\", on every profile and on your "
            f"website, so AI tools keep connecting you to the questions couples ask."))
    elif s and s["percent"] > f["percent"]:
        fixes.append((
            f"Connect your {s['label']} reputation to planning",
            f"Claude mentioned you in {s['mentioned']} of {s['total']} answers to {s['label']} "
            f"questions, but in {f['mentioned']} of {f['total']} answers to wedding planner "
            f"questions. If you offer planning, say \"wedding planner\" or \"event planning\" "
            f"clearly on the same profiles and pages where you're known for {s['label']}."))

    fixes.extend(settings(f).get("extra_fixes", []))

    # Businesses with a specialty test: the websites from ALL their specialty (+ second-test)
    # answers - the same list as the "Websites Claude used to decide" section above the fixes.
    # Everyone else: the websites from the planner questions.
    spec_sites, spec_total, spec_topics = specialty_sources(f)
    if s and spec_sites:
        top3, total = related_only(spec_sites)[:3], spec_total
        about = f"the {spec_total} {join_and(spec_topics)} answers we collected about you"
    else:
        top3, total, about = related_only(f["sites"])[:3], f["total"], f"questions about {f['town']}"
    if top3:
        listed = ", ".join(f"{site} ({n} of {total} answers)" for site, n in top3)
        fixes.append((
            "Be complete on the sites Claude reads most",
            f"For {about}, Claude's answers used {listed}. "
            f"Make sure you have a complete, up-to-date profile on each one, that clearly says "
            f"\"{what} in {f['town']}, PA\", with photos and prices if you're comfortable "
            f"sharing them."))

    # Only if we have their website on file (if the website column is empty, skip this fix).
    # Count over ALL answers we have for this business: planner + specialty + second test.
    if f["domain"]:
        pool = (f["planner_answers"] + (s["answers"] if s else []) + own_answers_2(f))
        used = [a for a in pool if f["domain"] in clean_sources(a["sources"])]
        how = (f"Say plainly on your homepage what you do and where, e.g. "
               f"\"{what[0].upper() + what[1:]} in {f['town']}, PA\", and list the towns and "
               f"venues you serve, so AI tools can connect you to these questions.")
        if settings(f).get("website_fix_extra"):
            how += " " + settings(f)["website_fix_extra"]
        else:
            # Good news from hand checks: other AI tools that DID cite the website
            cited_by = [r for r in other_rows(f) if r.get("official_site_used") == "YES"]
            if cited_by:
                bits = list(dict.fromkeys(f"{r['tool']} (for {r['topic']})" for r in cited_by))
                how += (" Good sign: in our quick checks, " + join_and(bits)
                        + " did cite your website, so it can be found; it just needs to say "
                          "more about what you do.")
        # ("Claude answers", because we now also have hand checks of other AI tools)
        if not used:
            fixes.append(("Make your own website easy for AI to understand",
                          f"Your website ({f['domain']}) wasn't used as a source in any of the "
                          f"{len(pool)} Claude answers we collected. " + how))
        elif len(used) < len(pool) / 2:
            only_brand = all(a.get("topic") == "brand" for a in used)
            fixes.append((
                "Make your own website easy for AI to understand",
                f"Your website ({f['domain']}) was used as a source in only {len(used)} of the "
                f"{len(pool)} Claude answers we collected"
                + (", and only when we asked about you by name" if only_brand else "")
                + ". " + how))

    leader = f["leader"]
    if leader["name"] != f["name"] and f["leader_reviews"] and f["kind"] != "near hidden gem":
        fixes.append((
            "Keep collecting reviews",
            f"You have {f['reviews']} Google reviews (rated {f['rating']}). In this test, the planner "
            f"from our list that Claude mentioned most, {leader['name']}, has {f['leader_reviews']} "
            f"Google reviews and was mentioned in {leader['times_mentioned']} of "
            f"{leader['total_asked']} answers for {leader['town']}. "
            f"We can't prove reviews are the reason, but more recent reviews that mention your "
            f"weddings and {f['town']} give AI tools more to go on."))
    # Hand-checked fixes add to the list instead of pushing measured ones out
    extra = len(settings(f).get("listing_fixes", [])) + len(settings(f).get("extra_fixes", []))
    return (front + fixes)[:7 if front else min(3 + extra, 5)]


# ---------- 3. Writing the report (HTML) ----------

CSS = """
:root { --bg:#f6f5f2; --card:#ffffff; --text:#1f2328; --muted:#5f6670; --line:#e4e2dc;
        --accent:#7a4e9e; --bar:#c9b3dc; --low:#b3261e; --lowbg:#fdecea; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16151a; --card:#1f1e24; --text:#ecebf0; --muted:#a6a3ad; --line:#33313a;
          --accent:#c4a3e0; --bar:#5d4775; --low:#ff8a80; --lowbg:#3a1f1f; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:16px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width:760px; margin:0 auto; padding:32px 16px 48px; }
header p { color:var(--muted); margin:4px 0 0; }
h1 { font-size:28px; margin:0; line-height:1.2; }
h2 { font-size:19px; margin:0 0 12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:20px; margin-top:20px; }
.score { display:flex; gap:20px; align-items:center; flex-wrap:wrap; }
.big { font-size:44px; font-weight:700; color:var(--low); background:var(--lowbg);
       border-radius:12px; padding:8px 18px; line-height:1.1; }
.score p { margin:0; flex:1; min-width:220px; }
.muted { color:var(--muted); font-size:14px; }
ul.bars { list-style:none; padding:0; margin:0; }
ul.bars li { display:grid; grid-template-columns:minmax(0,1fr) 110px 44px; gap:10px;
             align-items:center; padding:6px 0; border-bottom:1px solid var(--line); }
ul.bars li:last-child { border-bottom:0; }
.name { overflow-wrap:anywhere; }
.track { background:var(--line); border-radius:4px; height:8px; }
.fill { background:var(--bar); border-radius:4px; height:8px; }
.count { text-align:right; font-variant-numeric:tabular-nums; color:var(--muted); font-size:14px; }
ol.fixes { padding-left:22px; margin:0; }
ol.fixes li { margin-bottom:14px; }
ol.fixes li:last-child { margin-bottom:0; }
ol.fixes strong { display:block; }
ol.fixes > li > strong { font-size:17px; }
ul.steps { margin:8px 0 0; padding-left:20px; }
ul.steps li { margin-bottom:6px; }
footer { margin-top:24px; }
.badge { display:inline-block; margin-top:10px; padding:3px 10px; border-radius:999px;
         font-size:13px; font-weight:600; background:var(--bar); color:var(--text); }
.compare { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px;
           margin-bottom:14px; }
.stat { border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.stat .num { font-size:30px; font-weight:700; line-height:1.1; white-space:nowrap; }
.stat .num.low { color:var(--low); }
.stat .num.good { color:var(--accent); }
.stat .what { font-size:14px; color:var(--muted); }
.lead { margin:0 0 14px; font-weight:600; }
.summary .lead { margin:0; font-size:17px; }
.note { margin:12px 0 0; padding:10px 12px; border-left:3px solid var(--accent);
        background:var(--bg); border-radius:6px; font-size:14px; }
h3 { font-size:15px; margin:18px 0 8px; }
@media (max-width:480px) { ul.bars li { grid-template-columns:minmax(0,1fr) 60px 40px; }
                           .compare { grid-template-columns:1fr; } }
"""


def bar_list(items, total):
    rows = []
    for label, n in items:
        width = round(100 * n / total) if total else 0
        rows.append(
            f'<li><span class="name">{html.escape(label)}</span>'
            f'<span class="track"><span class="fill" style="display:block;width:{width}%"></span></span>'
            f'<span class="count">{n}/{total}</span></li>')
    return '<ul class="bars">' + "".join(rows) + "</ul>"


def compare_sentence(f):
    """Step 7: one plain sentence comparing the specialty score with the planner score."""
    s = f["spec"]
    spec, plan = f"{s['label']} ({s['percent']}%)", f"a wedding planner ({f['percent']}%)"
    # More than one topic, and at least one hit: list each topic so it matches the boxes
    if len(s["topics"]) > 1 and s["mentioned"] > 0:
        parts = [f"{t['percent']}% of {t['topic']} answers" for t in s["topics"]]
        parts.append(f"{f['percent']}% of wedding planner answers")
        return f"Claude mentioned you in {', '.join(parts[:-1])} and {parts[-1]}."
    if s["percent"] > f["percent"]:
        return f"Claude knows you better for {spec} than as {plan}."
    if s["percent"] < f["percent"]:
        return f"Claude mentions you more as {plan} than for {spec}."
    if s["percent"] == 0:
        return f"Claude didn't mention you for {s['label']} questions either (0 of {s['total']} answers)."
    return f"Claude mentions you about equally for {spec} and as {plan}."


def specialty_card(f):
    s = f["spec"]
    if not s:
        return ""
    e = html.escape
    qs = "".join(f"<li>&ldquo;{e(q)}&rdquo;</li>" for q in s["questions"])

    def stat(percent, mentioned, total, what):
        cls = "good" if percent >= 30 else "low"
        return (f'<div class="stat"><div class="num {cls}">{percent}%</div>'
                f'<div class="what">{e(what)}<br>{mentioned} of {total} answers</div></div>')

    instead = ""
    if s["instead"]:
        instead = (f"<h3>Other businesses Claude named for these questions</h3>"
                   f"{bar_list(s['instead'], s['total'])}")
    return f"""
  <section class="card">
    <h2>Planner questions vs. your specialty</h2>
    <div class="compare">
      {stat(f['percent'], f['mentioned'], f['total'], 'Wedding planner questions')}
      {"".join(stat(t['percent'], t['mentioned'], t['total'], first_upper(t['topic']) + ' questions')
               for t in s['topics'])}
    </div>
    <p class="lead">{e(compare_sentence(f))}</p>
    <p class="muted">Because your business focuses on {e(s['label'])}, we also asked these questions
    ({s['runs']} times each, on {e(s['day'])}). This is a separate score; it doesn't change your planner score.</p>
    <ul>{qs}</ul>
    {instead}
  </section>
"""


def second_test_facts(name, score_rows, answers):
    """Second specialty test (e.g. Decor Co's brand / vintage decor / venue questions):
    one entry per question. Returns None if this business wasn't in that test."""
    mine = [r for r in score_rows if r["name"] == name]
    if not mine:
        return None
    questions = []
    for r in mine:
        rs = [a for a in answers if a["name"] == name and a["question"] == r["question"]]
        instead = who_and_where(rs, name, top=5)[0] if r["topic"] != "brand" else []
        any_name = r.get("mentioned_any_name", "")
        questions.append({**r, "hits": int(r["hits"]), "asked": int(r["asked"]),
                          "score_percent": int(r["score_percent"]), "instead": instead,
                          # mentioned under ANY of their names (falls back to official name)
                          "any": int(any_name) if str(any_name).strip() else int(r["hits"])})
    from check_specialty import other_names_in   # re-check the saved answer text
    mine_answers = [a for a in answers if a["name"] == name]
    names_per_answer = [other_names_in(a["answer"], name) for a in mine_answers]
    other_names = Counter(n for names in names_per_answer for n in names)
    day = next((a["date"] for a in mine_answers), "")
    return {"questions": questions, "other_names": other_names.most_common(), "day": day,
            "answers_with_other_names": sum(bool(names) for names in names_per_answer)}


def confirm_note(f):
    """'We believe Old Name Rentals is connected to your business; please confirm.'"""
    cfg = settings(f)
    linked = cfg.get("linked_names", [])
    if not linked:
        return ""
    if cfg.get("linked_names_confirmed"):
        # Confirmed: show the evidence instead of "please confirm"
        if cfg.get("name_evidence"):
            return (f'<p class="note"><strong>Name change confirmed:</strong> '
                    f'{html.escape(cfg["name_evidence"])}</p>')
        return ""
    verb = "is" if len(linked) == 1 else "are"
    return (f'<p class="note">We believe {html.escape(join_and(linked))} {verb} connected to '
            f'your business; please confirm.</p>')


def formerly_html(f):
    """' · formerly Old Name Rentals' in the report header (confirmed name changes only)"""
    cfg = settings(f)
    if cfg.get("old_name") and cfg.get("linked_names_confirmed"):
        return f" &middot; formerly {html.escape(cfg['old_name'])}"
    return ""


def load_other_ai_checks(path="other_ai_checks.csv"):
    """Hand checks of other AI tools (e.g. Perplexity), typed into other_ai_checks.csv."""
    try:
        return read_csv(path)
    except FileNotFoundError:
        return []


def other_rows(f):
    # Skip whole-brand grader rows (e.g. HubSpot): they have scores, not per-question answers.
    return [r for r in load_other_ai_checks()
            if r["business"] == f["name"] and not r.get("method", "").startswith("HubSpot")]


def other_tools_number_one(f, topic):
    """Other AI tools that ranked this business #1 for a topic (hand checks)."""
    return list(dict.fromkeys(r["tool"] for r in other_rows(f)
                              if r.get("topic") == topic and r["rank"] == "1"))


def other_tools_summary(f):
    """'In one-try checks, Google AI Mode, ChatGPT and Perplexity all recommended you #1 for
    Hollis Mansion, and Google AI Mode and Perplexity also #1 for vintage décor. Google AI Mode
    and ChatGPT used your new name.'  Built only from other_ai_checks.csv."""
    rows = other_rows(f)
    topics = list(dict.fromkeys(r.get("topic", "") for r in rows if r["rank"] == "1"))
    by_topic = sorted(((t, other_tools_number_one(f, t)) for t in topics),
                      key=lambda x: -len(x[1]))
    if not by_topic:
        return ""
    t, tools = by_topic[0]
    text = (f"In one-try checks, {join_and(tools)} {'all ' if len(tools) > 2 else ''}"
            f"recommended you #1 for {t}")
    rest = [f"{join_and(tools)} also #1 for {t}" for t, tools in by_topic[1:]]
    if rest:
        text += (", and " if len(rest) == 1 else ", ") + join_and(rest)
    text += "."
    # Which name each tool used: "Google AI Mode and ChatGPT used your new name; Perplexity
    # did too, except for Hollis Mansion (“Decor Co Design / Old Name Decor”)."
    all_new, mixed = [], []
    for tool, names in names_by_tool(f).items():
        other = [(n, ts) for n, ts in names.items() if not n.startswith(f["name"])]
        if not other:
            all_new.append(tool)
        elif len(other) < len(names):
            mixed.append(f"{tool} did too, except for "
                         + join_and([f"{join_and(ts)} (“{n}”)" for n, ts in other]))
    if all_new:
        text += f" {join_and(all_new)} used your new name"
        text += ("; " + "; ".join(mixed)) if mixed else ""
        text += "."
    return text


def names_by_tool(f):
    """{tool: {name used: [topics]}} from the hand checks (brand questions left out, because
    the name is already in the question)."""
    out = {}
    for r in other_rows(f):
        if r.get("name_used") and r.get("topic") != "brand":
            topics = out.setdefault(r["tool"], {}).setdefault(r["name_used"], [])
            if r["topic"] not in topics:
                topics.append(r["topic"])
    return out


def other_tools_names(f):
    """'In one-try checks, Google AI Mode called you “…” (for vintage décor), ChatGPT “…”
    (for Hollis Mansion) and Perplexity “…” (for Hollis Mansion).'  Plain official-name uses are
    left out: this sentence is about the OTHER names tools use."""
    named = [(tool, n, ts) for tool, names in names_by_tool(f).items()
             for n, ts in names.items() if n != f["name"]]
    if not named:
        return ""
    parts = [(f"{tool} called you" if i == 0 else tool) + f" “{n}” (for {join_and(ts)})"
             for i, (tool, n, ts) in enumerate(named)]
    return f"In one-try checks, {join_and(parts)}."


def other_tools_category(f):
    """'Google AI Mode and ChatGPT show your business category as “Wedding venue”.'"""
    shown = {}
    for r in other_rows(f):
        if r.get("category_shown"):
            shown.setdefault(r["category_shown"], [])
            if r["tool"] not in shown[r["category_shown"]]:
                shown[r["category_shown"]].append(r["tool"])
    return " ".join(f"{join_and(tools)} show{'s' if len(tools) == 1 else ''} your business "
                    f"category as “{cat}”." for cat, tools in shown.items())


def other_tools_mentions(f, topic):
    """'In one-try checks for King of Prussia wedding planners, ChatGPT listed you #4, as “best
    for flowers and décor”; Google AI Mode and Perplexity didn't mention you.'"""
    rows = [r for r in other_rows(f) if r.get("topic") == topic]
    if not rows:
        return ""
    yes = [f"{r['tool']} listed you #{r['rank']}"
           + (f", as “{r['described_as']}”" if r.get("described_as") else "")
           for r in rows if r["mentioned"].upper() == "YES"]
    # Each tool once (a tool can have several tries for the same topic)
    said_yes = {r["tool"] for r in rows if r["mentioned"].upper() == "YES"}
    no = list(dict.fromkeys(r["tool"] for r in rows
                            if r["mentioned"].upper() != "YES" and r["tool"] not in said_yes))
    parts = yes + ([f"{join_and(no)} didn't mention you"] if no else [])
    return f"In quick checks for {topic}, " + "; ".join(parts) + "."


# Notes that are about a whole tool, shown once under it (all other notes go next to their line)
TOOL_NOTES = {"Google results may be personalized"}


def combined_result(f, rs):
    """All tries for one tool + business + topic in one line, e.g.
    '#1 in 2 of 2 tries · new name in 0 of 2 (1 not recorded), also “Decor Co Design / …”'"""
    n = sum(int(r["tries"] or 1) for r in rs)
    tries = f"{n} {'try' if n == 1 else 'tries'}"
    yes = [r for r in rs if r["mentioned"].upper() == "YES"]

    if rs[0].get("topic") == "brand":
        # Name is in the question, so the check is "does it know you"
        parts = [f"knows you in {len(yes)} of {tries}"]
    elif not yes:
        return f"did not mention you in {tries}"
    else:
        ranks = sorted({r["rank"] for r in yes if r["rank"]}, key=int)
        if len(yes) == n and len(ranks) == 1:
            parts = [f"#{ranks[0]} in {len(yes)} of {tries}"]
        else:
            parts = [f"mentioned in {len(yes)} of {tries}"
                     + (f" (ranked {', '.join('#' + x for x in ranks)})" if ranks else "")]
        # Which name it used: new (official) name vs other names; blank = not recorded
        recorded = [r for r in yes if r.get("name_used")]
        new = [r for r in recorded if r["name_used"].startswith(f["name"])]
        not_recorded = len(yes) - len(recorded)
        renamed = settings(f).get("old_name") and settings(f).get("linked_names_confirmed")
        # Only worth showing when names vary (a renamed business, or another name was used)
        if recorded and (renamed or len(new) < len(recorded)):
            text = f"{'new' if renamed else 'official'} name in {len(new)} of {len(yes)}"
            if not_recorded:
                text += f" ({not_recorded} not recorded)"
            # List each name it used and how often, e.g. "“A” once, “B” once" (plain, no also/as)
            counts = {}
            for r in recorded:
                counts[r["name_used"]] = counts.get(r["name_used"], 0) + 1
            if any(nm != f["name"] for nm in counts):
                words = {1: "once", 2: "twice"}
                text += " (names used: " + ", ".join(
                    f"“{nm}” {words.get(c, str(c) + ' times')}" for nm, c in counts.items()) + ")"
            parts.append(text)
        described = list(dict.fromkeys(r["described_as"] for r in yes if r.get("described_as")))
        if described:
            parts.append("described as " + " and ".join(f"“{d}”" for d in described))
    cited = sum(r.get("official_site_used") == "YES" for r in rs)
    if cited:
        parts.append(f"cited your website in {cited} of {n}")
    return " · ".join(parts)


def other_ai_card(f):
    rows = other_rows(f)
    if not rows:
        return ""
    e = html.escape
    parts = []
    for tool in dict.fromkeys(r["tool"] for r in rows):
        mine = [r for r in rows if r["tool"] == tool]
        # ONE line per topic, combining all tries for that tool + business + topic
        items = []
        for topic in dict.fromkeys(r["topic"] for r in mine):
            rs = [r for r in mine if r["topic"] == topic]
            # Notes about this line (e.g. "map list: #2") go next to it
            line_notes = [n for n in dict.fromkeys(n.strip() for r in rs
                                                   for n in r.get("notes", "").split(";"))
                          if n and n not in TOOL_NOTES]
            muted = join_and(sorted({r['date'] for r in rs})) + "".join(f"; {n}" for n in line_notes)
            items.append(f"<li><strong>{e(first_upper(topic))}:</strong> "
                         f"{e(combined_result(f, rs))} "
                         f"<span class=\"muted\">({e(muted)})</span></li>")
        # One entry per website (the first word is the site, e.g. "decor-co.example (…)")
        sources, seen_sites = [], set()
        for r in mine:
            for s in r["sources"].split(" | "):
                site = s.strip().split(" ")[0]
                if site and site not in seen_sites:
                    seen_sites.add(site)
                    sources.append(s.strip())
        extra = []
        if sources:
            # Pasted answers can list 10-25 sources each: show the first few
            shown = sources[:6]
            more = f" and {len(sources) - len(shown)} more" if len(sources) > len(shown) else ""
            extra.append(f"Sources it cited: {e(', '.join(shown))}{more}.")
        cats = list(dict.fromkeys(r["category_shown"] for r in mine if r.get("category_shown")))
        if cats:
            extra.append(f"Business category it shows for you: {e(join_and(cats))}.")
        # Notes about the whole tool (e.g. "Google results may be personalized") go once, below
        notes = [n for n in dict.fromkeys(n.strip() for r in mine
                                          for n in r.get("notes", "").split(";"))
                 if n in TOOL_NOTES]
        extra += [e(first_upper(n)) + "." for n in notes]
        extra_html = "".join(f"<p class=\"muted\">{x}</p>" for x in extra)
        parts.append(f"<h3>{e(tool)}</h3><ul>{''.join(items)}</ul>{extra_html}")
    return f"""
  <section class="card">
    <h2>Quick check on other AI tools</h2>
    <p class="muted">Checked by hand (typed in or pasted from each tool), with only one or two tries per question, so treat this as a spot check, not a score.</p>
    {''.join(parts)}
  </section>
"""


def summary_card(f):
    text = summary_text(f)
    if not text:
        return ""
    return f"""
  <section class="card summary">
    <h2>In short</h2>
    <p class="lead">{html.escape(text)}</p>
    {confirm_note(f)}
  </section>
"""


def second_test_card(f):
    t = f.get("spec2")
    if not t:
        return ""
    e = html.escape
    boxes, details = [], []
    for q in t["questions"]:
        if q["topic"] == "brand":
            count = q["hits"]
            what = "Knows your business"
            yes, partly, no = (q.get("knows_clearly_partly_no") or "0 / 0 / 0").split(" / ")
            extra = (f"Clearly: {yes} &middot; Says info is thin: {partly}"
                     f" &middot; Doesn't know you: {no}")
        else:
            # Main number = under ANY of their names; official name shown underneath
            count = q["any"]
            what = "Recommends you, under any name"
            extra = f"{q['hits']} of {q['asked']} by your official name"
        cls = "good" if count / q["asked"] >= 0.3 else "low"
        boxes.append(
            f'<div class="stat"><div class="num {cls}">{count} of {q["asked"]}</div>'
            f'<div class="what"><strong>{e(first_upper(q["topic"]))}</strong>: {what}<br>'
            f'{extra}</div></div>')
        if q["instead"]:
            details.append(f"<h3>Who Claude named for &ldquo;{e(q['question'])}&rdquo;</h3>"
                           f"{bar_list(q['instead'], q['asked'])}")
    qs = "".join(f"<li><strong>{e(first_upper(q['topic']))}:</strong> &ldquo;{e(q['question'])}&rdquo;</li>"
                 for q in t["questions"])
    total = sum(q["asked"] for q in t["questions"])
    if t["other_names"]:
        names = ", ".join(f"{e(n)} (in {c} of {total} answers)" for n, c in t["other_names"])
        names_html = f"<p><strong>Other names Claude used for you:</strong> {names}</p>"
    else:
        names_html = "<p><strong>Other names Claude used for you:</strong> none found.</p>"
    return f"""
  <section class="card">
    <h2>Second test: does Claude know your brand, style and venues?</h2>
    <p class="muted">On {e(t['day'])} we asked three more questions, {t['questions'][0]['asked']} times each.
    Each one has its own score. For the brand question we checked whether Claude actually knew
    your business (not just repeated the name from the question).</p>
    <div class="compare">{''.join(boxes)}</div>
    {names_html}
    <ul>{qs}</ul>
    {''.join(details)}
  </section>
"""


def report_html(f, day):
    e = html.escape
    questions = "".join(f"<li>&ldquo;{e(q)}&rdquo;</li>" for q in f["questions"])
    badge = {"hidden gem": "Hidden gem: great reviews, low AI visibility",
             "near hidden gem": "Near hidden gem: great rating, almost enough reviews"}.get(f["kind"], "")
    badge_html = f'<span class="badge">{e(badge)}</span>' if badge else ""
    groups = grouped_fixes(f)
    if groups:
        # Grouped style: numbered fixes, each with steps underneath
        lead = settings(f).get("fix_groups_lead", "")
        fixes_lead = f'<p class="lead">{e(lead)}</p>' if lead else ""
        fixes = "".join(
            f"<li><strong>{e(g['title'])}</strong>"
            + (f"<span>{e(g['intro'])}</span>" if g["intro"] else "")
            + "<ul class=\"steps\">" + "".join(f"<li>{e(step)}</li>" for step in g["steps"])
            + "</ul></li>" for g in groups)
    else:
        fixes_lead = ""
        fixes = "".join(f"<li><strong>{e(t)}</strong>{e(body)}</li>" for t, body in suggested_fixes(f))
    if f["mentioned"] == 0:
        headline = (f"Claude didn't mention {e(f['name'])} in any of the {f['total']} answers "
                    f"about wedding planners near {e(f['town'])}, PA")
    else:
        headline = (f"Claude mentioned {e(f['name'])} in {f['mentioned']} of {f['total']} answers "
                    f"about wedding planners near {e(f['town'])}, PA")
    other_towns = ""
    if f["mentioned_anywhere"] == 0:
        other_towns = (f" You also weren't mentioned in any of the {f['all_answers']} answers "
                       f"we collected across all the nearby towns we checked.")
    planner_sections = f"""
  <section class="card">
    <h2>How often Claude recommends you as a wedding planner</h2>
    <div class="score">
      <div class="big">{f['percent']}%</div>
      <p>{headline}.{other_towns}</p>
    </div>
  </section>
{specialty_card(f)}"""
    instead_section = f"""
  <section class="card">
    <h2>Who Claude recommended instead (planner questions)</h2>
    <p class="muted">Businesses Claude named most often for {e(f['town'])}, out of {f['total']} answers.</p>
    {bar_list(f['instead'], f['total'])}
  </section>
"""

    def sources_section(title, sites, total, what):
        # Label clearly unrelated pages (e.g. job postings), but keep them in the list
        labeled = [(f"{site} — unrelated page ({unrelated_kind(site)})" if unrelated_kind(site)
                    else site, n) for site, n in sites]
        note = ("<p class=\"muted\">Claude sometimes cites pages that aren't about wedding vendors, "
                "like job postings. We show them so the list stays accurate.</p>"
                if any(unrelated_kind(site) for site, _ in sites) else "")
        return f"""
  <section class="card">
    <h2>{title}</h2>
    <p class="muted">The sources listed in Claude's answers to {what}, and how many of the {total} answers used each one.</p>
    {bar_list(labeled, total)}
    {note}
  </section>
"""

    # Businesses with a second test (e.g. Decor Co): those results are the main story, so they
    # come right after "In short", followed by the websites from their specialty + second-test
    # questions (the same list Fix #4 uses). ALL planner sections move down, before "How we tested".
    planner_sources = sources_section("Sources for planner questions", f["sites"], f["total"],
                                      "the wedding planner questions")
    spec_sites, spec_total, spec_topics = specialty_sources(f)
    specialty_sources_section = sources_section(
        "Websites Claude used to decide", spec_sites, spec_total,
        f"the {join_and(spec_topics)} questions") if spec_sites else ""
    if f.get("spec2"):
        top_sections = second_test_card(f) + specialty_sources_section
        bottom_sections = planner_sections + instead_section + planner_sources
    # Businesses with a specialty test (e.g. Florist & Event Co): the websites section above
    # the fixes shows the specialty sources (same list as the "Be complete" fix); the
    # planner-question sources move to the bottom.
    elif specialty_sources_section:
        top_sections = planner_sections + instead_section + specialty_sources_section
        bottom_sections = planner_sources
    else:
        top_sections = (planner_sections + instead_section
                        + sources_section("Websites Claude used to decide", f["sites"], f["total"],
                                          "the wedding planner questions"))
        bottom_sections = ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Visibility – {e(f['name'])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
  <header>
    <h1>AI visibility report: {e(f['name'])}</h1>
    <p>{e(f['town'])}, PA{formerly_html(f)} &middot; Google rating {e(f['rating'])} from {e(f['reviews'])} reviews &middot; Checked {e(day)}</p>
    {badge_html}
  </header>
{summary_card(f)}
{top_sections}
{other_ai_card(f)}
  <section class="card">
    <h2>Suggested fixes</h2>
    {fixes_lead}
    <ol class="fixes">{fixes}</ol>
  </section>
{bottom_sections}
  <section class="card">
    <h2>How we tested</h2>
    <p>On {e(day)} we asked Claude (with web search turned on) these wedding planner questions, {f['runs']} times each:</p>
    <ul>{questions}</ul>
    {"<p>We also asked the " + e(f['spec']['label']) + " questions shown above, " + str(f['spec']['runs']) + " times each.</p>" if f['spec'] else ""}
    <p class="muted">AI answers change from one try to the next, so we asked several times and counted.
    This is a small test ({f['total']} answers), so treat the numbers as a snapshot, not a final verdict.
    Business names were pulled automatically from the answer text. Other AI tools
    (ChatGPT, Google, Perplexity) may answer differently.</p>
  </section>

  <footer class="muted">Portfolio demo &middot; AI Visibility Checker</footer>
</main>
</body>
</html>
"""


# ---------- 4. Writing the draft message (plain text) ----------

def second_test_hook(f):
    """'AI recommends you for vintage wedding décor and at Hollis Mansion every time. But at
    Hollis Mansion it usually calls you "Decor Co Design" or "Old Name Rentals"; ...'
    Built only from the measured numbers."""
    n = name_story(f)
    if not n["every_time"]:
        return ""
    from check_specialty import other_names_in
    answers = f["spec2_answers"]
    cfg = settings(f)

    # Confirmed name change: lead with the place where AI recommends them every time,
    # but mixes in the OLD name
    if cfg.get("old_name") and cfg.get("linked_names_confirmed"):
        for q in n["weak"]:
            if q not in n["every_time"]:
                continue
            rs = [a for a in answers if a["name"] == f["name"] and a["question"] == q["question"]]
            k = old_name_answers(f, rs)
            seen = Counter(x for a in rs for x in other_names_in(a["answer"], f["name"])
                           if x in cfg.get("old_name_variants", []))
            old_forms = " or ".join(f"“{x}”" for x, _ in seen.most_common())
            who = "every answer also used" if k == q["asked"] else f"{k} of {q['asked']} answers also used"
            hook = (f"Claude recommended you {topic_text(q)} every time I asked, but {who} your "
                    f"old name ({old_forms}), and only {q['hits']} of {q['asked']} used your full "
                    f"new name, “{f['name']}”.")
            others = other_tools_number_one(f, "Hollis Mansion") if "Hollis Mansion" in q["topic"] else []
            if others:
                hook += f" {join_and(others)} also picked you #1 there."
            return hook

    hook = (f"Claude recommends you {join_and([topic_text(q) for q in n['every_time']])} every time.")
    for q in n["weak"]:
        rs = [a for a in answers if a["name"] == f["name"] and a["question"] == q["question"]]
        counts = Counter(x for a in rs for x in other_names_in(a["answer"], f["name"]))
        # only names used in MORE than half of these answers count as "usually"
        usual = [name for name, c in counts.most_common(2) if c > q["asked"] / 2]
        if usual:
            hook += (f" But {topic_text(q)} it usually calls you "
                     + " or ".join(f"\"{u}\"" for u in usual)
                     + f"; your full name, \"{f['name']}\", came up in only {q['hits']} of "
                       f"{q['asked']} answers.")
    return hook


# How the hand-check topics read in the message
OTHER_TOPIC_TEXT = {
    "Hollis Mansion": "for a wedding at Hollis Mansion",
    "vintage décor": "for vintage décor near Malvern",
}


# Who's writing, and why (free research, no sales pitch: OPT rules + honest outreach)
MESSAGE_INTRO = ("I'm Lakshmi, a recent Villanova computer science grad. I'm running a research "
                 "project on how AI assistants like ChatGPT, Perplexity and Claude recommend "
                 "local wedding vendors, and your business came up.")
MESSAGE_CLOSE = ("This is free research, not a sales pitch. I've written up your results and a "
                 "few fixes in a short report. Would you like me to send it? If it's useful, "
                 "I'd also love to know whether I could use your results as a case study, "
                 "with or without your name.")
SIGNATURE = ["Best,", "Lakshmi Tulasi Maradana"]


def protect_top_spot_message(f):
    """'Protect your top spot' message: good news (other AI tools rank them #1), one risk
    (Claude uses the old name; venue credits use several names), then the offer.
    Every claim comes from the data or the hand checks."""
    cfg = settings(f)
    rows = other_rows(f)
    # Only the topics the message is about (keeps it short: vintage décor and Hollis Mansion)
    topics = list(dict.fromkeys(r["topic"] for r in rows
                                if r["rank"] == "1" and r["topic"] in OTHER_TOPIC_TEXT))
    by_topic = sorted(((t, other_tools_number_one(f, t)) for t in topics), key=lambda x: -len(x[1]))
    good = []
    for i, (t, tools) in enumerate(by_topic):
        phrase = OTHER_TOPIC_TEXT.get(t, f"for {t}")
        if i == 0:
            each = " each" if len(tools) > 1 else ""
            good.append(f"Good news: when I asked AI tools who to hire {phrase}, "
                        f"{join_and(tools)}{each} picked you #1.")
        else:
            good.append(f"{join_and(tools)} also ranked you #1 {phrase}.")
    n = name_story(f)
    k = old_name_answers(f, own_answers_2(f))
    # k counts the old name OR a short form of it (e.g. "Old Name"), so say so
    risk = (f"One risk: Claude often uses your old name. “{cfg['old_name']}” or a short "
            f"form of it came up in {k} of {n['total']} of its answers")
    if cfg.get("message_risk_extra"):
        risk += f", and {cfg['message_risk_extra']}"
    risk += ". Mixed names can split the credit AI gives you."
    lines = [
        "=== DRAFT - not sent. Read it, edit it, and send it yourself. Delete this line. ===",
        "",
        "Subject: Protecting your top spot in AI recommendations",
        "",
        f"Hi {f['name']} team,",
        "",
        MESSAGE_INTRO,
        "",
        " ".join(good),
        "",
        risk,
        "",
        MESSAGE_CLOSE,
        "",
    ] + SIGNATURE + [
    ]
    return "\n".join(lines) + "\n"


def second_test_message(f, day):
    if settings(f).get("message_style") == "protect_top_spot" and other_rows(f):
        return protect_top_spot_message(f)
    n = name_story(f)
    asks = n["asks"]
    examples = " and ".join(f"\"{q['question']}\"" for q in asks[:2])
    lines = [
        "=== DRAFT - not sent. Read it, edit it, and send it yourself. Delete this line. ===",
        "",
        f"Subject: How AI assistants recommend {f['name']}",
        "",
        f"Hi {f['name']} team,",
        "",
        MESSAGE_INTRO,
        "",
        f"I've been testing how AI assistants recommend local wedding vendors. On "
        f"{f['spec2']['day']} I asked Claude (with web search) questions like {examples}, "
        f"{asks[0]['asked']} times each.",
        "",
        second_test_hook(f),
        "",
        MESSAGE_CLOSE,
        "",
    ] + SIGNATURE + [
    ]
    return "\n".join(lines) + "\n"


def message_text(f, day):
    # Businesses with a second test get a message built around those results
    if name_story(f) and second_test_hook(f):
        return second_test_message(f, day)
    q = f["questions"][0] if f["questions"] else f"wedding planners near {f['town']}, PA"
    if f["mentioned"] == 0:
        result = (f"Your business wasn't mentioned in any of those {f['total']} answers, "
                  f"even though you have a {f['rating']} rating on Google.")
    else:
        result = (f"Your business came up in {f['mentioned']} of those {f['total']} answers, "
                  f"even though you have a {f['rating']} rating on Google.")
    named = " and ".join(f"{name} ({n} of {f['total']})" for name, n in f["instead"][:2])
    top_sites = [s for s, _ in f["sites"][:3]]
    sites = (", ".join(top_sites[:-1]) + " and " + top_sites[-1]) if len(top_sites) > 1 else "".join(top_sites)
    n_questions = {1: "one question", 2: "two questions", 3: "three questions"}.get(
        len(f["questions"]), f"{len(f['questions'])} questions")

    # Step 7: one sentence about the specialty questions, using only the real numbers
    spec_line = ""
    s = f["spec"]
    topic = {t["topic"]: t for t in s["topics"]} if s else {}
    if s and s["questions"]:
        sq = s["questions"][0]
        # Florist who also plans events: use the split numbers, so it matches the report
        if (s["percent"] > f["percent"] and is_florist(f) and offers_planning(f)
                and "florist" in topic and "event design" in topic):
            fl, de = topic["florist"], topic["event design"]
            florist_part = (f"all {fl['total']} answers" if fl["mentioned"] == fl["total"]
                            else f"{fl['mentioned']} of {fl['total']} answers")
            planner_part = (f"none of {f['total']}" if f["mentioned"] == 0
                            else f"{f['mentioned']} of {f['total']}")
            spec_line = (f"When I asked florist questions instead, Claude mentioned you in "
                         f"{florist_part}, but only {de['mentioned']} of {de['total']} event design "
                         f"answers and {planner_part} wedding planner answers. So Claude knows you "
                         f"as a florist, but not for your planning and design work.")
        elif s["percent"] > f["percent"]:
            spec_line = (f"Interestingly, when I asked {s['label']} questions instead (like \"{sq}\"), "
                         f"Claude did mention you in {s['mentioned']} of {s['total']} answers. "
                         f"So Claude knows you for {s['label']}, just not as a planner.")
        elif s["mentioned"] == 0:
            spec_line = (f"I also asked {s['label']} questions (like \"{sq}\"), and you weren't "
                         f"mentioned in any of those {s['total']} answers either.")
        else:
            spec_line = (f"For {s['label']} questions (like \"{sq}\"), you came up in "
                         f"{s['mentioned']} of {s['total']} answers.")
    lines = [
        "=== DRAFT - not sent. Read it, edit it, and send it yourself. Delete this line. ===",
        "",
        f"Subject: How AI assistants answer \"wedding planner near {f['town']}\"",
        "",
        f"Hi {f['name']} team,",
        "",
        MESSAGE_INTRO,
        "",
        f"On {day} I asked Claude (with web search) {n_questions}, such as \"{q}\", "
        f"{f['runs']} times each ({f['total']} answers in total).",
        "",
        result + (f" The planners it named most often were {named}," if named else "")
        + (f" and it relied mostly on {sites}." if sites else ""),
        "",
    ] + ([spec_line, ""] if spec_line else []) + (
        [settings(f)["message_extra"], ""] if settings(f).get("message_extra") else []) + [
        MESSAGE_CLOSE,
        "",
    ] + SIGNATURE + [
    ]
    return "\n".join(lines) + "\n"


# ---------- 5. Run it ----------

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main(scores_path=None, visibility_path=None):
    scores_path = scores_path or latest_path("scores")
    visibility_path = visibility_path or latest_path("visibility")
    print(f"Using {scores_path} and {visibility_path}\n")
    day = run_date(visibility_path)

    scores = read_csv(scores_path)
    answers = [r for r in read_csv(visibility_path) if not r["answer"].startswith("ERROR")]
    planners = {p["name"]: p for p in load_planners()}

    # Step 7: the newest specialty scores, if a specialty run exists (kept separate from planner scores)
    spec_rows, spec_answers = {}, []
    try:
        spec_scores_path = latest_path("specialty_scores")
        spec_rows = {r["name"]: r for r in read_csv(spec_scores_path)}
        spec_answers = read_csv(latest_path("specialty_visibility"))
        print(f"Specialty scores from {spec_scores_path}\n")
    except FileNotFoundError:
        print("(No specialty run yet - reports will show planner scores only.)\n")

    # Second specialty test (one score per question), if it has been run
    spec2_rows, spec2_answers = [], []
    try:
        spec2_path = latest_path("specialty2_scores")
        spec2_rows = read_csv(spec2_path)
        spec2_answers = read_csv(latest_path("specialty2_visibility"))
        print(f"Second specialty test from {spec2_path}\n")
    except FileNotFoundError:
        pass

    # Who gets a report: hidden gems, plus "near hidden gems" (Step 7)
    targets = []
    for s in scores:
        p = planners[s["name"]]
        if s.get("group") == "hidden gem":
            targets.append((s, "hidden gem"))
        elif near_hidden_gem(to_number(p["google_rating"]), to_number(p["review_count"]),
                             int(s["score_percent"])):
            targets.append((s, "near hidden gem"))
    if not targets:
        print("No hidden gems or near hidden gems in this run - nothing to write.")
        return
    for s, kind in targets:
        f = facts_for(planners[s["name"]], s, answers, scores, kind,
                      spec_rows.get(s["name"]), spec_answers)
        f["spec2"] = second_test_facts(s["name"], spec2_rows, spec2_answers)
        f["spec2_answers"] = spec2_answers
        # Reports and messages: ONE file per business per day. Re-making it on the same day
        # replaces that day's file; a different day gets its own dated file (history kept).
        report = day_path(slug(s["name"]), day=day, ext="html", folder="reports")
        with open(report, "w", encoding="utf-8") as out:
            out.write(report_html(f, day))
        message = day_path(slug(s["name"]), day=day, ext="txt", folder="messages")
        with open(message, "w", encoding="utf-8") as out:
            out.write(message_text(f, day))
        spec = f["spec"]
        print(f"{s['name']} ({kind}): planner {f['mentioned']}/{f['total']} = {f['percent']}%"
              + (f" | {spec['label']} {spec['mentioned']}/{spec['total']} = {spec['percent']}%"
                 if spec else ""))
        print(f"   report:  {report}")
        print(f"   message: {message}   (DRAFT - never sent automatically)")
    print("\nOpen the .html file in your browser. Read the .txt draft before sending anything.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
