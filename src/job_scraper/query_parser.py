"""
Natural language query parser.

Uses OpenAI (primary) or regex+transliteration (fallback) to parse free-form
queries in Ukrainian / Russian / English and extract structured scraper parameters.

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

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    workers: int = 3

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
    "Czechia", "Denmark", "Finland", "Ireland",
    "Romania", "Bulgaria", "Croatia", "Greece", "Hungary",
    "Lithuania", "Latvia", "Estonia", "Slovakia", "Slovenia",
]

COUNTRY_ALIASES = {
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

# ─── Cyrillic tech term → English translation ───

CYRILLIC_TECH_MAP = {
    # Languages & frameworks
    "пайтон": "python", "питон": "python",
    "джава": "java", "жава": "java",
    "реакт": "react", "ангуляр": "angular", "вью": "vue",
    "ноде": "node", "нод": "node",
    "тайпскрипт": "typescript", "джаваскрипт": "javascript",
    "котлін": "kotlin", "котлин": "kotlin",
    "свіфт": "swift", "свифт": "swift",
    "рубі": "ruby", "руби": "ruby",
    "сі шарп": "C#", "сишарп": "C#",
    "плюси": "C++", "плюсы": "C++",
    "флаттер": "flutter", "дарт": "dart",
    "джанго": "django", "фласк": "flask", "фастапі": "fastapi", "фастапи": "fastapi",
    "спрінг": "spring", "спринг": "spring",
    # Roles
    "бекенд": "backend", "бэкенд": "backend", "бекэнд": "backend",
    "фронтенд": "frontend", "фронтэнд": "frontend",
    "фулстек": "fullstack", "фулстак": "fullstack", "фул стек": "fullstack",
    "девелопер": "developer", "розробник": "developer", "разработчик": "developer",
    "інженер": "engineer", "инженер": "engineer",
    "програміст": "developer", "программист": "developer",
    "дизайнер": "designer",
    "аналітик": "analyst", "аналитик": "analyst",
    "менеджер": "manager",
    "архітект": "architect", "архитект": "architect",
    "тестувальник": "QA engineer", "тестировщик": "QA engineer",
    "девопс": "devops",
    "адміністратор": "administrator", "администратор": "administrator",
    "художник": "artist", "моделер": "modeler",
    "аніматор": "animator", "аниматор": "animator",
    "ілюстратор": "illustrator", "иллюстратор": "illustrator",
    # Levels
    "сіньйор": "senior", "синьор": "senior", "старший": "senior", "сеньор": "senior",
    "джуніор": "junior", "джуниор": "junior", "младший": "junior", "джун": "junior",
    "мідл": "middle", "мидл": "middle", "середній": "middle",
    "лід": "lead", "лид": "lead", "тімлід": "team lead", "тимлид": "team lead",
    # Domains - Tech
    "дата сайнтіст": "data scientist", "датасайнтист": "data scientist",
    "дата інженер": "data engineer", "дата инженер": "data engineer",
    "машинне навчання": "machine learning", "машинное обучение": "machine learning",
    "штучний інтелект": "artificial intelligence",
    "веб": "web", "мобільний": "mobile", "мобильный": "mobile",
    "безпека": "security", "безопасність": "security", "безопасность": "security",
    "хмарн": "cloud", "облачн": "cloud",
    # Marketing / SMM / Content
    "маркетинг": "marketing", "маркетолог": "marketing",
    "смм": "smm", "соцмережі": "social media", "соцсети": "social media",
    "контент": "content", "копірайт": "copywriter", "копирайт": "copywriter",
    "сео": "seo", "реклам": "ads", "таргет": "targeting",
    "бренд": "brand", "піар": "pr", "пиар": "pr",
    # Sales / Business
    "продажі": "sales", "продажи": "sales", "продавець": "sales",
    "менеджер з продажу": "sales manager",
    "бізнес": "business", "бизнес": "business",
    "партнерств": "partnerships", "клієнт": "client", "клиент": "client",
    "підтримка": "support", "поддержка": "support",
    # HR / People
    "рекрутер": "recruiter", "рекрутинг": "recruitment",
    "ейчар": "hr", "кадри": "hr",
    # Finance / Legal
    "фінанс": "financ", "финанс": "financ",
    "бухгалтер": "accountant", "юрист": "legal",
    "аудитор": "auditor",
    # Operations
    "логістик": "logistic", "логистик": "logistic",
    "закупівл": "procurement", "закупк": "procurement",
}

# Words to strip when extracting job title (command/filler words)
_STRIP_COMMAND_WORDS = re.compile(
    r"\b(?:"
    r"найди|найді|найти|знайди|знайді|покажи|покажі|шукай|шукати|"
    r"find|get|show|search|looking|for|"
    r"мне|мені|мою|мій|нам|my|me|please|пожалуйста|будь[ -]ласка"
    r")\b",
    re.I | re.UNICODE,
)

_STRIP_COUNT_WORDS = re.compile(
    r"\b(?:"
    r"вакансі\w*|вакансий|вакансии|позиці\w*|позиций|позиции|"
    r"компані\w*|компаний|компании|"
    r"jobs?|positions?|companies|results?|listings?|offers?|openings?"
    r")\b",
    re.I | re.UNICODE,
)


def _transliterate_tech_terms(text: str) -> str:
    """Translate Cyrillic tech terms to English equivalents."""
    result = text.lower()
    # Sort by length descending so multi-word matches go first
    for cyrillic, english in sorted(CYRILLIC_TECH_MAP.items(), key=lambda x: -len(x[0])):
        result = result.replace(cyrillic, english)
    # Clean up double spaces
    result = re.sub(r"\s+", " ", result).strip()
    return result


# ═══════════════════════════════════════════════════════
#  AI-POWERED QUERY PARSER (primary)
# ═══════════════════════════════════════════════════════

def _ai_parse_query(raw: str) -> ParsedQuery | None:
    """
    Use OpenAI structured output to parse the user query.
    Returns ParsedQuery on success, None on failure (triggers regex fallback).
    """
    try:
        from openai import OpenAI
        from pydantic import BaseModel, Field
        from job_scraper import config
    except ImportError:
        return None

    if not config.OPENAI_API_KEY or not config.ENABLE_AI_QUERY_PARSING:
        return None

    class ParsedQueryAI(BaseModel):
        job_title: str = Field(
            description=(
                "The exact job title/role being searched for, IN ENGLISH. "
                "Translate from Ukrainian/Russian if needed (e.g. 'пайтон бекенд' → 'Python backend developer'). "
                "Keep technical terms like '3D', 'UI/UX', 'C++' exactly. "
                "Return empty string if no specific title is mentioned."
            )
        )
        count: int = Field(
            description="Number of results wanted. Parse written numbers. Default 100."
        )
        remote: bool = Field(
            description="True if user wants remote/WFH/віддалена/удалённая positions."
        )
        locations: list[str] = Field(
            description=(
                "Countries to search in (English canonical names). "
                "If 'EU'/'ЄС'/'Europe' mentioned, expand to: "
                + ", ".join(EU_COUNTRIES) + ". "
                "Use 'United States' not 'USA', 'United Kingdom' not 'UK'. "
                "Empty list if no location specified."
            )
        )
        max_age_hours: int = Field(
            description="Max job age in hours. days×24, weeks×168, months×720. Default 336."
        )
        salary_filter: bool = Field(
            description="True if user mentions salary/зарплата filtering."
        )

    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.beta.chat.completions.parse(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a query parser for a job scraping tool. "
                        "Extract structured search parameters from the user's message "
                        "(Ukrainian, Russian, or English). "
                        "ALWAYS translate job titles to English for search engines. "
                        "When 'EU'/'ЄС' is mentioned, expand to all EU countries."
                    ),
                },
                {"role": "user", "content": raw},
            ],
            response_format=ParsedQueryAI,
            temperature=0.0,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            return None

        return ParsedQuery(
            job_title=parsed.job_title,
            count=max(1, min(10000, parsed.count)),
            remote=parsed.remote,
            locations=sorted(set(parsed.locations)),
            max_age_hours=max(1, parsed.max_age_hours),
            salary_filter=parsed.salary_filter,
            raw_query=raw,
        )
    except Exception as e:
        logger.warning(f"AI query parsing failed, falling back to regex: {e}")
        return None


# ═══════════════════════════════════════════════════════
#  REGEX-BASED PARSER (fallback)
# ═══════════════════════════════════════════════════════

def _extract_count(text: str) -> int:
    """Extract the desired number of results."""
    text_lower = text.lower()
    mapping = {
        "тисячу": 1000, "тисячі": 2000, "тысячу": 1000, "тысячи": 2000, "thousand": 1000,
        "сотню": 100, "сотні": 200, "сотня": 100, "hundred": 100,
        "п'ятсот": 500, "пятьсот": 500, "пятьдесят": 50, "п'ятдесят": 50,
        "десяток": 10, "десять": 10,
    }
    for k, v in mapping.items():
        if k in text_lower:
            return v

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

    m = re.search(
        r"\b(\d+)\b(?!\s*(?:тижн|днів|дней|день|дня|day|week|hour|год|місяц|месяц|month))",
        text, re.I,
    )
    if m:
        n = int(m.group(1))
        if 5 <= n <= 10000:
            return n
    return 100


def _extract_job_title(text: str) -> str:
    """
    Extract the job title from the query.
    
    Strategy:
      1. Try pattern-matching for structured queries
      2. Fall back to "stripping" approach — remove known command/filler words,
         numbers, and count nouns, whatever remains is the title
      3. Transliterate any Cyrillic tech terms to English
    """
    # ── Pattern matching (for structured queries) ──
    noise = (
        r"\b(remote|віддален\w*|удалён\w*|удален\w*|шукай|знайд\w*|найд\w*|мені|мне|"
        r"позиці\w*|вакансі\w*|компані\w*|jobs?|positions?|companies|"
        r"країн\w*|у\s+країн|в\s+стран|in\s+countr|maximum|максимум|"
        r"також|also|надай\w*|provide|за\s+останн|last|"
        r"\d+\s*тижн|\d+\s*днів|\d+\s*дней|\d+\s*days|\d+\s*weeks?)\b"
    )

    patterns = [
        # "шукають 3D hard-surface artist"
        r"(?:шукають|шукає|шукати|ищут|ищет)\s+(.+?)(?:\.|,|надай|надаю|шукай|\n|$)",
        # "looking for product manager"
        r"(?:looking for|search(?:ing)? for)\s+(.+?)(?:\.|,|provide|\n|$)",
        # "find 200 companies looking for X"
        r"(?:find|get|show)\s+\d+\s+\S+\s+looking\s+for\s+(.+?)(?:\.|,|provide|\n|$)",
        # "find product manager"
        r"(?:find|get|show)\s+(?!\d)(.+?)(?:\.|,|provide|in\s|\n|$)",
        # "вакансій/вакансий 3D artist" (Ukrainian + Russian)
        r"(?:вакансі\w*|позиці\w*|jobs?|positions?)\s+(.+?)(?:\.|,\s*(?:remote|віддален|удалён|шукай|країн|в\s)|\n|$)",
        # "знайди мені 100 компаній які шукають X"
        r"(?:знайд\w*|найд\w*).+?(?:шукають|шукає|ищут)\s+(.+?)(?:\.|,|надай|надаю|шукай|\n|$)",
        # "знайди 10 вакансій X" / "найди 10 вакансий X"
        r"(?:знайд\w*|найд\w*)\s+\d+\s+\S+\s+(.+?)(?:\.|,\s*(?:remote|віддален|удалён|шукай|країн|[уві]\s)|\n|$)",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            title = m.group(1).strip()
            title = re.sub(noise, "", title, flags=re.I)
            title = re.sub(r"\s+", " ", title).strip(" .,;:–—-")
            if len(title) > 2:
                return _transliterate_tech_terms(title)

    # ── Stripping approach (for simple queries) ──
    # Remove everything that ISN'T the job title
    stripped = text
    stripped = _STRIP_COMMAND_WORDS.sub(" ", stripped)
    stripped = re.sub(r"\b\d+\b", " ", stripped)           # numbers
    stripped = _STRIP_COUNT_WORDS.sub(" ", stripped)
    # Remove location/remote markers
    stripped = re.sub(
        r"\b(?:remote|віддален\w*|удалён\w*|удален\w*|дистанц\w*)\b",
        " ", stripped, flags=re.I | re.UNICODE,
    )
    # Remove country names and EU markers
    stripped = re.sub(
        r"\b(?:єс|ес|eu|євросоюз|евросоюз|europe|європ\w*|сша|usa|канад\w*|canada)\b",
        " ", stripped, flags=re.I | re.UNICODE,
    )
    # Remove salary-related words
    stripped = re.sub(
        r"\b(?:зарплат\w*|salary|оплат\w*|компенсац\w*|pay|wage)\b",
        " ", stripped, flags=re.I | re.UNICODE,
    )
    # Remove time markers
    stripped = re.sub(
        r"\b(?:максимум|maximum|останн\w*|last|тижн\w*|днів|дней|день|дня|days?|weeks?|months?|місяц\w*|месяц\w*|двох?|двух?|давнин\w*)\b",
        " ", stripped, flags=re.I | re.UNICODE,
    )
    # Remove filler/connector words
    stripped = re.sub(
        r"\b(?:які|яких|які|который|которые|що|что|та|и|і|й|та|також|also|тобі|тебе|своє|для|кращого|розуміння|шукай|виключно|відфільтруй|за|у|в|країнах?|щоб|були|резюме)\b",
        " ", stripped, flags=re.I | re.UNICODE,
    )
    # Remove punctuation leftovers
    stripped = re.sub(r"[.,;:!?\-–—\"'()\[\]{}]", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()

    if len(stripped) > 1:
        return _transliterate_tech_terms(stripped)

    # ── Last resort fallbacks ──
    m = re.search(r'"([^"]+)"', text)
    if m:
        return _transliterate_tech_terms(m.group(1))

    m = re.search(
        r"\b(\d?D[\s\-]?\w[\w\s\-]{3,30}(?:artist|designer|modeler|animator|developer))",
        text, re.I,
    )
    if m:
        return m.group(1).strip()

    return ""


def _extract_remote(text: str) -> bool:
    """Check if remote-only is requested."""
    t = text.lower()
    if re.search(r"\b(remote|remotely|wfh|work\s+from\s+home)\b", t):
        return True
    cyrillic_markers = ["віддален", "удалён", "удален", "дистанц"]
    return any(m in t for m in cyrillic_markers)


def _extract_locations(text: str) -> list[str]:
    """Extract target countries/locations."""
    locations: set[str] = set()
    t = text.lower()

    if re.search(r"\b(єс|ес|eu|євросоюз|евросоюз|europe|європ)\b", t, re.I):
        locations.update(EU_COUNTRIES)

    for alias, canonical in COUNTRY_ALIASES.items():
        if alias in t:
            locations.add(canonical)

    return sorted(locations)


def _extract_max_age(text: str) -> int:
    """Extract max job age in hours."""
    t = text.lower()

    m = re.search(r"(\d+)\s*(?:дн[ейів]|день|day|дня)", t)
    if m:
        return int(m.group(1)) * 24

    m = re.search(r"(\d+)\s*(?:тижн|неділ|недел|week)", t)
    if m:
        return int(m.group(1)) * 24 * 7

    if re.search(r"(дво?х?|двух?)\s*тижн", t):
        return 14 * 24
    if re.search(r"(дво?х?|двух?)\s*недел", t):
        return 14 * 24

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


def _regex_parse_query(raw: str) -> ParsedQuery:
    """Parse query using regex + transliteration (fallback when AI is unavailable)."""
    return ParsedQuery(
        job_title=_extract_job_title(raw),
        count=_extract_count(raw),
        remote=_extract_remote(raw),
        locations=_extract_locations(raw),
        max_age_hours=_extract_max_age(raw),
        salary_filter=_extract_salary_filter(raw),
        raw_query=raw,
    )


# ═══════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════

def parse_query(raw: str) -> ParsedQuery:
    """
    Parse a natural language query into structured scraper parameters.
    
    Strategy:
      1. Try AI parsing (OpenAI structured output) — fast, accurate, multilingual
      2. Fall back to regex + Cyrillic transliteration if AI is unavailable
    """
    result = _ai_parse_query(raw)
    if result is not None:
        logger.info("✓ Query parsed via AI")
        return result

    logger.info("⚙ Query parsed via regex (AI unavailable)")
    return _regex_parse_query(raw)
