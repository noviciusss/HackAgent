from __future__ import annotations

import re


NEGATION_PATTERNS = [
    r"(?:do not|don\'t|dont)\s+(?:close|delete|erase|remove)",
    r"without\s+(?:removing|deleting|erasing|closing)",
    r"not\s+(?:asking for|a request (?:for|to))\s+(?:deletion|erase|delete|close)",
    r"leave\s+.*(?:active|in place|as it is)",
    r"keep\s+.*(?:active|as it is)",
    r"no\s+(?:eliminen|borren|cierren)",
    r"sin\s+(?:eliminar|borrar|cerrar)",
    r"não\s+(?:exclua|excluir|apagar|eliminar|fechar)",
    r"sem\s+(?:excluir|apagar|eliminar)",
    r"ne\s+(?:supprimez|fermez|effacez)\s+pas",
    r"sans\s+(?:supprimer|effacer)",
    r"nicht\s+(?:löschen|schließen)",
    r"ohne\s+zu\s+löschen",
]

NARROW_NON_DELETION = [
    r"marketing (?:lists?|emails?)|promotional|unsubscribe|opt[- ]?out",
    r"download\s+.*(?:information|data)\s+in\s+a\s+portable\s+format",
    r"copy\s+of\s+.*invoice",
    r"information\s+request",
    r"what\s+personal\s+information",
    r"reset(?:ting)?\s+the\s+login",
    r"misspell|misspelled|correct\s+(?:my|the|it)",
    r"replace\s+it\s+with\s+the\s+new\s+one",
    r"change\s+(?:the\s+)?(?:email|phone|mobile|number)",
]

DELETION_PATTERNS = [
    r"\bdelete\b", r"delet(?:e|ed|ion|ing)\b", r"\berase\b", r"\berased\b",
    r"\bremove\b", r"\bremov(?:e|al|ed|ing)\b",
    r"\bclose\b.*\baccount\b", r"\baccount\b.*\bclosed\b",
    r"profile is gone", r"audit the deletion", r"confirm .* deletion",
    r"suppression", r"elimin", r"exclusão", r"削除", r"삭제",
]


def is_deletion_request(text: str) -> bool:
    low = text.lower()
    # 1. Check explicit non-deletion / negation expressions
    if any(re.search(pat, low, re.I) for pat in NEGATION_PATTERNS):
        return False
    # 2. Check narrow-scope requests (e.g. marketing opt-out, download, correction) without general account deletion
    if any(re.search(pat, low, re.I) for pat in NARROW_NON_DELETION):
        if not re.search(r"(?:permanently|entire|full|account)\s+(?:delete|erase|close|removal)", low, re.I):
            return False
    # 3. Check affirmative deletion patterns
    if any(re.search(pat, low, re.I) for pat in DELETION_PATTERNS):
        return True
    return False


def classify_request(text: str) -> str:
    return "DELETION" if is_deletion_request(text) else "NOT_APPLICABLE"
