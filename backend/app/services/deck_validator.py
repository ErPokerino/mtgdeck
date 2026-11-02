import re
from collections import Counter
from typing import List, Tuple, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import Card
from app.schemas import DeckAnalytics, DeckValidationReport, ValidationIssue
from app.services.scryfall_sync import normalize_card_name, sort_colors_wubrg

COLOR_NAMES = {
    "": "Colorless",
    "W": "Mono-White",
    "U": "Mono-Blue",
    "B": "Mono-Black",
    "R": "Mono-Red",
    "G": "Mono-Green",
    "WU": "Azorius",
    "UB": "Dimir",
    "BR": "Rakdos",
    "RG": "Gruul",
    "WG": "Selesnya",
    "WB": "Orzhov",
    "UR": "Izzet",
    "BG": "Golgari",
    "WR": "Boros",
    "UG": "Simic",
    "WUB": "Esper",
    "UBR": "Grixis",
    "BRG": "Jund",
    "WRG": "Naya",
    "WUG": "Bant",
    "WBG": "Abzan",
    "WUR": "Jeskai",
    "UBG": "Sultai",
    "WBR": "Mardu",
    "URG": "Temur",
    "WUBRG": "Five-Color Domain",
}


def get_color_combination_label(colors: List[str]) -> Tuple[List[str], str]:
    ordered = sort_colors_wubrg(colors)
    code = "".join(ordered)
    name = COLOR_NAMES.get(code, "Four-Color" if len(ordered) == 4 else code)
    return ordered, f"{name} ({code})" if code else "Colorless"


def resolve_card_by_name(db: Session, raw_name: str) -> Optional[Card]:
    name = normalize_card_name(raw_name)
    if not name:
        return None
    card = db.query(Card).filter(Card.normalized_name == name).first()
    if card:
        return card
    # Never use a fuzzy match for a deck slot. Only exact front/back names of DFCs.
    front = name.split(" // ")[0]
    escaped = front.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    candidates = (
        db.query(Card)
        .filter(Card.normalized_name.like(escaped + " //%", escape="\\"))
        .all()
    )
    for card in candidates:
        if normalize_card_name(card.name.split(" // ")[0]) == front:
            return card
    return (
        db.query(Card).filter(func.lower(Card.name) == raw_name.strip().lower()).first()
    )


def validate_deck_entries(format_id, entries) -> DeckValidationReport:
    fmt = format_id.lower()
    issues = []

    def issue(code, message, severity="error", card_name=None):
        issues.append(
            ValidationIssue(
                code=code, message=message, severity=severity, card_name=card_name
            )
        )

    if fmt not in ("standard", "pioneer", "modern"):
        issue("UNSUPPORTED_FORMAT", "Formato non supportato.")
    for card, board, qty in entries:
        if (
            board not in ("main", "side", "companion")
            or not isinstance(qty, int)
            or qty <= 0
        ):
            issue("INVALID_ENTRY", f"Voce non valida: {card.name}")
    main = sum(q for _, b, q in entries if b == "main")
    side = sum(q for _, b, q in entries if b in ("side", "companion"))
    companion = sum(q for _, b, q in entries if b == "companion")
    if main < 60:
        issue("MAINBOARD_TOO_SMALL", f"Mainboard: {main} carte. Minimo richiesto: 60.")
    elif main > 60:
        issue(
            "MAINBOARD_OVER_60",
            f"Mainboard: {main} carte. Legale, ma motiva il costo sulla consistenza.",
            "warning",
        )
    if side > 15:
        issue(
            "SIDEBOARD_TOO_LARGE",
            f"Sideboard: {side} carte incluso il companion. Massimo: 15.",
        )
    elif side < 15 and main >= 60:
        issue(
            "SIDEBOARD_INCOMPLETE",
            f"Sideboard: {side}/15. Una sideboard con meno di 15 carte è legale.",
            "warning",
        )
    if companion > 1:
        issue("MULTIPLE_COMPANIONS", "Puoi designare un solo companion.")
    quantities, cards = Counter(), {}
    for card, board, qty in entries:
        if board not in ("main", "side", "companion") or qty <= 0:
            continue
        if board == "companion":
            issue(
                "COMPANION_REQUIRES_REVIEW",
                f"{card.name}: la restrizione del companion richiede una verifica manuale; la lista non è certificata automaticamente.",
            )
        quantities[card.oracle_id] += qty
        cards[card.oracle_id] = card
    for oid, qty in quantities.items():
        card = cards[oid]
        if (
            not card.is_basic_land
            and card.max_copies is not None
            and qty > card.max_copies
        ):
            issue(
                "MAX_COPIES_EXCEEDED",
                f"{card.name}: {qty} copie totali, massimo {card.max_copies}.",
                card_name=card.name,
            )
        legality = getattr(card, f"legality_{fmt}", "not_legal")
        if legality == "banned":
            issue(
                "CARD_BANNED",
                f"{card.name} è bandita in {fmt.capitalize()}.",
                card_name=card.name,
            )
        elif legality != "legal":
            issue(
                "CARD_NOT_LEGAL",
                f"{card.name} non è legale in {fmt.capitalize()}.",
                card_name=card.name,
            )
    return DeckValidationReport(
        is_valid=not any(i.severity == "error" for i in issues),
        format_id=fmt,
        mainboard_count=main,
        sideboard_count=side,
        companion_count=companion,
        issues=issues,
    )


def compute_deck_analytics(entries) -> DeckAnalytics:
    curve = {
        key: {"creatures": 0, "spells": 0, "total": 0}
        for key in ["0", "1", "2", "3", "4", "5", "6+"]
    }
    pips = dict.fromkeys("WUBRGC", 0)
    sources = dict.fromkeys("WUBRGC", 0)
    types = dict.fromkeys(
        [
            "Creature",
            "Planeswalker",
            "Instant",
            "Sorcery",
            "Artifact",
            "Enchantment",
            "Battle",
            "Land",
        ],
        0,
    )
    lands = nonlands = 0
    cmc_sum = 0.0
    for card, board, qty in entries:
        if board != "main" or qty <= 0:
            continue
        front_type = (card.card_faces or [{}])[0].get("type_line") or (
            card.type_line or ""
        ).split("//")[0]
        is_land = "Land" in front_type
        # Type counts intentionally overlap for artifact creatures, enchantment creatures, etc.
        for type_name in types:
            if type_name in front_type:
                types[type_name] += qty
        if is_land:
            lands += qty
        else:
            nonlands += qty
            cmc = float(card.cmc or 0)
            cmc_sum += cmc * qty
            bucket = "6+" if cmc >= 6 else str(max(0, int(cmc)))
            curve[bucket]["creatures" if "Creature" in front_type else "spells"] += qty
            curve[bucket]["total"] += qty
        mana_cost = (card.card_faces or [{}])[0].get("mana_cost") or (
            card.mana_cost or ""
        ).split("//")[0]
        for symbol in re.findall(r"\{([^}]+)\}", mana_cost):
            for color in pips:
                if color in symbol:
                    pips[color] += qty
        for color in card.produced_mana or []:
            if color in sources:
                sources[color] += qty
    return DeckAnalytics(
        mana_curve=curve,
        avg_cmc_nonland=round(cmc_sum / nonlands, 2) if nonlands else 0,
        color_pip_distribution=pips,
        mana_source_distribution=sources,
        type_Counts=types,
        land_count=lands,
        nonland_count=nonlands,
    )


DECK_LINE = re.compile(
    r"^\s*(\d+)\s*x?\s+(.+?)(?:\s+\(([A-Za-z0-9]+)\)\s+([A-Za-z0-9\-★]+))?\s*$"
)


def parse_decklist_text(db, raw_text):
    board, seen_main = "main", False
    merged, unresolved = {}, []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            if seen_main and board == "main":
                board = "side"
            continue
        header = line.lower().rstrip(":")
        if header in ("deck", "main", "mainboard", "maindeck", "mazzo"):
            board = "main"
            continue
        if header in ("sideboard", "side", "sb"):
            board = "side"
            continue
        if header in ("companion", "compagno"):
            board = "companion"
            continue
        if line.startswith(("//", "#")):
            continue
        target = board
        if line.upper().startswith("SB:"):
            target, line = "side", line[3:].strip()
        match = DECK_LINE.match(line)
        if not match:
            # Common Arena metadata is harmless; malformed card rows must not vanish.
            if not line.lower().startswith(("name ", "about", "commander")):
                unresolved.append(line)
            continue
        qty, name = int(match[1]), match[2].strip()
        if qty <= 0:
            unresolved.append(line)
            continue
        card = resolve_card_by_name(db, name)
        if not card:
            unresolved.append(name)
        else:
            key = (card.oracle_id, target)
            merged[key] = (card, target, merged.get(key, (None, None, 0))[2] + qty)
        if target == "main":
            seen_main = True
        if board == "companion":
            board = "main"
    # Arena repeats the designated companion in the sideboard section. It is one card.
    for oid, target in list(merged):
        if target == "companion" and (oid, "side") in merged:
            card, _, side_qty = merged[(oid, "side")]
            companion_qty = merged[(oid, "companion")][2]
            if side_qty > companion_qty:
                merged[(oid, "side")] = (card, "side", side_qty - companion_qty)
            else:
                del merged[(oid, "side")]
    return list(merged.values()), unresolved


def export_decklist_formats(entries):
    main = [(c, q) for c, b, q in entries if b == "main" and q > 0]
    side = [(c, q) for c, b, q in entries if b in ("side", "companion") and q > 0]
    companion = [(c, q) for c, b, q in entries if b == "companion" and q > 0]

    def line(c, q, arena=False):
        name = c.name.split(" // ")[0]
        return f"{q} {name}" + (
            f" ({c.set_code.upper()}) {c.collector_number}"
            if arena and c.set_code and c.collector_number
            else ""
        )

    arena, mtgo = [], []
    if companion:
        arena += ["Companion"] + [line(c, q, True) for c, q in companion] + [""]
    arena += ["Deck"] + [line(c, q, True) for c, q in main]
    mtgo += [line(c, q) for c, q in main]
    if side:
        arena += ["", "Sideboard"] + [line(c, q, True) for c, q in side]
        mtgo += ["", "Sideboard"] + [line(c, q) for c, q in side]
    return "\n".join(arena), "\n".join(mtgo)
