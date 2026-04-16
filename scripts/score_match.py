"""
Match-scoring logic. Pure functions, no side effects, easy to unit-test.

Score = sum of weighted contributions, capped at 100. Negative if the role is clearly
out of scope (no security signal at all). Returns (score, why_breakdown_string).
"""
import re

# ---------------------------------------------------------------------------
# Keyword tables. Tune these without touching scoring math.
# ---------------------------------------------------------------------------

# Hard requirement: at least one of these must appear in the title or description,
# else the role is outside the security domain and gets score 0.
SECURITY_GATEKEEPER_KEYWORDS = [
    "security", "secur", "cyber", "appsec", "infosec", "devsecops",
    "pentest", "pen test", "penetration test", "red team", "blue team",
    "siem", "soc analyst", "soc engineer", "incident response", "ir engineer",
    "threat", "vulnerability", "exploit", "cryptograph", "crypto engineer",
    "trust and safety", "trust & safety",  "privacy engineer", "abuse",
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

SENIOR_PENALTY_SIGNALS = [
    "principal", "staff ", "director", "head of", "vp ", "lead ",
    "manager", "engineering manager", "senior staff", "architect",
]

# Skill keywords; each match adds 1 point to the skill bucket (capped).
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
    haystack = f"{title_l} | {dept_l} | {body_l}"

    # ---- gatekeeper: security signal must hit TITLE or DEPARTMENT ---------
    # (a body-only mention triggers too many sales / customer-success false positives;
    #  by requiring it in title/dept we exclude e.g. "Digital Solutions Intern" whose
    #  body merely lists "security" as one of many product themes.)
    title_dept = f"{title_l} | {dept_l}"
    sec_hits_strict = _contains_any(title_dept, SECURITY_GATEKEEPER_KEYWORDS)
    if not sec_hits_strict:
        return (0, "No security signal in title/department", [])
    # Use the wider list for downstream scoring nuance.
    sec_hits = _contains_any(haystack, SECURITY_GATEKEEPER_KEYWORDS)

    breakdown = []
    score = 0

    # ---- security domain base ------------------------------------------
    domain_pts = min(20, 12 + 2 * len(sec_hits))   # 14..20
    score += domain_pts
    breakdown.append(f"+{domain_pts} security domain ({len(sec_hits)} kw)")

    # ---- seniority match -----------------------------------------------
    intern_hits = _contains_any(f"{title_l} {type_l}", INTERNSHIP_SIGNALS)
    senior_hits = _contains_any(title_l, SENIOR_PENALTY_SIGNALS)

    if intern_hits:
        score += 30
        breakdown.append(f"+30 intern/early-career match ({intern_hits[0]})")
    elif senior_hits:
        score -= 15
        breakdown.append(f"-15 senior role ({senior_hits[0]}) -- not Youssef's level")
    else:
        # mid-level FT - some value (post-MSc target) but lower for current goal
        score += 8
        breakdown.append("+8 mid-level FT (post-MSc target only)")

    # ---- location ------------------------------------------------------
    loc_score = 0
    loc_reason = ""
    for needle, pts in LOCATION_BOOST.items():
        if needle in loc_l:
            if pts > loc_score:
                loc_score = pts
                loc_reason = needle.strip().title()
    if loc_score:
        score += loc_score
        breakdown.append(f"+{loc_score} location ({loc_reason})")
    else:
        breakdown.append("+0 location (outside priority countries)")

    # ---- skill stack overlap -------------------------------------------
    skill_hits = _contains_any(haystack, USER_SKILLS)
    skill_pts = min(20, 2 * len(skill_hits))
    if skill_pts:
        score += skill_pts
        breakdown.append(f"+{skill_pts} skill stack ({len(skill_hits)} matches)")

    # ---- bonus for Youssef's deep-interest sub-fields ------------------
    deep_interests = ["ai red team", "adversarial", "alignment", "ai safety",
                      "confidential computing", "trusted execution", "enclave",
                      "splunk", "qradar", "applied cryptography"]
    deep_hits = _contains_any(haystack, deep_interests)
    if deep_hits:
        bonus = min(8, 3 * len(deep_hits))
        score += bonus
        breakdown.append(f"+{bonus} deep-interest topic ({deep_hits[0]})")

    # ---- cap and clamp -------------------------------------------------
    score = max(0, min(100, score))
    return (score, "; ".join(breakdown), skill_hits[:8])


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
        ("Application Security Engineer", "Zurich, CH", "Security", "We seek an AppSec engineer with Python, OWASP top 10..."),
        ("Marketing Intern", "London, UK", "Marketing", "Help our brand grow"),
        ("Senior Engineering Manager, Detection and Response", "Zurich, CH", "Security", ""),
        ("Cybersecurity Werkstudent", "Munich, Germany", "InfoSec", "Splunk, SIEM, Python automation"),
    ]
    for t, l, d, b in cases:
        s, why, sk = score_job(t, l, d, b)
        print(f"{s:3d}  {t}  [{l}]  -> {why}  | skills: {sk}")
