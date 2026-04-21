"""
Match-scoring logic. Pure functions, no side effects, easy to unit-test.

Score = sum of weighted contributions, capped at 100. Returns (score, why, key_skills).

Precision model:
  - Security signal is weighted by WHERE it appears (title > department > body).
  - Seniority is gradient-scored, not binary. Intern/graduate roles get a strong
    positive, senior/principal/manager roles get a scaled negative, with intern
    signals taking priority if both appear.
  - Years-of-experience floor in the job description drives a targeted penalty
    unless the role is explicitly an internship.
  - Skill, location, and deep-interest bonuses layer on top with soft caps.
"""
import re

# ---------------------------------------------------------------------------
# Keyword tables. Tune these without touching scoring math.
# ---------------------------------------------------------------------------

# Hard requirement: at least one of these must appear in the title or department,
# else the role is outside the security domain and gets score 0.
SECURITY_GATEKEEPER_KEYWORDS = [
    "security", "secur", "cyber", "appsec", "infosec", "devsecops",
    "pentest", "pen test", "penetration test", "red team", "blue team",
    "siem", "soc analyst", "soc engineer", "incident response", "ir engineer",
    "threat", "vulnerability", "exploit", "cryptograph", "crypto engineer",
    "trust and safety", "trust & safety", "privacy engineer", "abuse",
    "detection", "forensic", "reverse engineer", "malware", "fraud engineer",
    "ai red team", "alignment", "adversarial", "ai safety",
    "confidential computing", "trusted execution", "tee ", "enclave",
    "fortinet", "cisco security", "splunk", "qradar",
]

# Title-level seniority signals (tested on title + employment_type).
INTERNSHIP_SIGNALS = [
    "intern", "internship", "trainee", "graduate", "new grad", "new-grad",
    "early career", "early-career", "early talent",
    "working student", "werkstudent", "student researcher",
    "phd intern", "research intern", "summer", "step",
    "residency", "résidency", "rotation",
]

# Gradient penalty table — ordered from heaviest to lightest.
# Each key is a substring checked against the title. Larger penalty = more senior.
SENIOR_PENALTY_TABLE = [
    ("principal",          40),
    ("distinguished",      40),
    ("vp ",                40),
    ("director",           35),
    ("head of",            35),
    ("senior staff",       35),
    ("staff engineer",     30),
    ("staff ",             28),
    ("architect",          25),
    ("engineering manager",25),
    ("manager",            22),
    ("lead ",              18),
    ("senior ",            15),
    ("sr ",                12),
    ("sr.",                12),
]

# Skill keywords; each match adds to the skill bucket (capped).
USER_SKILLS = [
    "python", "c++", "c/c++", "bash", "linux", "git", "docker",
    "splunk", "qradar", "siem", "wireshark", "burp", "nmap",
    "owasp", "fortinet", "fortigate", "cisco",
    "ci/cd", "devsecops", "static analysis", "sast", "dast",
    "kubernetes", "aws", "gcp", "azure",
    "penetration test", "vulnerability assessment", "threat model",
    "reverse engineering", "binary", "exploit", "cve",
    "tls", "pki", "cryptography", "applied cryptography",
    "llm", "prompt injection", "jailbreak", "adversarial ml",
    "confidential computing", "tee", "sgx", "tdx",
]

# Country -> score boost (Youssef's geographic priority list).
LOCATION_BOOST = {
    # Switzerland
    "switzerland": 30, "zurich": 30, "lausanne": 30, "geneva": 30,
    "basel": 28, "bern": 28, " ch": 30, ", ch": 30,
    # Germany
    "germany": 22, "berlin": 22, "munich": 22, "münchen": 22, "frankfurt": 22,
    "hamburg": 20, "stuttgart": 20, "walldorf": 20, "erlangen": 20, ", de": 22,
    # Adjacent EU + UK
    "france": 16, "paris": 16, "ile-de-france": 14,
    "ireland": 16, "dublin": 16,
    "netherlands": 15, "amsterdam": 15,
    "united kingdom": 15, "london": 15, "uk": 15, "england": 15,
    "spain": 13, "barcelona": 13, "madrid": 13,
    "italy": 12, "milan": 12,
    "sweden": 12, "stockholm": 12,
    "portugal": 11, "lisbon": 11,
    # USA
    "united states": 8, "usa": 8, "us ": 8, "remote - us": 8,
    "san francisco": 8, "new york": 8, "seattle": 8, "remote-friendly": 9,
    # Gulf
    "saudi arabia": 5, "riyadh": 5, "dubai": 5, "uae": 5, "abu dhabi": 5,
    # Remote (catch-all, mid)
    "remote": 10,
}


def _normalise(text: str) -> str:
    return (text or "").lower()


def _contains_any(text: str, needles: list) -> list:
    """Return the subset of `needles` that occur in `text` (already lowercased)."""
    return [n for n in needles if n in text]


# ---------------------------------------------------------------------------
# Years of experience extraction
# ---------------------------------------------------------------------------
_YOE_PATTERNS = [
    re.compile(r'(\d{1,2})\s*\+\s*years?'),
    re.compile(r'minimum\s+(?:of\s+)?(\d{1,2})\s*years?'),
    re.compile(r'at\s+least\s+(\d{1,2})\s*years?'),
    re.compile(r'(\d{1,2})\s*-\s*\d{1,2}\s+years?'),
    re.compile(r'(\d{1,2})\s+to\s+\d{1,2}\s+years?'),
    re.compile(r'(\d{1,2})\s*yrs?\s+of\s+experience'),
]


def extract_min_yoe(text: str) -> int | None:
    """
    Return the smallest minimum-years-of-experience number mentioned in the text,
    or None if no such requirement is found. Ignores values <= 0 or > 20.
    """
    if not text:
        return None
    text = text.lower()
    lowest = None
    for pat in _YOE_PATTERNS:
        for m in pat.finditer(text):
            try:
                val = int(m.group(1))
            except ValueError:
                continue
            if 1 <= val <= 20:
                if lowest is None or val < lowest:
                    lowest = val
    return lowest


def _seniority_penalty(title_l: str) -> tuple:
    """Return (penalty_points, label) for the heaviest senior signal in the title."""
    for needle, penalty in SENIOR_PENALTY_TABLE:
        if needle in title_l:
            return (penalty, needle.strip())
    return (0, "")


def score_job(title: str, location: str, department: str, body: str = "",
              employment_type: str = "") -> tuple:
    """
    Return (match_score:int 0-100, why_string, key_skills_matched_list).

    Pure function. Does not raise; on missing fields, treats them as empty.
    """
    title_l = _normalise(title)
    loc_l = _normalise(location)
    dept_l = _normalise(department)
    body_l = _normalise(body)
    type_l = _normalise(employment_type)

    # ---- gatekeeper: security signal must hit TITLE or DEPARTMENT ---------
    sec_hits_title = _contains_any(title_l, SECURITY_GATEKEEPER_KEYWORDS)
    sec_hits_dept = _contains_any(dept_l, SECURITY_GATEKEEPER_KEYWORDS)
    sec_hits_body = _contains_any(body_l, SECURITY_GATEKEEPER_KEYWORDS)

    if not sec_hits_title and not sec_hits_dept:
        return (0, "No security signal in title/department", [])

    breakdown = []
    score = 0

    # ---- security domain (position-weighted) --------------------------------
    if sec_hits_title:
        pts = min(22, 14 + 2 * len(sec_hits_title))
        score += pts
        breakdown.append(f"+{pts} security in title ({sec_hits_title[0]})")
    elif sec_hits_dept:
        pts = min(16, 10 + 2 * len(sec_hits_dept))
        score += pts
        breakdown.append(f"+{pts} security in dept ({sec_hits_dept[0]})")
    if sec_hits_body:
        body_pts = min(6, len(sec_hits_body))
        score += body_pts
        breakdown.append(f"+{body_pts} security density in body ({len(sec_hits_body)} kw)")

    # ---- seniority gradient (intern wins over senior if both are present) ---
    intern_hits = _contains_any(f"{title_l} {type_l}", INTERNSHIP_SIGNALS)
    senior_pts, senior_label = _seniority_penalty(title_l)

    if intern_hits:
        score += 32
        breakdown.append(f"+32 intern/early-career match ({intern_hits[0]})")
    elif senior_pts:
        score -= senior_pts
        breakdown.append(f"-{senior_pts} senior signal ({senior_label}) -- not intern level")
    else:
        # Untagged FT - small positive for post-MSc target
        score += 6
        breakdown.append("+6 mid-level FT (post-MSc target only)")

    # ---- years-of-experience filter ---------------------------------------
    yoe_req = extract_min_yoe(body_l) if not intern_hits else None
    if yoe_req is not None:
        if yoe_req >= 6:
            score -= 45
            breakdown.append(f"-45 requires {yoe_req}+ YOE (far beyond intern level)")
        elif yoe_req >= 4:
            score -= 30
            breakdown.append(f"-30 requires {yoe_req}+ YOE (above intern level)")
        elif yoe_req >= 3:
            score -= 18
            breakdown.append(f"-18 requires {yoe_req}+ YOE (borderline for intern)")
        elif yoe_req >= 2:
            score -= 8
            breakdown.append(f"-8 requires {yoe_req}+ YOE (stretch for intern)")

    # ---- location ---------------------------------------------------------
    loc_score = 0
    loc_reason = ""
    for needle, pts in LOCATION_BOOST.items():
        if needle in loc_l and pts > loc_score:
            loc_score = pts
            loc_reason = needle.strip().title()
    if loc_score:
        score += loc_score
        breakdown.append(f"+{loc_score} location ({loc_reason})")
    else:
        breakdown.append("+0 location (outside priority countries)")

    # ---- skill stack overlap (title-weighted) -----------------------------
    skill_hits_title = _contains_any(title_l, USER_SKILLS)
    skill_hits_body = _contains_any(body_l, USER_SKILLS)
    # Combine, dedupe, then score: title hits are worth more.
    unique_hits = list(dict.fromkeys(skill_hits_title + skill_hits_body))
    skill_pts = min(20, 3 * len(skill_hits_title) + 2 * (len(skill_hits_body) - len(skill_hits_title)))
    skill_pts = max(0, skill_pts)
    if skill_pts:
        score += skill_pts
        breakdown.append(f"+{skill_pts} skill stack ({len(unique_hits)} matches)")

    # ---- bonus for deep-interest sub-fields -------------------------------
    deep_interests = ["ai red team", "adversarial", "alignment", "ai safety",
                      "confidential computing", "trusted execution", "enclave",
                      "splunk", "qradar", "applied cryptography"]
    haystack = f"{title_l} | {dept_l} | {body_l}"
    deep_hits = _contains_any(haystack, deep_interests)
    if deep_hits:
        bonus = min(8, 3 * len(deep_hits))
        score += bonus
        breakdown.append(f"+{bonus} deep-interest topic ({deep_hits[0]})")

    # ---- cap and clamp ----------------------------------------------------
    score = max(0, min(100, score))
    return (score, "; ".join(breakdown), unique_hits[:8])


def classify_country(location: str) -> str:
    """Best-effort country classification for grouping in the CSV."""
    loc_l = _normalise(location)
    rules = [
        (["switzerland", "zurich", "lausanne", "geneva", "basel", "bern", " ch", ", ch"], "Switzerland"),
        (["germany", "berlin", "munich", "münchen", "frankfurt", "hamburg", "walldorf", ", de"], "Germany"),
        (["united kingdom", "london", " uk", ", uk", "england", "cambridge"], "United Kingdom"),
        (["ireland", "dublin"], "Ireland"),
        (["france", "paris"], "France"),
        (["netherlands", "amsterdam"], "Netherlands"),
        (["spain", "barcelona", "madrid"], "Spain"),
        (["italy", "milan"], "Italy"),
        (["portugal", "lisbon"], "Portugal"),
        (["sweden", "stockholm"], "Sweden"),
        (["united states", "usa", " us ", "u.s.", "san francisco", "new york", "seattle", "austin"], "USA"),
        (["saudi", "riyadh"], "Saudi Arabia"),
        (["uae", "dubai", "abu dhabi"], "UAE"),
        (["canada", "toronto", "vancouver"], "Canada"),
        (["singapore"], "Singapore"),
        (["india", "bangalore", "bengaluru"], "India"),
    ]
    for needles, country in rules:
        for n in needles:
            if n in loc_l:
                return country
    if "remote" in loc_l:
        return "Remote"
    return "Other"


def classify_work_mode(location: str, body: str = "") -> str:
    text = _normalise(f"{location} {body}")
    if "remote" in text and "hybrid" not in text:
        return "Remote"
    if "hybrid" in text:
        return "Hybrid"
    return "On-site"


if __name__ == "__main__":
    # quick smoke test
    cases = [
        ("Application Security Engineer", "Zurich, CH", "Security",
         "We seek an AppSec engineer with 5+ years of Python, OWASP top 10..."),
        ("Security Engineer Intern", "Zurich, CH", "Security",
         "We seek an intern with Python, OWASP top 10..."),
        ("Senior Security Engineer", "Zurich, CH", "Security",
         "minimum 7 years of experience in SIEM and cloud security"),
        ("Marketing Intern", "London, UK", "Marketing", "Help our brand grow"),
        ("Cybersecurity Werkstudent", "Munich, Germany", "InfoSec",
         "Splunk, SIEM, Python automation; at least 1 year experience"),
        ("Principal Security Architect", "London, UK", "Security",
         "10+ years of experience required"),
    ]
    for t, l, d, b in cases:
        s, why, sk = score_job(t, l, d, b)
        print(f"{s:3d}  {t:45s}  [{l}]  -> {why}")
