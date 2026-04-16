#!/usr/bin/env python3
"""
6-hourly job scraper for Youssef's cybersecurity-internship search.

Runs from cron. Pulls every endpoint in companies.API_COMPANIES, normalises into a
common record shape, scores it, dedupes against jobs.csv, and APPENDS new rows.
SWISS_DIRECT_APPLY entries are also re-seeded each run (already-deduped).

Usage:
    python3 scrape_jobs.py            # full run, append-only
    python3 scrape_jobs.py --dry-run  # print what would be added, don't write
    python3 scrape_jobs.py --rebuild  # rebuild jobs.csv from scratch
                                       # (BACKS UP existing csv first)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.error
from typing import Iterable

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "jobs.csv")
LOG_PATH = os.path.join(ROOT, "logs", "scraper.log")

sys.path.insert(0, HERE)
from companies import API_COMPANIES, SWISS_DIRECT_APPLY                     # type: ignore
from score_match import score_job, classify_country, classify_work_mode     # type: ignore


# ---------------------------------------------------------------------------
# CSV schema (column order locked - the cron and Excel both depend on it)
# ---------------------------------------------------------------------------
COLUMNS = [
    "First Seen",          # ISO date when scraper first found it
    "Country",             # CH / DE / UK / etc. - for sorting
    "Company",
    "Job Title",
    "Location",
    "Work Mode",           # Remote / Hybrid / On-site
    "Department",
    "Match Score",         # 0-100
    "Why I Fit",           # short rationale
    "Key Skills Required", # extracted skill keywords
    "Avg Salary (this country)",  # populated lazily by artefact generator if asked
    "Hiring Manager",      # blank unless we discover it
    "Contact Email",       # blank unless we discover it
    "Status",              # Open / Closed / Pending - default Open
    "Application Link",
    "CV Feedback / Edits Needed",  # auto-suggested per-role tweaks
    "Applied",             # USER edits this (empty | yes | YYYY-MM-DD)
    "Generate Artefacts",  # USER edits this to "yes" to trigger cover letter + CV tailor
    "Generated At",        # ISO date when generate_artefacts.py ran for this row
    "Notes",               # USER scratch column
]

# Salary expectation (rough median for the country, EUR or local).
# Source: aggregated from levels.fyi / glassdoor / kununu / payscale 2025-2026 ranges.
# These are TYPICAL intern stipends per month, NOT full-time salaries.
SALARY_HINTS = {
    "Switzerland":   "CHF 2'400 - 3'500 / month (intern); CHF 90k-130k / yr (jr FT)",
    "Germany":       "EUR 1'800 - 2'600 / month (intern); EUR 60k-85k / yr (jr FT)",
    "United Kingdom":"GBP 2'500 - 4'000 / month (intern, London); GBP 50k-80k / yr (jr FT)",
    "Ireland":       "EUR 2'500 - 3'800 / month (intern); EUR 55k-75k / yr (jr FT)",
    "France":        "EUR 1'200 - 2'200 / month (stage); EUR 45k-65k / yr (jr FT)",
    "Netherlands":   "EUR 1'800 - 2'800 / month (intern); EUR 55k-80k / yr (jr FT)",
    "Spain":         "EUR 800 - 1'500 / month (intern); EUR 35k-55k / yr (jr FT)",
    "Portugal":      "EUR 800 - 1'400 / month (intern); EUR 30k-48k / yr (jr FT)",
    "Italy":         "EUR 800 - 1'400 / month (stage); EUR 32k-48k / yr (jr FT)",
    "Sweden":        "SEK 18'000 - 25'000 / month (intern); SEK 480k-620k / yr (jr FT)",
    "USA":           "USD 7'500 - 10'000 / month (intern at FAANG/AI lab); USD 130k-180k / yr (jr FT)",
    "Canada":        "CAD 5'000 - 7'500 / month (intern); CAD 95k-130k / yr (jr FT)",
    "Saudi Arabia":  "SAR 5'000 - 9'000 / month (intern); SAR 200k-350k / yr (jr FT)",
    "UAE":           "AED 6'000 - 12'000 / month (intern); AED 240k-420k / yr (jr FT)",
    "Singapore":     "SGD 3'500 - 6'000 / month (intern); SGD 90k-140k / yr (jr FT)",
    "Remote":        "Varies wildly by employer country; ask in screening",
}


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# HTTP fetch with retries and a polite user-agent
# ---------------------------------------------------------------------------
def fetch_json(url: str, timeout: int = 20, retries: int = 2) -> dict | list | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (jobQuery scraper; personal job search; contact youssef.barrima@epfl.ch)",
        "Accept": "application/json",
    }
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            log(f"  fetch failed for {url}: {e!r}")
            return None
    return None


# ---------------------------------------------------------------------------
# Per-board parsers - each yields normalised dicts
# ---------------------------------------------------------------------------
def parse_greenhouse(company: str, payload: dict) -> Iterable[dict]:
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        title = j.get("title", "") or ""
        # Departments may be a list of {name}; flatten.
        depts = j.get("departments") or []
        dept = ", ".join(d.get("name", "") for d in depts if isinstance(d, dict)) or ""
        body_html = j.get("content") or ""
        # Cheap HTML strip - we only need keyword density, not faithful text.
        body = body_html.replace("<", " <").replace(">", "> ")
        url = j.get("absolute_url", "")
        yield {
            "company": company.title(),
            "title": title,
            "location": loc,
            "department": dept,
            "body": body,
            "employment_type": "",        # greenhouse rarely exposes this cleanly
            "url": url,
        }


def parse_ashby(company: str, payload: dict) -> Iterable[dict]:
    for j in payload.get("jobs", []):
        title = j.get("title", "") or ""
        loc = j.get("location", "") or j.get("locationName", "") or ""
        if isinstance(loc, dict):
            loc = loc.get("name", "")
        dept = j.get("department", "") or j.get("team", "") or ""
        if isinstance(dept, dict):
            dept = dept.get("name", "")
        body = j.get("descriptionPlain") or j.get("descriptionHtml") or ""
        et = j.get("employmentType") or ""
        url = j.get("jobUrl") or j.get("applyUrl") or ""
        yield {
            "company": company.title(),
            "title": title,
            "location": loc,
            "department": dept,
            "body": body,
            "employment_type": et,
            "url": url,
        }


def parse_lever(company: str, payload: list) -> Iterable[dict]:
    if not isinstance(payload, list):
        return
    for j in payload:
        title = j.get("text", "") or ""
        cats = j.get("categories", {}) or {}
        loc = cats.get("location", "") or ""
        dept = cats.get("team", "") or cats.get("department", "") or ""
        et = cats.get("commitment", "") or ""
        body = ""
        for lst in j.get("lists", []) or []:
            body += (lst.get("text", "") or "") + "\n"
        body += j.get("descriptionPlain", "") or j.get("description", "") or ""
        url = j.get("hostedUrl") or j.get("applyUrl") or ""
        yield {
            "company": company.title(),
            "title": title,
            "location": loc,
            "department": dept,
            "body": body,
            "employment_type": et,
            "url": url,
        }


PARSERS = {"greenhouse": parse_greenhouse, "ashby": parse_ashby, "lever": parse_lever}


# ---------------------------------------------------------------------------
# CV-feedback heuristic per role
# ---------------------------------------------------------------------------
def cv_feedback_for(title: str, body: str, key_skills: list) -> str:
    """Return 1-3 short suggestions for what to tweak in the per-role CV strengths."""
    text = (title + " " + body).lower()
    suggestions = []
    if "ai" in text or "llm" in text or "adversarial" in text or "red team" in text:
        suggestions.append("Lead Strengths bullet 2 with AI red-team / OWASP LLM Top 10 framing")
    if "appsec" in text or "application security" in text:
        suggestions.append("Highlight CI/CD security gates + SAST/DAST exposure first")
    if "detection" in text or "soc" in text or "siem" in text:
        suggestions.append("Lead with Splunk migration + 20% MTTD reduction")
    if "cryptograph" in text or "confidential computing" in text or "tee" in text:
        suggestions.append("Surface EPFL applied-cryptography / confidential-computing focus in bullet 3")
    if "kubernetes" in text or " k8s" in text or "cloud" in text or "aws" in text or "gcp" in text:
        suggestions.append("Add 'cloud security (AWS/GCP)' to Strengths if you have any exposure; otherwise call it out as 'currently learning'")
    if "german" in text and "fluent" in text:
        suggestions.append("Flag German B1 + active improvement in cover letter; OK in CV as is")
    if not suggestions:
        suggestions.append("Mirror the JD's exact phrasing in Strengths bullets; keep wording crisp")
    return " | ".join(suggestions[:3])


# ---------------------------------------------------------------------------
# CSV io
# ---------------------------------------------------------------------------
def load_existing(path: str) -> tuple[list, set]:
    """Return (existing_rows_list, dedupe_key_set)."""
    rows = []
    keys = set()
    if not os.path.exists(path):
        return rows, keys
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
            keys.add(_dedupe_key(row.get("Company", ""), row.get("Job Title", ""), row.get("Location", "")))
    return rows, keys


def _dedupe_key(company: str, title: str, location: str) -> str:
    return f"{company.strip().lower()}||{title.strip().lower()}||{location.strip().lower()}"


def write_csv(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def append_csv(path: str, new_rows: list) -> None:
    if not new_rows:
        return
    file_exists = os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if not file_exists:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def collect_jobs() -> list:
    """Pull every endpoint and yield normalised dicts."""
    all_jobs = []
    for company, cfg in API_COMPANIES.items():
        log(f"polling {company} ({cfg['board_type']}) ...")
        payload = fetch_json(cfg["endpoint"])
        if payload is None:
            continue
        parser = PARSERS.get(cfg["board_type"])
        if parser is None:
            log(f"  unknown board type {cfg['board_type']}")
            continue
        n_before = len(all_jobs)
        for j in parser(company, payload):
            all_jobs.append(j)
        log(f"  +{len(all_jobs) - n_before} jobs from {company}")
    return all_jobs


def score_and_filter(raw_jobs: list, min_score: int = 30) -> list:
    """Score every job; drop those that don't pass min_score. Returns CSV-ready row dicts."""
    today = dt.date.today().isoformat()
    rows = []
    for j in raw_jobs:
        score, why, skills = score_job(
            j["title"], j["location"], j["department"],
            j.get("body", ""), j.get("employment_type", "")
        )
        if score < min_score:
            continue
        country = classify_country(j["location"])
        rows.append({
            "First Seen": today,
            "Country": country,
            "Company": j["company"],
            "Job Title": j["title"],
            "Location": j["location"],
            "Work Mode": classify_work_mode(j["location"], j.get("body", "")),
            "Department": j["department"],
            "Match Score": score,
            "Why I Fit": why,
            "Key Skills Required": ", ".join(skills),
            "Avg Salary (this country)": SALARY_HINTS.get(country, ""),
            "Hiring Manager": "",
            "Contact Email": "",
            "Status": "Open",
            "Application Link": j["url"],
            "CV Feedback / Edits Needed": cv_feedback_for(j["title"], j.get("body", ""), skills),
            "Applied": "",
            "Generate Artefacts": "",
            "Generated At": "",
            "Notes": "",
        })
    return rows


def seed_direct_apply_rows() -> list:
    """Re-create rows for the manually-curated SWISS_DIRECT_APPLY portals."""
    today = dt.date.today().isoformat()
    rows = []
    for company, title, location, url, why in SWISS_DIRECT_APPLY:
        country = classify_country(location)
        # We score these with a synthetic JD-like text so the gatekeeper passes.
        synth_body = title + " " + why
        score, why_score, skills = score_job(title, location, "Security", synth_body, "intern")
        # Floor portal entries at 60 so they're visible in your sort.
        score = max(score, 60)
        rows.append({
            "First Seen": today,
            "Country": country,
            "Company": company,
            "Job Title": title + "  [check portal]",
            "Location": location,
            "Work Mode": classify_work_mode(location),
            "Department": "Security (curated portal)",
            "Match Score": score,
            "Why I Fit": why,
            "Key Skills Required": ", ".join(skills) if skills else "Python, SIEM, Pentest, AppSec, DevSecOps",
            "Avg Salary (this country)": SALARY_HINTS.get(country, ""),
            "Hiring Manager": "",
            "Contact Email": "",
            "Status": "Open (manual portal)",
            "Application Link": url,
            "CV Feedback / Edits Needed": "Tailor Strengths bullet to portal posting once it appears",
            "Applied": "",
            "Generate Artefacts": "",
            "Generated At": "",
            "Notes": "Portal is JS-rendered; check manually each week",
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="don't write to csv")
    p.add_argument("--rebuild", action="store_true", help="back up old csv and start fresh")
    p.add_argument("--min-score", type=int, default=50,
                   help="drop any job whose match score falls below this (default 50)")
    args = p.parse_args()

    log("=== scrape run starting ===")

    if args.rebuild and os.path.exists(CSV_PATH):
        bk = CSV_PATH + ".bak." + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(CSV_PATH, bk)
        log(f"backed up existing csv -> {bk}")
        os.remove(CSV_PATH)

    existing_rows, existing_keys = load_existing(CSV_PATH)
    log(f"loaded {len(existing_rows)} existing rows")

    raw_jobs = collect_jobs()
    log(f"total raw jobs across all boards: {len(raw_jobs)}")

    scored = score_and_filter(raw_jobs, min_score=args.min_score)
    log(f"after scoring/filter (>= {args.min_score}): {len(scored)} rows")

    direct = seed_direct_apply_rows()
    log(f"+ {len(direct)} curated direct-apply portal rows")

    candidate_rows = scored + direct

    new_rows = []
    for r in candidate_rows:
        k = _dedupe_key(r["Company"], r["Job Title"], r["Location"])
        if k in existing_keys:
            continue
        existing_keys.add(k)
        new_rows.append(r)

    log(f"=> {len(new_rows)} NEW rows to append (deduped)")

    if args.dry_run:
        for r in new_rows[:30]:
            print(f"  + [{r['Match Score']:3d}] {r['Company']} | {r['Job Title']} | {r['Location']}")
        log("dry-run; not writing.")
        return 0

    # Sort new rows by match score desc before append so a fresh tail is the most useful first.
    new_rows.sort(key=lambda r: -int(r["Match Score"]))
    append_csv(CSV_PATH, new_rows)
    log(f"appended {len(new_rows)} rows -> {CSV_PATH}")
    log("=== scrape run done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
