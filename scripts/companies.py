"""
Configuration of company job-board endpoints to scrape every 6h.

Each entry maps a company key to:
  - board_type: one of "greenhouse", "ashby", "lever"
  - endpoint:   full URL returning JSON
  - priority:   1 (CH-native) | 2 (DE/EU anchor) | 3 (global, has EU office) | 4 (US-only fallback)

Adding a new company: copy one of the entries below. The scraper auto-handles the
three board types. For Workday / custom portals that aren't scrapeable from a public
JSON endpoint, add them instead to SWISS_DIRECT_APPLY below - those rows get re-seeded
into the CSV as "apply via portal" pointers so you don't forget them.
"""

# Companies whose public JSON API we poll every run
API_COMPANIES = {
    # ----- tier 1: AI safety / security-forward with EU presence -----
    "anthropic":       {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true", "priority": 1},
    "cloudflare":      {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true", "priority": 1},
    "openai":          {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true", "priority": 1},
    "cohere":          {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/cohere?includeCompensation=true", "priority": 2},
    "scaleai":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/scaleai/jobs?content=true", "priority": 2},

    # ----- tier 2: security specialty, hiring globally -----
    "palantir":        {"board_type": "lever",      "endpoint": "https://api.lever.co/v0/postings/palantir?mode=json", "priority": 2},
    "snyk":            {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/snyk?includeCompensation=true", "priority": 2},
    "abnormalsecurity":{"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/abnormalsecurity/jobs?content=true", "priority": 3},
    "expel":           {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/expel/jobs?content=true", "priority": 3},
    "zscaler":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true", "priority": 3},

    # ----- tier 3: big tech with security teams -----
    "stripe":          {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true", "priority": 2},
    "datadog":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true", "priority": 2},
    "figma":           {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true", "priority": 2},
    "databricks":      {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true", "priority": 2},
    "mongodb":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/mongodb/jobs?content=true", "priority": 3},
    "okta":            {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/okta/jobs?content=true", "priority": 3},
    "elastic":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/elastic/jobs?content=true", "priority": 3},

    # ----- tier 4: Swiss / EU specialty security -----
    "dfinity":         {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/dfinity/jobs?content=true", "priority": 1},
    "vanta":           {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/vanta?includeCompensation=true", "priority": 3},
    "drata":           {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/drata?includeCompensation=true", "priority": 3},
    "cursor":          {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/cursor?includeCompensation=true", "priority": 2},

    # ----- fintech with appsec teams (salary upside, EU presence) -----
    "robinhood":       {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true", "priority": 3},
    "coinbase":        {"board_type": "greenhouse", "endpoint": "https://boards-api.greenhouse.io/v1/boards/coinbase/jobs?content=true", "priority": 3},
    "ramp":            {"board_type": "ashby",      "endpoint": "https://api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true", "priority": 3},
}


# Employers whose boards are JS-rendered or behind custom portals.
# Each run, the scraper RE-SEEDS these into the CSV with a stable "apply via portal" note
# (deduped by company+title+location so they don't create spam rows).
# These are ranked by priority for Youssef's Swiss-first goal.
SWISS_DIRECT_APPLY = [
    # company, canonical title, location, portal URL, reason it's worth checking manually
    ("Kudelski Security", "Security Analyst / Consultant intern track", "Cheseaux-sur-Lausanne, CH",
     "https://www.kudelskisecurity.com/about-us/careers/",
     "Lausanne HQ; pure-play cyber consultancy; perfect geographic + domain fit; check portal weekly"),
    ("Proton AG", "Security / Cryptography / Privacy engineering intern", "Geneva, CH",
     "https://proton.me/careers",
     "Geneva HQ; end-to-end encryption shop; privacy-engineering focus"),
    ("Sonar (SonarSource)", "Software / AppSec engineering intern", "Geneva, CH / Annecy, FR / Bochum, DE",
     "https://jobs.lever.co/sonarsource",
     "Geneva HQ; static-analysis / code security vendor; tech-adjacent to thesis track"),
    ("Nexthink", "Security / Software engineering intern", "Lausanne, CH",
     "https://www.nexthink.com/careers",
     "Lausanne HQ; DEX platform with security analytics; walk-to-work for Youssef"),
    ("DFINITY Foundation", "Cryptography / Security research intern", "Zurich, CH",
     "https://dfinity.org/careers",
     "Zurich HQ; applied-crypto heavy; 0 open as of 2026-04-16 but watch the board"),
    ("IBM Research Zurich", "Pre-doctoral research intern (Security & Privacy)", "Rüschlikon, CH",
     "https://www.zurich.ibm.com/careers/",
     "IBM Research lab; world-class applied crypto / system security / confidential computing group"),
    ("Google (Zurich)", "STEP / Student Researcher / SWE Intern (Security)", "Zurich, CH",
     "https://www.google.com/about/careers/applications/",
     "Largest Google eng office in EU; security teams hire interns via student programs"),
    ("Microsoft Research (Cambridge / Zurich satellite)", "Research intern (AI Security / Confidential Computing)", "Zurich, CH / Cambridge, UK / Remote-EU",
     "https://www.microsoft.com/en-us/research/academic-program/internship/",
     "MSR intern programs are application-gated; strong for confidential-computing research"),
    ("Meta (London)", "Security Engineer intern", "London, UK",
     "https://www.metacareers.com/jobs?roles[0]=Intern",
     "London has security-eng interns; UK market = photo off"),
    ("Deepmind", "Research engineer intern (safety/security)", "London, UK",
     "https://deepmind.google/careers/",
     "Safety/security alignment interns; Research engineer track aligns with EPFL focus"),
    ("SAP SE", "Werkstudent Cyber Security / Intern", "Walldorf, DE / Berlin, DE",
     "https://jobs.sap.com/search/?q=cyber+security+intern",
     "Large cyber team; structured Werkstudent + intern pipeline"),
    ("Siemens AG", "Werkstudent Cybersecurity", "Munich, DE / Erlangen, DE",
     "https://jobs.siemens.com/",
     "Industrial cyber / OT security; Werkstudent pipeline for MSc students"),
    ("Infineon Technologies", "Intern HW/SW security", "Munich, DE / Neubiberg, DE",
     "https://www.infineon.com/cms/en/careers/",
     "Hardware security, trusted platform modules, secure elements; MSc fit"),
    ("CrowdStrike (Munich)", "Intern / Graduate security research", "Munich, DE / Remote-EMEA",
     "https://www.crowdstrike.com/careers/",
     "Threat intel + endpoint detection; EMEA Munich HQ; interns via workday"),
    ("Palo Alto Networks (Amsterdam)", "Intern / Working student security", "Amsterdam, NL / Munich, DE",
     "https://www.paloaltonetworks.com/company/careers",
     "Big EMEA security vendor; intern + working student pipeline"),
    ("Darktrace", "Security Analyst / Graduate Threat Analyst", "Cambridge, UK",
     "https://www.darktrace.com/careers",
     "Cambridge HQ; AI-driven detection; graduate pipeline"),
    ("NCC Group", "Graduate Consultant - Security Research / Pentest", "Zurich, CH / Manchester, UK",
     "https://www.nccgroup.com/careers/",
     "Pure-play pentesting + research; well-regarded grad programme"),
    ("ETH CSS (Center for Security Studies)", "Research internship (applied security policy)", "Zurich, CH",
     "https://css.ethz.ch/en/center/internship-program.html",
     "Research internship; 2026 cycle closed but watch 2027"),
    ("CERN openlab", "Summer Student (IT security / Systems)", "Geneva, CH",
     "https://openlab.cern/summer-student-programme",
     "9-week summer program at CERN; June-Aug 2026; high prestige"),
    ("Zurich Insurance Group", "Cyber Security Werkstudent / intern", "Zurich, CH",
     "https://www.zurich.com/careers",
     "Financial-services cyber; Zurich HQ"),
    ("UBS", "Cyber Security Analyst intern", "Zurich, CH / Basel, CH",
     "https://www.ubs.com/global/en/careers.html",
     "Bank cyber; well-paid; Zurich HQ"),
    ("Swiss Re", "Information Security intern", "Zurich, CH",
     "https://www.swissre.com/careers/",
     "Insurance cyber / info-risk; good name recognition in CH"),
]
