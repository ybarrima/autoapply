#!/usr/bin/env python3
"""
On-demand cover-letter and tailored-CV generator.

Reads jobs.csv, finds rows where the user set `Generate Artefacts = yes`, and for each:
  1. Calls `claude -p` with a tightly-scoped prompt to produce a non-AI-sounding
     cover letter.
  2. Calls `claude -p` again to produce 3 tailored Strengths bullets, then surgically
     swaps them into a copy of cv_latex/templates/master.tex saved as
     cv_latex/generated/<company>_<title>.tex.
  3. Marks the row as processed by setting `Generated At = <today>` and clearing
     `Generate Artefacts`.

All personal data (name, contact info, candidate facts, style rules) is loaded from
profile.yaml in the project root. Copy profile.yaml.example to profile.yaml and
fill in your own details.

Usage:
    python3 generate_artefacts.py            # process all rows marked yes
    python3 generate_artefacts.py --row 17   # process only row index 17 (0-based, header excluded)
    python3 generate_artefacts.py --list     # list pending rows, do nothing
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "jobs.csv")
COVER_DIR = os.path.join(ROOT, "cover_letters")
CV_OUT_DIR = os.path.join(ROOT, "cv_latex", "generated")
CV_MASTER = os.path.join(ROOT, "cv_latex", "templates", "master.tex")
LOG = os.path.join(ROOT, "logs", "artefact_gen.log")
PROFILE_PATH = os.path.join(ROOT, "profile.yaml")

CLAUDE_BIN = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
CLAUDE_MODEL = "claude-opus-4-6"

# Markets where photo MUST be off (US/UK/IE/Nordics).
PHOTO_OFF_COUNTRIES = {
    "USA", "United States", "United Kingdom", "UK", "Ireland",
    "Sweden", "Norway", "Denmark", "Finland", "Iceland", "Canada", "Australia",
}


# ---------------------------------------------------------------------------
# Minimal YAML loader (stdlib only, handles the flat key: "value" + key: |
# multiline block format used in profile.yaml — no pip dependency needed).
# ---------------------------------------------------------------------------
def load_profile() -> dict:
    """Parse profile.yaml into a dict. Supports scalar and block-literal values."""
    if not os.path.exists(PROFILE_PATH):
        print(f"ERROR: {PROFILE_PATH} not found.\n"
              f"Copy profile.yaml.example to profile.yaml and fill in your details.")
        sys.exit(1)

    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = {}
    current_key = None
    block_lines: list[str] = []
    block_indent = 0

    def _flush():
        if current_key and block_lines:
            result[current_key] = "\n".join(block_lines)

    for raw in lines:
        # Skip blank lines outside blocks and comments
        stripped = raw.rstrip("\n")
        if stripped.lstrip().startswith("#") and current_key is None:
            continue

        # Check for a top-level key (no leading whitespace, contains colon)
        m = re.match(r'^([a-z_]+)\s*:\s*(.*)', stripped)
        if m and not stripped[0].isspace():
            _flush()
            key = m.group(1)
            val = m.group(2).strip()
            if val == "|":
                current_key = key
                block_lines = []
                block_indent = 0
            elif val.startswith('"') and val.endswith('"'):
                result[key] = val[1:-1]
                current_key = None
                block_lines = []
            else:
                result[key] = val
                current_key = None
                block_lines = []
        elif current_key is not None:
            # Inside a block literal
            if stripped.strip() == "" and not block_lines:
                continue  # skip leading blanks
            if block_indent == 0 and stripped.strip():
                block_indent = len(stripped) - len(stripped.lstrip())
            block_lines.append(raw.rstrip("\n")[block_indent:] if block_indent else raw.rstrip("\n"))

    _flush()
    return result


PROFILE: dict = {}


def _p(key: str) -> str:
    """Get a profile value or die with a helpful message."""
    val = PROFILE.get(key, "")
    if not val:
        print(f"ERROR: '{key}' is missing or empty in profile.yaml")
        sys.exit(1)
    return val


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s[:maxlen] or "untitled"


def call_claude(prompt: str) -> str:
    """Invoke `claude -p` headless. Returns stdout (the model's response)."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--model", CLAUDE_MODEL]
    log(f"  claude -p (model={CLAUDE_MODEL}, prompt={len(prompt)} chars)")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
    except subprocess.TimeoutExpired:
        log("  TIMEOUT after 240s")
        return ""
    if out.returncode != 0:
        log(f"  claude exited {out.returncode}: {out.stderr[:300]}")
    return (out.stdout or "").strip()


# ---------------------------------------------------------------------------
# Prompt templates — personal data injected from profile.yaml at runtime
# ---------------------------------------------------------------------------
COVER_LETTER_PROMPT = """\
You are writing a cover letter on behalf of {name} for a SPECIFIC job listing.

Hard rules (a single violation makes the output unusable):
{cover_letter_rules}
Sign-off: exactly "Best regards,\\n{name}"
Plain text only. No markdown, no bullet points.

Candidate facts you MAY use (do not fabricate beyond these):
{candidate_facts}

Job listing details:
- Company: {company}
- Title: {title}
- Location: {location}
- Department: {department}
- Application URL: {url}
- Why-I-fit summary: {why}
- Key skills required: {skills}

Write the letter now. Output only the letter body (no header, no address block,
no date, no recipient name). The script will prepend the address block.
"""

STRENGTHS_PROMPT = """\
You will rewrite ONLY the three Strengths bullets in {name}'s CV LaTeX
file, tailored to a specific job. Output exactly three lines, each starting with
'\\item' and exactly the same LaTeX markup conventions used below. Do NOT include
the surrounding \\begin{{itemize}} or \\end{{itemize}}. Do NOT add a preamble or a
footer.

Hard rules:
1. NEVER use em-dashes. Use commas, colons, parentheses.
2. Use \\textbf{{...}} for the bullet's lead phrase (the topic), then a colon, then
   one or two specific sentences with concrete numbers.
3. Mirror language from the job description but stay truthful to the candidate
   facts below. If the JD mentions a tool/topic the candidate doesn't have, do
   NOT claim it. Either omit it or say "currently learning" only once.
4. Each bullet must end with a period.
5. Each bullet should be 2-3 lines when rendered (about 35-55 words).

Candidate facts (use these only):
{candidate_facts_short}

Reference template (match the structure exactly):
{reference_bullets}

Job details:
- Company: {company}
- Title: {title}
- Location: {location}
- Department: {department}
- Why I fit (heuristic): {why}
- Skill keywords matched: {skills}

Output: 3 lines, each starting with \\item. Nothing else.
"""


# ---------------------------------------------------------------------------
# CV surgery: replace ONLY the Strengths itemize block, leave everything else
# byte-identical so Overleaf compiles the file unchanged.
# ---------------------------------------------------------------------------
STRENGTHS_BLOCK_RE = re.compile(
    r"(\\section\{Strengths\}.*?\\begin\{itemize\})(.*?)(\\end\{itemize\})",
    re.DOTALL,
)


def patch_strengths(master_text: str, new_items: str) -> str:
    """Replace the body of the itemize inside \\section{Strengths}."""
    def _sub(m):
        return m.group(1) + "\n  " + new_items.strip() + "\n" + m.group(3)
    if not STRENGTHS_BLOCK_RE.search(master_text):
        raise RuntimeError("master.tex Strengths itemize block not found - check template")
    return STRENGTHS_BLOCK_RE.sub(_sub, master_text, count=1)


PHOTO_TOGGLE_RE = re.compile(r"\\photo(true|false)")


def set_photo(master_text: str, country: str) -> str:
    target = "\\photofalse" if country in PHOTO_OFF_COUNTRIES else "\\phototrue"
    return PHOTO_TOGGLE_RE.sub(target, master_text, count=1)


# ---------------------------------------------------------------------------
# Cover-letter shell (address block + signature). Plain text.
# ---------------------------------------------------------------------------
def wrap_cover_letter(body: str, company: str, role_location: str) -> str:
    name = _p("name")
    today = dt.date.today().strftime("%d %B %Y")
    header = (
        f"{name}\n"
        f"{_p('city')}\n"
        f"{_p('email')}  |  {_p('phone')}\n"
        f"\n{today}\n\n"
        f"{company}\n"
        f"{role_location}\n\n"
    )
    # Strip any em-dashes the model might still have produced; replace with comma.
    cleaned = body.replace("\u2014", ",").replace("\u2013", "-")
    # Defensive: ensure our sign-off is present.
    if not cleaned.rstrip().endswith(name):
        cleaned = cleaned.rstrip() + f"\n\nBest regards,\n{name}"
    return header + cleaned + "\n"


# ---------------------------------------------------------------------------
# CSV row marshalling
# ---------------------------------------------------------------------------
def load_csv() -> tuple[list, list]:
    if not os.path.exists(CSV_PATH):
        return [], []
    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def save_csv(headers: list, rows: list) -> None:
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def process_row(row: dict) -> bool:
    """Generate cover letter + CV for one row. Returns True if successful."""
    company = row.get("Company", "Unknown")
    title = row.get("Job Title", "Untitled")
    location = row.get("Location", "")
    department = row.get("Department", "")
    why = row.get("Why I Fit", "")
    skills = row.get("Key Skills Required", "")
    url = row.get("Application Link", "")
    country = row.get("Country", "")

    slug = slugify(f"{company}_{title}")[:80]

    # 1. Cover letter
    cover_prompt = COVER_LETTER_PROMPT.format(
        name=_p("name"),
        cover_letter_rules=_p("cover_letter_rules"),
        candidate_facts=_p("candidate_facts"),
        company=company, title=title, location=location, department=department,
        url=url, why=why, skills=skills,
    )
    body = call_claude(cover_prompt)
    if not body:
        log(f"  [{slug}] cover letter generation failed; skipping")
        return False
    full_letter = wrap_cover_letter(body, company, location)
    cover_path = os.path.join(COVER_DIR, f"{slug}.txt")
    os.makedirs(COVER_DIR, exist_ok=True)
    with open(cover_path, "w", encoding="utf-8") as f:
        f.write(full_letter)
    log(f"  wrote {cover_path}")

    # 2. CV strengths
    strengths_prompt = STRENGTHS_PROMPT.format(
        name=_p("name"),
        candidate_facts_short=_p("candidate_facts_short"),
        reference_bullets=_p("reference_bullets"),
        company=company, title=title, location=location, department=department,
        why=why, skills=skills,
    )
    new_items = call_claude(strengths_prompt)
    if not new_items or "\\item" not in new_items:
        log(f"  [{slug}] Strengths generation failed; skipping CV write")
        return True  # cover letter succeeded; partial OK

    with open(CV_MASTER, "r", encoding="utf-8") as f:
        master = f.read()
    try:
        patched = patch_strengths(master, new_items)
    except RuntimeError as e:
        log(f"  patch failed: {e}")
        return True
    patched = set_photo(patched, country)

    cv_path = os.path.join(CV_OUT_DIR, f"{slug}.tex")
    os.makedirs(CV_OUT_DIR, exist_ok=True)
    with open(cv_path, "w", encoding="utf-8") as f:
        f.write(patched)
    log(f"  wrote {cv_path}")

    return True


def main() -> int:
    global PROFILE
    PROFILE = load_profile()

    p = argparse.ArgumentParser()
    p.add_argument("--row", type=int, default=None,
                   help="0-based row index (excluding header) to process; default = all flagged")
    p.add_argument("--list", action="store_true",
                   help="list pending rows, do nothing")
    args = p.parse_args()

    headers, rows = load_csv()
    if not rows:
        log("no rows in jobs.csv")
        return 1

    pending_idx = []
    if args.row is not None:
        pending_idx = [args.row]
    else:
        for i, r in enumerate(rows):
            flag = (r.get("Generate Artefacts") or "").strip().lower()
            if flag in ("yes", "y", "1", "true", "go"):
                pending_idx.append(i)

    log(f"=== artefact gen: {len(pending_idx)} row(s) to process ===")

    if args.list:
        for i in pending_idx:
            r = rows[i]
            print(f"  row {i}: {r.get('Company')} | {r.get('Job Title')} | {r.get('Location')}")
        return 0

    today = dt.date.today().isoformat()
    for i in pending_idx:
        r = rows[i]
        log(f"-> row {i}: {r.get('Company')} | {r.get('Job Title')}")
        ok = process_row(r)
        if ok:
            r["Generated At"] = today
            r["Generate Artefacts"] = ""
    save_csv(headers, rows)
    log("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
