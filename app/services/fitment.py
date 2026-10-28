"""Deterministic candidate-job fitment baseline.

Versioned rules (see README "Deterministic assessment"):
- Text is folded with NFKC, casefolded, quotes/dashes normalised and whitespace collapsed.
- A criterion matches when one of its terms appears as a whole token. Tokens may contain
  letters, digits, '+', '#' and inner '.' (for example "c++", "c#", "node.js").
  "C" does not match "C++", and "Java" does not match "JavaScript".
- "a | b" in a criterion means either option satisfies it.
- Known synonyms (SYNONYMS) are treated as equivalent terms.
- A match preceded by a negation word within 40 characters is NOT counted as matched;
  it is marked needs_review so a recruiter checks it.
- "missing" means not evidenced in the supplied text. It never proves the candidate lacks a skill.
- Empty requirements or empty resume text never produce a fabricated match.
"""

import re
import unicodedata
from dataclasses import dataclass

ASSESSMENT_VERSION = "fitment-v1.0.0"
SNIPPET_MAX_CHARS = 160
NEGATION_WINDOW = 40
_NEGATION_RE = re.compile(r"\b(no|not|never|without|lack|lacks|lacking)\b")

SYNONYMS: dict[str, tuple[str, ...]] = {
    "javascript": ("js", "ecmascript"),
    "node.js": ("nodejs", "node js"),
    "c#": ("csharp", "c sharp"),
    "c++": ("cpp",),
    "python": ("python3",),
    "postgresql": ("postgres",),
    "machine learning": ("ml",),
    "natural language processing": ("nlp",),
    "amazon web services": ("aws",),
    "retrieval augmented generation": ("rag",),
    "extract transform load": ("etl",),
}
_REVERSE_SYNONYMS = {alias: canonical for canonical, aliases in SYNONYMS.items() for alias in aliases}

_QUOTE_MAP = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"}
)


def fold(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold().translate(_QUOTE_MAP)
    return re.sub(r"\s+", " ", value).strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#]|\.\w)")


def _terms_for(option: str) -> tuple[str, ...]:
    key = fold(option)
    canonical = key if key in SYNONYMS else _REVERSE_SYNONYMS.get(key, key)
    ordered = [canonical, *SYNONYMS.get(canonical, ())]
    seen: list[str] = []
    for term in ordered:
        folded = fold(term)
        if folded and folded not in seen:
            seen.append(folded)
    return tuple(seen)


def _has_matchable_text(option: str) -> bool:
    return re.search(r"\w", option) is not None


def _snippet(line: str) -> str:
    if len(line) <= SNIPPET_MAX_CHARS:
        return line
    return line[: SNIPPET_MAX_CHARS - 3].rstrip() + "..."


def _resume_lines(resume_text: str | None) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw in (resume_text or "").splitlines():
        stripped = raw.strip()
        if stripped:
            lines.append((stripped, fold(stripped)))
    return lines


def _find_evidence(option_terms: list[tuple[str, ...]], lines: list[tuple[str, str]]):
    patterns = [_term_pattern(term) for terms in option_terms for term in terms]
    for original, folded in lines:
        for pattern in patterns:
            found = pattern.search(folded)
            if found:
                window = folded[max(0, found.start() - NEGATION_WINDOW) : found.start()]
                return _snippet(original), _NEGATION_RE.search(window) is not None
    return None, False


def clean_requirements(requirements) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in requirements or []:
        text = " ".join(str(item).split())
        key = fold(text)
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


@dataclass(frozen=True)
class CriterionResult:
    criterion: str
    status: str  # matched | missing | needs_review
    evidence: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class FitmentResult:
    version: str
    criteria: tuple[CriterionResult, ...]

    def _with_status(self, status: str) -> tuple[CriterionResult, ...]:
        return tuple(c for c in self.criteria if c.status == status)

    @property
    def matched(self) -> tuple[CriterionResult, ...]:
        return self._with_status("matched")

    @property
    def missing(self) -> tuple[CriterionResult, ...]:
        return self._with_status("missing")

    @property
    def needs_review(self) -> tuple[CriterionResult, ...]:
        return self._with_status("needs_review")

    @property
    def fitment_percent(self) -> float | None:
        scorable = len(self.matched) + len(self.missing)
        if scorable == 0:
            return None
        return round(100 * len(self.matched) / scorable, 1)


def compute_fitment(requirements, resume_text: str | None) -> FitmentResult:
    criteria = clean_requirements(requirements)
    lines = _resume_lines(resume_text)
    results: list[CriterionResult] = []
    for criterion in criteria:
        options = [part.strip() for part in criterion.split("|") if _has_matchable_text(part)]
        if not options:
            results.append(
                CriterionResult(criterion, "needs_review", note="Criterion has no matchable text.")
            )
            continue
        if not lines:
            results.append(
                CriterionResult(criterion, "needs_review", note="No resume text is available to compare.")
            )
            continue
        snippet, negated = _find_evidence([_terms_for(o) for o in options], lines)
        if snippet is None:
            results.append(CriterionResult(criterion, "missing"))
        elif negated:
            results.append(
                CriterionResult(
                    criterion,
                    "needs_review",
                    evidence=snippet,
                    note="Possible negation near the matched term; recruiter review required.",
                )
            )
        else:
            results.append(CriterionResult(criterion, "matched", evidence=snippet))
    return FitmentResult(version=ASSESSMENT_VERSION, criteria=tuple(results))
