"""Feature 4 — lightweight policy-violation detection for chat messages.

This is a defensive scanner: it looks at an incoming question for a few
well-known risky patterns (attempts to exfiltrate secrets or confidential data,
requests to share credentials, abusive/toxic language, and clear policy-bypass
phrasing). It never blocks the conversation on its own; the caller decides what
to do with the result (we log an AuditLog row and surface a flag to the user).

Kept deliberately simple and dependency-free: case-insensitive regexes with word
boundaries to keep false positives low. The goal is useful signal, not a perfect
classifier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each category maps to a list of compiled patterns. Word boundaries (\b) keep
# "class" from matching "classified", etc.
_RAW_PATTERNS: dict[str, list[str]] = {
    "data_leak": [
        r"\bconfidential\b.{0,30}\b(share|send|leak|forward|post|upload)\b",
        r"\b(share|send|leak|forward|post|upload)\b.{0,30}\bconfidential\b",
        r"\bleak(ed|ing)?\b",
        r"\bexfiltrat",
        r"\bdump\b.{0,20}\b(database|db|data|table)\b",
    ],
    "credential_exposure": [
        r"\b(api[\s_-]?key|secret[\s_-]?key|access[\s_-]?token|private[\s_-]?key)\b",
        r"\b(password|passwd|credentials?)\b.{0,20}\b(share|send|give|tell|reveal|show)\b",
        r"\b(share|send|give|tell|reveal|show)\b.{0,20}\b(password|passwd|credentials?)\b",
        r"\bssh[\s_-]?key\b",
    ],
    "pii_exposure": [
        # US SSN-style and generic 16-digit card numbers.
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b(?:\d[ -]?){16}\b",
        # Pakistani identifiers: CNIC (XXXXX-XXXXXXX-X) and PK-format IBAN
        # (PK + 2 check digits + 4-letter bank code + 16 account chars = 24
        # total) — the formats this product's users are actually likely to paste.
        r"\b\d{5}-\d{7}-\d\b",
        r"\bPK\d{2}[A-Z]{4}[A-Z0-9]{16}\b",
    ],
    "policy_bypass": [
        r"\b(bypass|circumvent|get around|override)\b.{0,25}\b(policy|policies|rule|rules|security|control)\b",
        r"\bignore\b.{0,25}\b(policy|policies|rule|rules|compliance)\b",
        r"\b(delete|wipe|erase|clear)\b.{0,20}\b(audit|logs?|records?)\b",
        r"\bdisable\b.{0,20}\b(audit|logging|security)\b",
    ],
    "toxic_language": [
        r"\b(idiot|stupid|moron|dumbass|shut up)\b",
        r"\bf[\*u]ck\b",
        r"\bb[\*i]tch\b",
        r"\basshole\b",
    ],
    "prompt_injection": [
        r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all)\b.{0,25}\b(instructions?|prompts?|rules?|directives?)\b",
        r"\b(you are now|act as|pretend to be|roleplay as)\b.{0,30}\b(unrestricted|jailbreak|DAN|evil|god mode|developer mode)\b",
        r"\b(reveal|output|display|show|print|tell me)\b.{0,30}\b(system\s+prompt|initial\s+instructions?|developer\s+instructions?)\b",
        r"\b<\s*(?:system|im_start|instruction)\s*>",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats] for cat, pats in _RAW_PATTERNS.items()
}

# Human-readable labels for the categories, used in audit details and the UI flag.
_LABELS = {
    "data_leak": "possible confidential-data leak",
    "credential_exposure": "credential / secret sharing",
    "pii_exposure": "personal data (PII) exposure",
    "policy_bypass": "attempt to bypass policy or controls",
    "toxic_language": "abusive or toxic language",
    "prompt_injection": "potential prompt injection / system prompt extraction",
}


@dataclass
class ModerationResult:
    flagged: bool = False
    categories: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [_LABELS.get(c, c) for c in self.categories]

    def summary(self) -> str:
        """Short, audit-friendly one-liner."""
        if not self.flagged:
            return ""
        return "; ".join(self.labels)


def scan(text: str) -> ModerationResult:
    """Scan a chat message and return which policy categories it tripped (if any)."""
    result = ModerationResult()
    if not text:
        return result
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                result.categories.append(category)
                snippet = m.group(0).strip()
                # Keep audit snippets short and never store a full card/SSN value.
                if category == "pii_exposure":
                    snippet = "<redacted>"
                result.matches.append(snippet[:60])
                break  # one hit per category is enough
    result.flagged = bool(result.categories)
    return result


_SECRET_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})['\"]?"),
]

_EXFIL_PATTERNS = [
    re.compile(r"\b(dump|print|output|copy|extract|export|reveal)\b.{0,30}\b(entire|whole|full|all|every word of)\b.{0,25}\b(documents?|files?|vault|database|chunks?)\b", re.IGNORECASE),
    re.compile(r"\b(verbatim|word[- ]for[- ]word)\b.{0,30}\b(entire|whole|all|document|file)\b", re.IGNORECASE),
]


def detect_pii(text: str) -> bool:
    """True when text contains structured PII (SSN/CNIC/card/IBAN) or embedded secrets."""
    if not text:
        return False
    if any(p.search(text) for p in _COMPILED["pii_exposure"]):
        return True
    return any(p.search(text) for p in _SECRET_VALUE_PATTERNS)


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Mask structured PII and secret values before text leaves to an LLM or external share."""
    if not text:
        return text, []
    cleaned = text
    redacted: list[str] = []
    for p in _COMPILED["pii_exposure"]:
        if p.search(cleaned):
            cleaned = p.sub("[REDACTED:PII]", cleaned)
            if "pii_exposure" not in redacted:
                redacted.append("pii_exposure")
    for p in _SECRET_VALUE_PATTERNS:
        if p.search(cleaned):
            cleaned = p.sub("[REDACTED:SECRET]", cleaned)
            if "secret_exposure" not in redacted:
                redacted.append("secret_exposure")
    return cleaned, redacted


def is_exfiltration_attempt(text: str) -> bool:
    """True when a prompt looks like an attempt to dump whole vault files verbatim."""
    if not text:
        return False
    return any(p.search(text) for p in _EXFIL_PATTERNS)
