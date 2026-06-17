"""Licence-plate helpers for the parking ANPR module.

Phase 1 only needs normalization — turning whatever the admin types (or the
ANPR camera later reports) into one canonical form so whitelist lookups are
exact and alphabet-agnostic.
"""

from __future__ import annotations

# Cyrillic letters that are visually identical to Latin ones. KG/RU plates use
# exactly this restricted set; an admin may type them in Cyrillic while a Dahua
# ANPR camera reports Latin (or vice-versa). Fold everything to Latin so the
# stored plate and the recognised plate always compare equal.
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    }
)


def normalize_plate(raw: str) -> str:
    """Canonical form of a licence plate for storage and comparison.

    Upper-cases, folds Cyrillic homoglyphs to Latin, and drops everything that
    is not a letter or digit (spaces, dashes, dots). Returns "" for empty/None.
    """
    if not raw:
        return ""
    folded = raw.upper().translate(_CYRILLIC_TO_LATIN)
    return "".join(ch for ch in folded if ch.isalnum())


async def find_active_plate(db, plate: str):
    """Return the enabled ``PlateWhitelist`` row matching ``plate``, or None.

    ``plate`` must already be normalized (see normalize_plate). Used by the
    anpr_service to decide whether to open the barrier.
    """
    if not plate:
        return None
    from sqlalchemy import select

    from app.models import PlateWhitelist

    result = await db.execute(
        select(PlateWhitelist).where(
            PlateWhitelist.plate == plate,
            PlateWhitelist.enabled == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()
