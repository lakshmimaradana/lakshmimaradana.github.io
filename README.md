# AI Visibility Checker for local wedding vendors

When couples ask ChatGPT, Perplexity, Google or Claude "who's the best wedding planner near me?", the answer names three to five businesses. I wanted to know which small vendors get left out, and why.

This is a portfolio project I built in November 2026 to practice go-to-market work: picking a market, finding the right businesses, figuring out what to tell them, and reaching out.

## What it does

1. **Picks businesses worth checking.** I started with five wedding vendors on Philadelphia's Main Line with strong Google reviews (4.5 stars or more). Strong reviews and weak AI visibility is the group I'm after. A business with bad reviews isn't a fit, because visibility won't fix bad service.
2. **Asks Claude the questions couples ask.** `check_planners.py` runs Claude Code with web search, 5 times per question, because AI answers change from one try to the next. It records who was named, in what order, and which websites the answer cited.
3. **Asks narrower questions too.** `check_specialty.py` asks about each business's specialty and venues (for example "vintage wedding décor near Malvern"), since small vendors usually win on narrow questions, not on "best wedding planner".
4. **Checks other AI tools by hand.** `open_checks.py` opens the same questions in ChatGPT, Perplexity and Google AI Mode. I paste the answers into a folder and `score_pasted.py` scores them. No bots, no paid APIs.
5. **Writes a report and a first message.** `make_reports.py` builds one report per business: how often each AI tool names it, which websites the AI relied on, and a short list of fixes. It also drafts an outreach message. Nothing is ever sent automatically.

## What I found

- **Claude leans on wedding directories.** Zola showed up in 50 of 50 "best planner" answers. The planners' own websites showed up in 0 of 50.
- **Each AI tool reads different sources.** Perplexity cited official websites and venue pages. Google AI Mode and ChatGPT leaned on Google-style business listings.
- **Businesses go missing for different reasons, so a single score hides the fix.** Three examples:
  - *Known for the wrong thing.* A King of Prussia florist and event company was Perplexity's top florist pick and showed up in 5 of 5 Claude florist answers, but in 0 of 10 planner answers, even though it plans full events.
  - *Credit split by an old name.* A Malvern décor company was picked #1 for weddings at a local mansion by Perplexity, Google AI Mode and ChatGPT. Claude used its old business name in 13 of 15 answers, and the venue's own gallery credited it under three different names.
  - *Credit split by the wrong town.* The florist above has a WeddingWire listing with 13 reviews that says "Ardmore" but gives a King of Prussia address. When an AI grader looked it up through Perplexity, it refused to count those reviews.
- **Checking one AI tool isn't enough.** On Claude alone, the Malvern company looked poorly known. On the other three tools it was the top pick. I would have given it the wrong advice.

## How this compares to existing tools

This idea isn't new. Profound, Peec AI, Otterly, Semrush and Ahrefs track AI mentions for brands. BrightLocal's Local AI Visibility does it for local businesses on ChatGPT and Google, with a score and suggested fixes. HubSpot's free AI Search Grader gives a one-time score. I ran one business through HubSpot's grader: it scored 31 on ChatGPT, 66 on Perplexity and 51 on Gemini, the same order my checks found, but one score for the whole business couldn't show that it was missing only for planner questions.

What this project adds:
- specific causes (old name, wrong town, wrong category) instead of only a score
- specialty and venue questions
- Claude and Perplexity alongside ChatGPT and Google
- the go-to-market side: who to contact, what to say first, and how to track replies

## Outreach

On November 18, 2026 I sent the first two messages, one by email and one by Instagram DM. Each leads with one specific finding about that business and offers the report for free. I track every message in a simple log (drafted, sent, replied, report sent, OK to use as a case study) so I can see where the funnel drops off.

The business names are left out until they say I can use them as case studies. In this repo's data files, business names, websites, handles and the venue are replaced with placeholders (Planner One, Florist & Event Co, Decor Co, Hollis Mansion, .example domains).

## Limits

- Small samples: 5 tries per question on Claude, and 1 or 2 hand checks on the other tools. These are snapshots, not final verdicts.
- AI answers change over time and can be personalized.
- Anything only an AI answer claims (an award, for example) is checked at the original source before it goes in a report.
- Honest fixes only: clearer websites, correct listings, real reviews.

## Running it

You need Python 3 and [Claude Code](https://claude.com/claude-code) installed. No other packages.

```
python check_planners.py                          # planner questions on Claude, scores, sources, reports
python check_specialty.py                         # specialty questions (add --test specialty2 for the second test)
python open_checks.py --business "name" --dry-run # list the hand-check questions for other AI tools
python score_pasted.py                            # score answers pasted into pasted_answers/<date>/
python make_reports.py                            # rebuild reports and draft messages
```

Every run is saved as a new dated file in `results/`, so earlier runs are never overwritten.
