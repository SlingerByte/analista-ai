from __future__ import annotations

from app.ingestion.normalizers import normalize_key

RULE_PHONE_EMAIL_EXACT = "PHONE_EMAIL_EXACT"
RULE_PHONE_NAME_SIMILAR = "PHONE_NAME_SIMILAR"
RULE_NAME_CITY_MATCH = "NAME_CITY_MATCH"

STRENGTH_STRONG = "strong"
STRENGTH_POSSIBLE = "possible"
STRENGTH_WEAK = "weak"

RULE_STRENGTH = {
    RULE_PHONE_EMAIL_EXACT: STRENGTH_STRONG,
    RULE_PHONE_NAME_SIMILAR: STRENGTH_POSSIBLE,
    RULE_NAME_CITY_MATCH: STRENGTH_WEAK,
}

# Deterministic cluster status: only all-strong clusters are auto-consolidated.
STATUS_AUTO = "auto"
STATUS_POSSIBLE_PENDING = "possible_pending"

NAME_SIMILARITY_THRESHOLD = 0.90
STRENGTH_ORDER = {STRENGTH_STRONG: 0, STRENGTH_POSSIBLE: 1, STRENGTH_WEAK: 2}


def name_similarity(name_a: str | None, name_b: str | None) -> float:
    return jaro_winkler(normalize_key(name_a), normalize_key(name_b))


def jaro_winkler(text_a: str, text_b: str) -> float:
    if text_a == text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    jaro = _jaro(text_a, text_b)
    if jaro == 0.0:
        return 0.0

    prefix = 0
    for char_a, char_b in zip(text_a, text_b):
        if char_a == char_b and prefix < 4:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


def _jaro(text_a: str, text_b: str) -> float:
    len_a, len_b = len(text_a), len(text_b)
    match_distance = max(len_a, len_b) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    matches_a = [False] * len_a
    matches_b = [False] * len_b
    matches = 0

    for index_a in range(len_a):
        start = max(0, index_a - match_distance)
        end = min(index_a + match_distance + 1, len_b)
        for index_b in range(start, end):
            if matches_b[index_b] or text_a[index_a] != text_b[index_b]:
                continue
            matches_a[index_a] = True
            matches_b[index_b] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    transpositions = 0
    index_b = 0
    for index_a in range(len_a):
        if not matches_a[index_a]:
            continue
        while not matches_b[index_b]:
            index_b += 1
        if text_a[index_a] != text_b[index_b]:
            transpositions += 1
        index_b += 1
    transpositions //= 2

    return (
        matches / len_a
        + matches / len_b
        + (matches - transpositions) / matches
    ) / 3
