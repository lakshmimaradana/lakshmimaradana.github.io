# KEEP HISTORY helper - shared by all the scripts.
# Rule: never overwrite old results. Every run saves to a NEW dated file in the
# results/ folder, e.g. results/2026-11-17_visibility.csv, so later we can compare
# "last month vs this month".
# If a file for today already exists, we add _2, _3, ... instead of overwriting it:
#   results/2026-11-17_visibility.csv  ->  results/2026-11-17_visibility_2.csv

import glob
import os
import re
from datetime import date

RESULTS_DIR = "results"


def new_path(kind, day=None, ext="csv", folder=RESULTS_DIR):
    """A brand-new file name like results/2026-11-17_scores.csv (never an existing one)."""
    os.makedirs(folder, exist_ok=True)
    day = day or date.today().isoformat()
    path = os.path.join(folder, f"{day}_{kind}.{ext}")
    number = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{day}_{kind}_{number}.{ext}")
        number += 1
    return path


def day_path(kind, day=None, ext="csv", folder=RESULTS_DIR):
    """ONE file per day, e.g. reports/2026-11-17_decor-co.html.
    Used for reports and messages: re-making them on the same day REPLACES that day's file,
    while a different day gets its own dated file (so history across days is kept).
    Raw results (results/ folder) use new_path() instead and are never replaced."""
    os.makedirs(folder, exist_ok=True)
    day = day or date.today().isoformat()
    return os.path.join(folder, f"{day}_{kind}.{ext}")


def latest_path(kind, ext="csv"):
    """The most recently saved file of this kind, e.g. the newest ..._visibility.csv."""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_" + re.escape(kind) + r"(_\d+)?\." + ext + "$")
    files = [f for f in glob.glob(os.path.join(RESULTS_DIR, "*." + ext))
             if pattern.match(os.path.basename(f))]
    if not files:
        raise FileNotFoundError(
            f"No {kind} file found in {RESULTS_DIR}/ - run check_planners.py first.")
    return max(files, key=os.path.getmtime)


def run_date(path):
    """The date at the start of a results file name: results/2026-11-17_x.csv -> 2026-11-17"""
    return os.path.basename(path)[:10]
