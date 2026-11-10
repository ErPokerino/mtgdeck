"""What a format allows, said once for every AI skill and checked on what the model writes.

The model knows Magic from memory, and memory goes stale: a card banned last year can
still look like a natural alternative. Every prompt therefore carries the format's scope
and banlist from the synced catalog, and every text the model returns is scanned for
cards that cannot be played in the format: a banned or out-of-format card is an error to
correct, wherever it appears (alternatives, excluded cards, flex slots, tips).
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models import Card, SetModel, SyncLog

FORMATS = ("standard", "pioneer", "modern")

FORMAT_SCOPE = {
    "standard": "Standard: solo le espansioni della rotazione corrente.",
    "pioneer": "Pioneer: espansioni da Return to Ravnica (2012) in poi; le ristampe contano solo se la carta è legale nel formato.",
    "modern": "Modern: espansioni da Eighth Edition e Mirrodin (2003) in poi; le ristampe contano solo se la carta è legale nel formato.",
}

# Words of a card name, keeping in-word apostrophes and hyphens ("Fire's", "Mirror-Breaker").
TOKEN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+(?:['\-][0-9A-Za-zÀ-ÖØ-öø-ÿ]+)*")
PLAYABLE = {"legal", "banned", "restricted"}
# "Funge da Time Walk", "funziona come Force Spike": a card used as a figure of speech
# describes an effect; it is not a card proposed for the deck.
COMPARISON_CUES = {"come", "tipo", "stile", "alla", "effetto", "funge", "fungere", "fa", "fare", "mo"}
# Paths whose text names an archetype, not a card.
NOT_CARD_TEXT = ("opponent_archetype", "deck_a_name", "deck_b_name", "base_archetype")


def _tokens(text: str) -> Tuple[str, ...]:
    return tuple(TOKEN.findall(text.replace("’", "'")))


def banned_names(db: Session, fmt: str) -> List[str]:
    col = getattr(Card, f"legality_{fmt}")
    return [n for (n,) in db.query(Card.name).filter(col == "banned").order_by(Card.name)]


def _sync_stamp(db: Session) -> str:
    sync = (
        db.query(SyncLog)
        .filter_by(source="scryfall", status="completed")
        .order_by(SyncLog.completed_at.desc())
        .first()
    )
    return sync.completed_at.date().isoformat() if sync and sync.completed_at else "non documentata"


def format_rules_block(db: Session, fmt: str) -> str:
    """Scope and banlist of the format, from the catalog the app validates against."""
    fmt = fmt.lower()
    label = fmt.upper()
    lines = [f"=== REGOLE DEL FORMATO {label} ===", FORMAT_SCOPE.get(fmt, label)]
    if fmt == "standard":
        sets = [
            n
            for (n,) in db.query(SetModel.name)
            .filter(SetModel.is_standard_legal.is_(True))
            .order_by(SetModel.released_at)
        ]
        if sets:
            lines.append("Espansioni Standard attuali: " + ", ".join(sets) + ".")
    banned = banned_names(db, fmt)
    lines.append(
        f"Banlist {label} aggiornata al {_sync_stamp(db)} ({len(banned)} carte): "
        + (", ".join(banned) if banned else "nessuna")
        + "."
    )
    lines.append(
        f"Ogni carta che nomini, nella lista o nel testo (alternative considerate, carte escluse, "
        f"flex slot, tech, sideboard, consigli), deve essere legale in {label}. Una carta bandita o "
        f"fuori formato non si gioca: non proporla e non citarla come opzione o alternativa. "
        f"Se non sei certo che una carta sia legale in {label}, scegline una fornita nel contesto."
    )
    return "\n".join(lines)


class CardNameIndex:
    """Every real card and face name, matched on whole words, longest name first."""

    def __init__(self, fmt: str, names: Iterable[Tuple[str, str]]):
        self.fmt = fmt
        status: Dict[Tuple[str, ...], Tuple[str, str]] = {}
        for name, legality in names:
            toks = _tokens(name)
            if not toks:
                continue
            prior = status.get(toks)
            # Two cards sharing a name (a face and a card): any legal one keeps it legal.
            if prior is None or legality == "legal":
                status[toks] = (name, legality)
        self.by_first: Dict[str, List[Tuple[Tuple[str, ...], str, str]]] = {}
        for toks, (name, legality) in status.items():
            self.by_first.setdefault(toks[0], []).append((toks, name, legality))
        for rows in self.by_first.values():
            rows.sort(key=lambda r: -len(r[0]))

    def _flagged(self, toks: Tuple[str, ...], legality: str) -> bool:
        if legality == "legal":
            return False
        # Single-word names that are not banned collide with keywords ("Flash",
        # "Channel", "Delirium"): only structured card fields check those.
        return legality == "banned" or len(toks) > 1

    def illegal_in_text(self, text: str) -> List[Tuple[str, str]]:
        words = _tokens(text)
        found: List[Tuple[str, str]] = []
        i = 0
        while i < len(words):
            for toks, name, legality in self.by_first.get(words[i], ()):
                if words[i : i + len(toks)] == toks:
                    comparison = any(w.lower() in COMPARISON_CUES for w in words[max(0, i - 3) : i])
                    if self._flagged(toks, legality) and not comparison:
                        found.append((name, legality))
                    i += len(toks)
                    break
            else:
                i += 1
        return list(dict.fromkeys(found))


_INDEX_CACHE: Dict[Tuple[str, str], CardNameIndex] = {}


def card_index(db: Session, fmt: str) -> CardNameIndex:
    fmt = fmt.lower()
    sync = (
        db.query(SyncLog.id, SyncLog.completed_at)
        .filter_by(source="scryfall", status="completed")
        .order_by(SyncLog.completed_at.desc())
        .first()
    )
    stamp = (fmt, f"{db.get_bind().url}:{sync.id if sync else 0}:{sync.completed_at if sync else ''}")
    cached = _INDEX_CACHE.get(stamp)
    if cached is not None:
        return cached
    col = getattr(Card, f"legality_{fmt}")
    names: List[Tuple[str, str]] = []
    rows = db.query(
        Card.name,
        Card.card_faces,
        col,
        Card.legality_standard,
        Card.legality_pioneer,
        Card.legality_modern,
        Card.legalities_json,
        Card.type_line,
    )
    for name, faces, legality, std, pio, mod, others, type_line in rows:
        # Tokens, emblems and un-cards are legal nowhere: they are not cards to play.
        if (type_line or "").startswith("Token"):
            continue
        if not ({std, pio, mod} | set((others or {}).values())) & PLAYABLE:
            continue
        legality = legality or "not_legal"
        if " // " not in name:
            names.append((name, legality))
        for face in faces or []:
            if face.get("name"):
                names.append((face["name"], legality))
        if " // " in name and not faces:
            names.extend((half, legality) for half in name.split(" // "))
    index = CardNameIndex(fmt, names)
    _INDEX_CACHE.clear()  # one catalog at a time: keep memory bounded
    _INDEX_CACHE[stamp] = index
    return index


def _texts(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _texts(item, f"{path}/{i}")
    elif isinstance(node, dict):
        for name, item in node.items():
            if name in NOT_CARD_TEXT:
                continue
            yield from _texts(item, f"{path}/{name}")


def _status_label(legality: str, fmt: str) -> str:
    return f"bandita in {fmt.upper()}" if legality == "banned" else f"non legale in {fmt.upper()}"


def illegal_mentions(
    index: CardNameIndex, node, ignore: Sequence[str] = ()
) -> List[Tuple[str, str, str]]:
    """(path, card, legality) of every card the text names that the format does not allow.
    `ignore` holds archetype names, which may contain the name of a card."""
    found = []
    for path, text in _texts(node):
        for name in ignore:
            if name:
                text = text.replace(name, " ")
        for card, legality in index.illegal_in_text(text):
            found.append((path, card, legality))
    return found


def illegal_mention_errors(
    index: CardNameIndex, node, ignore: Sequence[str] = ()
) -> List[str]:
    errors = []
    for path, card, legality in illegal_mentions(index, node, ignore):
        errors.append(
            f"Carta non giocabile ({path}): '{card}' è {_status_label(legality, index.fmt)}. "
            "Sostituiscila con un'alternativa legale nel formato o togli la menzione, in tutte le occorrenze."
        )
    return list(dict.fromkeys(errors))


def card_name_errors(
    db: Session, fmt: str, names: Iterable[Tuple[str, str]]
) -> List[str]:
    """Structured card fields (path, name): the name must be a real card legal in the format."""
    from app.services.deck_validator import resolve_card_by_name

    errors = []
    for path, raw in names:
        card: Optional[Card] = resolve_card_by_name(db, raw) if raw else None
        if card is None:
            errors.append(
                f"Carta sconosciuta ({path}): '{raw}' non esiste nel catalogo. Usa il nome inglese esatto di una carta legale in {fmt.upper()}."
            )
            continue
        legality = getattr(card, f"legality_{fmt}", "not_legal") or "not_legal"
        if legality != "legal":
            errors.append(
                f"Carta non giocabile ({path}): '{card.name}' è {_status_label(legality, fmt)}. "
                "Sostituiscila con un'alternativa legale nel formato."
            )
    return errors
