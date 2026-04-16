# autoapply for automated job apply

Automated job discovery and application-artefact generator for targeted internship and early-career searches. Scrapes public job boards (Greenhouse, Ashby, Lever) every 6 hours, scores each posting against your profile, and generates tailored cover letters and CVs on demand using Claude.

## Features

- **Multi-board scraper** — pulls from Greenhouse, Ashby, and Lever JSON APIs in one pass
- **Configurable scoring** — 0-100 match score based on domain fit, seniority, location priority, and skill overlap
- **Manual portal tracking** — seeds rows for JS-rendered career pages (Workday, iCIMS, SuccessFactors) so you don't forget to check them
- **Cover letter generator** — calls Claude to produce a concrete, non-generic cover letter per role
- **CV tailoring** — swaps the "Strengths" section of your LaTeX CV to match each job description, toggles photo on/off based on country norms
- **Append-only CSV** — deduped on `(company, title, location)`; safe to edit in Excel/LibreOffice between runs
- **Cron-ready** — ships with a lockfile-guarded shell wrapper for unattended operation

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/<you>/jobQuery.git
cd jobQuery
```

### 2. Edit your profile

Open `scripts/score_match.py` and customise:

| Section | What to change |
|---|---|
| `SECURITY_GATEKEEPER_KEYWORDS` | Domain keywords that a role **must** match (title or department) to be considered |
| `INTERNSHIP_SIGNALS` | Title-level seniority signals (intern, graduate, etc.) |
| `USER_SKILLS` | Your technical skills — each match adds to the score |
| `LOCATION_BOOST` | Country/city priority map with point values |
| Deep-interest topics | Sub-fields you care most about (bonus points) |

### 3. Add your target companies

Edit `scripts/companies.py`:

- **`API_COMPANIES`** — for employers using Greenhouse, Ashby, or Lever:
  ```python
  "stripe": {
      "board_type": "greenhouse",
      "endpoint": "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true",
      "priority": 2,
  },
  ```
- **`SWISS_DIRECT_APPLY`** (or rename to `DIRECT_APPLY`) — for JS-rendered portals you must visit manually. These get re-seeded into the CSV each run as reminder rows.

### 4. Prepare your CV template

Place your LaTeX CV at `cv_latex/templates/master.tex`. The generator looks for a `\section{Strengths}` block containing an `\begin{itemize}...\end{itemize}` — it replaces only those bullets. If your CV uses a photo toggle (`\phototrue` / `\photofalse`), it will be set automatically based on country norms.

### 5. Run the scraper

```bash
python3 scripts/scrape_jobs.py
```

This creates `jobs.csv` with all matching roles scored and sorted.

### 6. Set up cron (optional)

```bash
chmod +x scripts/run_scraper.sh
crontab -e
# Add:
0 */6 * * * /path/to/jobQuery/scripts/run_scraper.sh
```

### 7. Generate application artefacts

1. Open `jobs.csv` in Excel / LibreOffice
2. Sort by `Match Score` descending
3. Set the `Generate Artefacts` column to `yes` for roles you want to apply to
4. Run:
   ```bash
   python3 scripts/generate_artefacts.py
   ```
5. Find your outputs in `cover_letters/` and `cv_latex/generated/`

The generator requires [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

## CSV columns

| Column | Filled by | Purpose |
|---|---|---|
| `Match Score` | scraper | 0-100 fit score |
| `Why I Fit` | scraper | scoring breakdown |
| `CV Feedback / Edits Needed` | scraper | heuristic hint on which bullet to lead with |
| `Applied` | **you** | put `YYYY-MM-DD` once you submit |
| `Generate Artefacts` | **you** | set to `yes` before running `generate_artefacts.py` |
| `Generated At` | generator | timestamp when artefacts were created |
| `Notes` | **you** | scratch column |

## Project structure

```
jobQuery/
├── jobs.csv                       # master spreadsheet (gitignored, generated)
├── scripts/
│   ├── companies.py               # endpoints + priorities
│   ├── score_match.py             # scoring logic (customise this)
│   ├── scrape_jobs.py             # main scraper
│   ├── generate_artefacts.py      # cover letter + CV generator (calls Claude)
│   └── run_scraper.sh             # cron entrypoint with flock lock
├── cover_letters/                 # generated cover letters (gitignored)
├── cv_latex/
│   ├── templates/
│   │   └── master.tex             # your CV template (gitignored)
│   └── generated/                 # per-role tailored CVs (gitignored)
└── logs/                          # runtime logs (gitignored)
```

## Customising for your field

This repo ships configured for cybersecurity internships, but you can adapt it to any domain:

1. Replace `SECURITY_GATEKEEPER_KEYWORDS` with your field's keywords (e.g., "machine learning", "data engineer", "product manager")
2. Adjust `INTERNSHIP_SIGNALS` if you're targeting full-time roles instead
3. Rewrite `LOCATION_BOOST` for your geographic preferences
4. Update the candidate facts in `generate_artefacts.py` prompts with your own background
5. Swap the LaTeX CV template for your own

## Commands

```bash
# Scrape all companies and append new rows
python3 scripts/scrape_jobs.py

# Rebuild from scratch (backs up existing CSV first)
python3 scripts/scrape_jobs.py --rebuild

# List rows pending artefact generation
python3 scripts/generate_artefacts.py --list

# Generate artefacts for all flagged rows
python3 scripts/generate_artefacts.py

# Generate artefacts for a specific row (0-based index)
python3 scripts/generate_artefacts.py --row 17
```

## Requirements

- Python 3.8+ (stdlib only, no pip dependencies)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (for artefact generation)
- `flock` (for cron lockfile; available on Linux by default)

## License

MIT
