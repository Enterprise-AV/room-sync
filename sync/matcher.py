"""Fuzzy name matching engine.

Suggests possible mappings between rooms on different platforms using
string similarity.  Uses only the stdlib ``difflib`` module.
"""

import difflib


def normalize(name: str) -> str:
    """Lowercase, strip whitespace."""
    return name.strip().lower()


def similarity(a: str, b: str) -> float:
    """Return a 0-1 similarity score between two room names.

    Uses ``SequenceMatcher`` for overall shape and a word-overlap bonus so
    that names sharing key tokens (building codes, room numbers) score
    higher even when word order differs.
    """
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return 1.0

    seq_score = difflib.SequenceMatcher(None, na, nb).ratio()

    # Word-overlap bonus (same approach as activation.py _name_similarity)
    a_words = set(na.split())
    b_words = set(nb.split())
    if a_words and b_words:
        overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
    else:
        overlap = 0.0

    return max(seq_score, overlap)


def find_suggestions(source_rooms, target_rooms, threshold=0.7, max_per_room=3):
    """Find fuzzy matches between two lists of rooms.

    Parameters
    ----------
    source_rooms : list[dict]
        Rooms from the "source" platform (e.g. unmapped Zoom rooms).
        Each dict must have a ``"name"`` key.
    target_rooms : list[dict]
        Rooms from the "target" platform (e.g. unmapped Neat rooms).
    threshold : float
        Minimum similarity score to consider a match (0-1).
    max_per_room : int
        Maximum number of suggestions per source room.

    Returns
    -------
    list[dict]
        Each entry:
        ``{"source": room_dict, "suggestions": [{"target": room_dict, "score": float}, ...]}``
    """
    results = []
    for src in source_rooms:
        src_name = src.get("name", "")
        if not src_name:
            continue

        scored = []
        for tgt in target_rooms:
            tgt_name = tgt.get("name", "")
            if not tgt_name:
                continue
            score = similarity(src_name, tgt_name)
            if score >= threshold:
                scored.append({"target": tgt, "score": round(score, 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        if scored:
            results.append({
                "source": src,
                "suggestions": scored[:max_per_room],
            })

    return results
