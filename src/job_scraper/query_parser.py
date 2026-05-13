"""
Natural language query parser.

Parses free-form queries in Ukrainian / Russian / English and extracts
structured scraper parameters.

Example input:
    "знайди мені 100 компаній які шукають 3D hard-surface artist.
     Шукай виключно remote позиції, у країнах ЄС, США та Канади.
     Відфільтруй за зарплатнею. Максимум двох тиждневої давнини."

Extracted:
    job_title = "3D hard-surface artist"
    count = 100
    remote = True
    locations = ["United States", "Canada", "Poland", "Germany", ...]
    max_age_hours = 336
    salary_filter = True
"""

import re
from dataclasses import dataclass, field


@dataclass
class ParsedQuery:
    """Structured parameters extracted from a natural language query."""
    job_title: str = ""
    count: int = 100
    remote: bool = False
    locations: list[str] = field(default_factory=list)
    max_age_hours: int = 336  # 14 days default
    salary_filter: bool = False
    raw_query: str = ""

    def summary(self) -> str:
        lines = [
            f"  Job title:     {self.job_title}",
            f"  Results:       {self.count}",
            f"  Remote only:   {self.remote}",
            f"  Locations:     {', '.join(self.locations) or 'default'}",
            f"  Max age:       {self.max_age_hours}h ({self.max_age_hours // 24}d)",
            f"  Salary filter: {self.salary_filter}",
        ]
        return "\n".join(lines)


# ─── country sets ───

EU_COUNTRIES = [
    "Poland", "Germany", "France", "Spain", "Sweden",
    "Netherlands", "Italy", "Portugal", "Austria", "Belgium",
    "Czech Republic", "Denmark", "Finland", "Ireland",
    "Romania", "Bulgaria", "Croatia", "Greece", "Hungary",
    "Lithuania", "Latvia", "Estonia", "Slovakia", "Slovenia",
]

COUNTRY_ALIASES = {
    # Ukrainian / Russian / English → canonical name
    "сша": "United States", "usa": "United States", "us": "United States",
    "америк": "United States", "america": "United States",
    "united states": "United States", "штат": "United States",
    "канад": "Canada", "canada": "Canada",
    "uk": "United Kingdom", "британ": "United Kingdom",
    "англ": "United Kingdom", "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "польщ": "Poland", "польш": "Poland", "poland": "Poland",
    "німеч": "Germany", "герман": "Germany", "germany": "Germany",
    "франц": "France", "france": "France",
    "іспан": "Spain", "испан": "Spain", "spain": "Spain",
    "швец": "Sweden", "швед": "Sweden", "sweden": "Sweden",
    "нідерланд": "Netherlands", "нидерланд": "Netherlands",
    "голланд": "Netherlands", "netherlands": "Netherlands",
    "італ": "Italy", "итал": "Italy", "italy": "Italy",
    "португал": "Portugal", "portugal": "Portugal",
    "австр": "Austria", "austria": "Austria",
    "бельг": "Belgium", "belgium": "Belgium",
    "чех": "Czech Republic", "czech": "Czech Republic",
    "дан": "Denmark", "denmark": "Denmark",
    "фінлянд": "Finland", "финлянд": "Finland", "finland": "Finland",
    "ірланд": "Ireland", "ирланд": "Ireland", "ireland": "Ireland",
    "латв": "Latvia", "latvia": "Latvia",
}


def _extract_count(text: str) -> int:
    """Extract the desired number of results."""
    patterns = [
        r"(\d+)\s*(?:компан|вакан|позиц|job|compan|position|result|offer|listing)",
        r"(?:знайд|найд|find|get|show|search)\D{0,20}(\d+)",
        r"(?:топ|top)\s*[-–]?\s*(\d+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 10000:
                return n
    return 100


def _extract_job_title(text: str) -> str:
    """Extract the job title from the query."""
    # Noise words to strip from extracted titles
    noise = (
        r"\b(remote|віддален|удалён|удален|шукай|знайд|найд|мені|мне|"
        r"позиці[їі]|вакансі[їій]|компані[їій]|jobs?|positions?|companies|"
        r"країн|у\s+країн|в\s+стран|in\s+countr|maximum|максимум|"
        r"також|also|надай|надаю|provide|за\s+останн|last|"
        r"\d+\s*тижн|\d+\s*днів|\d+\s*дней|\d+\s*days|\d+\s*weeks?)\b"
    )

    patterns = [
        # "шукають 3D hard-surface artist"
        r"(?:шукають|шукає|шукати|ищут|ищет)\s+(.+?)(?:\.|,|надай|надаю|шукай|\n|$)",
        # "looking for product manager" (must be before "find")
        r"(?:looking for|search(?:ing)? for)\s+(.+?)(?:\.|,|provide|\n|$)",
        # "find 200 companies looking for X"
        r"(?:find|get|show)\s+\d+\s+\S+\s+looking\s+for\s+(.+?)(?:\.|,|provide|\n|$)",
        # "find product manager"
        r"(?:find|get|show)\s+(?!\d)(.+?)(?:\.|,|provide|in\s|\n|$)",
        # "вакансій 3D artist" / "вакансій python developer, remote"
        r"(?:вакансі[їій]|позиці[їій]|jobs?|positions?)\s+(.+?)(?:\.|,\s*(?:remote|віддален|удалён|шукай|країн|в\s)|\n|$)",
        # "знайди мені 100 компаній які шукають X" (flexible word count)
        r"(?:знайд[иі]|найд[иі]).+?(?:шукають|шукає|ищут)\s+(.+?)(?:\.|,|надай|надаю|шукай|\n|$)",
        # "знайди 10 вакансій X" (number + noun + title)
        r"(?:знайд[иі]|найд[иі])\s+\d+\s+\S+\s+(.+?)(?:\.|,\s*(?:remote|віддален|удалён|шукай|країн|у\s)|\n|$)",
        # "найди 50 вакансий X" (Russian)
        r"(?:найд[иі]|найти)\s+\d+\s+\S+\s+(.+?)(?:\.|,\s*(?:remote|удалён|страна|в\s)|\n|$)",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            title = m.group(1).strip()
            # Clean noise words from title
            title = re.sub(noise, "", title, flags=re.I)
            title = re.sub(r"\s+", " ", title).strip(" .,;:–—-")
            if len(title) > 2:
                return title

    # Fallback: look for quoted text
    m = re.search(r'"([^"]+)"', text)
    if m:
        return m.group(1)

    # Fallback: look for known job-title-like patterns
    m = re.search(r"\b(\d?D[\s\-]?\w[\w\s\-]{3,30}(?:artist|designer|modeler|animator|developer))", text, re.I)
    if m:
        return m.group(1).strip()

    # Fallback: look for "word word" patterns that look like job titles
    m = re.search(r"\b([a-zA-Z][\w\s\-]{2,25}(?:artist|designer|developer|engineer|manager|analyst|specialist|consultant))\b", text, re.I)
    if m:
        return m.group(1).strip()

    return ""


def _extract_remote(text: str) -> bool:
    """Check if remote-only is requested."""
    t = text.lower()
    # English words with word boundaries
    if re.search(r"\b(remote|remotely|wfh|work\s+from\s+home)\b", t):
        return True
    # Cyrillic substrings (word boundaries don't work well with Unicode)
    cyrillic_markers = ["віддален", "удалён", "удален", "дистанц"]
    return any(m in t for m in cyrillic_markers)


def _extract_locations(text: str) -> list[str]:
    """Extract target countries/locations."""
    locations: set[str] = set()
    t = text.lower()

    # Check for EU mention
    if re.search(r"\b(єс|ес|eu|євросоюз|евросоюз|europe|європ)\b", t, re.I):
        locations.update(EU_COUNTRIES)

    # Check for specific countries
    for alias, canonical in COUNTRY_ALIASES.items():
        if alias in t:
            locations.add(canonical)

    return sorted(locations)


def _extract_max_age(text: str) -> int:
    """Extract max job age in hours."""
    t = text.lower()

    # "X дней/днів/days"
    m = re.search(r"(\d+)\s*(?:дн[ейів]|день|day|дня)", t)
    if m:
        return int(m.group(1)) * 24

    # "X тижн/недел/week"
    m = re.search(r"(\d+)\s*(?:тижн|неділ|недел|week)", t)
    if m:
        return int(m.group(1)) * 24 * 7

    # "двох/двух тижн" (Ukrainian/Russian "two weeks")
    if re.search(r"(дво?х?|двух?)\s*тижн", t):
        return 14 * 24
    if re.search(r"(дво?х?|двух?)\s*недел", t):
        return 14 * 24

    # "X місяц/месяц/month"
    m = re.search(r"(\d+)\s*(?:місяц|месяц|month)", t)
    if m:
        return int(m.group(1)) * 24 * 30

    return 336  # default 14 days


def _extract_salary_filter(text: str) -> bool:
    """Check if salary filtering is requested."""
    return bool(re.search(
        r"(зарплат|salary|оплат|компенсац|pay|wage|€|\$|£|грн|usd|eur)",
        text, re.I,
    ))


def parse_query(raw: str) -> ParsedQuery:
    """Parse a natural language query into structured scraper parameters."""
    return ParsedQuery(
        job_title=_extract_job_title(raw),
        count=_extract_count(raw),
        remote=_extract_remote(raw),
        locations=_extract_locations(raw),
        max_age_hours=_extract_max_age(raw),
        salary_filter=_extract_salary_filter(raw),
        raw_query=raw,
    )
