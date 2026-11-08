"""Deterministic deckbuilding facts for the generator, the critic and the UI.

Everything here is computed from stored tournament lists, Oracle text and Scryfall
tags: no AI and no estimates presented as observations.

- consensus_list: the archetype's "stock" 75 (Frank Karsten's aggregation method).
- field_model: the expected field, weighted by observed share, with interaction profiles.
- analyze_list: mana sources vs requirements, tapped lands, curve, interaction density
  and hypergeometric odds for a concrete 60/15.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import comb
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models import (
    Card,
    MetaArchetype,
    MetaArchetypeCard,
    MetaSnapshot,
    TournamentDecklist,
)
from app.services.card_knowledge import tags_for
from app.services.deck_validator import castable_mana_value, mana_value_of

WUBRG = "WUBRG"
BASIC_TYPES = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}

# Coloured sources needed to cast a spell on curve ~90% of the time in a 60-card deck
# (Frank Karsten, "How Many Colored Mana Sources Do You Need", 2018 update).
# Key: coloured pips of one colour -> {turn: sources}.
KARSTEN_60 = {
    1: {1: 14, 2: 13, 3: 12, 4: 11, 5: 10, 6: 9},
    2: {2: 21, 3: 18, 4: 16, 5: 15, 6: 14},
    3: {3: 23, 4: 20, 5: 19, 6: 17},
    4: {4: 24, 5: 22, 6: 20},
}

# Tag groups counted as interaction; a card counts once per group.
INTERACTION_GROUPS = {
    "rimozioni": ("removal", "removal-creature", "removal-planeswalker", "removal-exile", "burn"),
    "counter": ("counterspell",),
    "sweeper": ("sweeper",),
    "scarto": ("discard",),
    "rimozioni artefatti/incantesimi": ("removal-artifact", "removal-enchantment"),
    "hate al cimitero": ("hate-graveyard",),
    # Net card gain only: cantrips, loot and impulse-style selection are excluded.
    "vantaggio carte": ("card-advantage-net",),
}


def _is_one_for_one_card_flow(card: Card, card_tags: set) -> bool:
    """True when an instant/sorcery only replaces itself (cantrip, cycling, or 1-card look-at-top)
    without generating net card advantage."""
    if "cantrip" in card_tags:
        return True
    face0 = _faces(card)[0]
    type_line = face0.get("type_line") or ""
    if not any(t in type_line for t in ("Instant", "Sorcery")) or len(_faces(card)) > 1:
        return False
    text = (face0.get("oracle_text") or "").lower()
    if any(
        k in text
        for k in (
            "flashback",
            "escape",
            "rebound",
            "jump-start",
            "retrace",
            "buyback",
            "cipher",
            "harmonize",
            "you may play",
            "you may cast",
        )
    ):
        return False
    non_cycling = re.sub(r"cycling[^\n]*", "", text)
    if "cycling" in text and not re.search(
        r"\b(draw|put\b.*\binto your hand|investigate|connive|discover|cascade|return\b.*\bto your hand)\b",
        non_cycling,
    ):
        return True
    if re.search(r"put one (?:of them )?into your hand", non_cycling) and not re.search(
        r"\b(draw|put (?:two|three|four|up to two|up to three)|more than|investigate|connive)\b",
        non_cycling,
    ):
        return True
    return False


def _group_hit(card: Card, card_tags: set, group: str) -> bool:
    if not (card_tags & set(INTERACTION_GROUPS[group])):
        return False
    if group == "vantaggio carte" and _is_one_for_one_card_flow(card, card_tags):
        return False
    return True

CORE_INCLUSION_PCT = 80.0


def _legal(card: Card, fmt: str) -> bool:
    return getattr(card, f"legality_{fmt}", "not_legal") == "legal"


def _faces(card: Card) -> List[dict]:
    return card.card_faces or [
        {"type_line": card.type_line, "oracle_text": card.oracle_text, "mana_cost": card.mana_cost}
    ]


def land_face(card: Card) -> Optional[dict]:
    """The face that is a land: the card itself, or the back of a modal DFC."""
    faces = _faces(card)
    if "Land" in (faces[0].get("type_line") or ""):
        return faces[0]
    if card.layout == "modal_dfc":
        for face in faces[1:]:
            if "Land" in (face.get("type_line") or ""):
                return face
    return None


def is_land_card(card: Card) -> bool:
    """Front face is a land (MDFC spell//land count as spells with a land option)."""
    return "Land" in (_faces(card)[0].get("type_line") or "")


# ---------------------------------------------------------------------------
# Consensus list
# ---------------------------------------------------------------------------


@dataclass
class ConsensusCard:
    card: Card
    quantity: int
    inclusion_pct: float  # lists playing it in this board
    avg_copies: float  # among those lists


@dataclass
class Consensus:
    archetype: MetaArchetype
    lists_count: int
    main: List[ConsensusCard] = field(default_factory=list)
    side: List[ConsensusCard] = field(default_factory=list)

    @property
    def core(self) -> List[ConsensusCard]:
        return [c for c in self.main if c.inclusion_pct >= CORE_INCLUSION_PCT]

    @property
    def flex(self) -> List[ConsensusCard]:
        return [c for c in self.main if c.inclusion_pct < CORE_INCLUSION_PCT]

    def entries(self) -> List[Tuple[Card, str, int]]:
        return [(c.card, "main", c.quantity) for c in self.main] + [
            (c.card, "side", c.quantity) for c in self.side
        ]


def _aggregate(
    lists: Sequence[Dict[str, int]], size: int, allowed: Dict[str, int]
) -> Dict[str, int]:
    """Karsten's aggregate list: rank every (card, n-th copy) by how many lists play at
    least n copies, then keep the best `size` slots. `allowed` caps copies per card."""
    slots = []
    for oid in {o for deck in lists for o in deck}:
        cap = allowed.get(oid, 0)
        for n in range(1, min(cap, max(deck.get(oid, 0) for deck in lists)) + 1):
            slots.append((sum(1 for deck in lists if deck.get(oid, 0) >= n), n, oid))
    slots.sort(key=lambda s: (-s[0], s[1], s[2]))
    chosen: Counter = Counter()
    for _count, n, oid in slots:
        if sum(chosen.values()) >= size:
            break
        # Copies are taken in order; a 3rd copy never precedes the 2nd.
        if chosen[oid] == n - 1:
            chosen[oid] += 1
    return dict(chosen)


def consensus_list(db: Session, archetype: MetaArchetype) -> Optional[Consensus]:
    decks = (
        db.query(TournamentDecklist)
        .filter(
            TournamentDecklist.id.in_(archetype.decklist_ids or []),
            TournamentDecklist.is_complete.is_(True),
        )
        .all()
    )
    if not decks:
        return None
    mains, sides = [], []
    for deck in decks:
        main, side = Counter(), Counter()
        for row in deck.cards or []:
            (main if row["board"] == "main" else side)[row["oracle_id"]] += row["quantity"]
        mains.append(main)
        sides.append(side)

    ids = {o for d in mains + sides for o in d}
    cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(ids))}
    fmt = archetype.format_id

    def cap(oid: str) -> int:
        card = cards.get(oid)
        if not card or not _legal(card, fmt):
            return 0  # banned since the list was played, or unknown
        return 250 if card.max_copies is None else card.max_copies

    main = _aggregate(mains, 60, {o: cap(o) for o in ids})
    side = _aggregate(sides, 15, {o: max(0, cap(o) - main.get(o, 0)) for o in ids})

    def describe(chosen: Dict[str, int], boards: List[Counter]) -> List[ConsensusCard]:
        out = []
        for oid, qty in chosen.items():
            playing = [b[oid] for b in boards if b.get(oid)]
            out.append(
                ConsensusCard(
                    card=cards[oid],
                    quantity=qty,
                    inclusion_pct=round(100 * len(playing) / len(boards), 1),
                    avg_copies=round(sum(playing) / len(playing), 2) if playing else 0.0,
                )
            )
        return sorted(out, key=lambda c: (-c.inclusion_pct, -c.quantity, c.card.name))

    return Consensus(
        archetype=archetype,
        lists_count=len(decks),
        main=describe(main, mains),
        side=describe(side, sides),
    )


# ---------------------------------------------------------------------------
# Expected field
# ---------------------------------------------------------------------------


@dataclass
class FieldCard:
    name: str
    oracle_id: str
    expected_copies: float  # inclusion x average copies, per list
    inclusion_pct: float
    is_land: bool = False


@dataclass
class FieldArchetype:
    archetype: MetaArchetype
    lists_count: int
    core: List[FieldCard]
    interaction: Dict[str, float]  # group -> expected main copies per list
    interaction_cards: List[FieldCard]
    curve: Dict[str, float]  # castable MV bucket -> expected nonland main copies
    likely_sideboard: List[FieldCard]


def latest_snapshot(db: Session, fmt: str) -> Optional[MetaSnapshot]:
    return (
        db.query(MetaSnapshot)
        .filter(MetaSnapshot.format_id == fmt)
        .order_by(MetaSnapshot.fetched_at.desc())
        .first()
    )


def _bucket(mv: float) -> str:
    return "5+" if mv >= 5 else str(int(mv))


def field_model(db: Session, snapshot: MetaSnapshot, limit: int = 8) -> List[FieldArchetype]:
    archs = (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == snapshot.id)
        .order_by(MetaArchetype.meta_share_pct.desc())
        .limit(limit)
        .all()
    )
    usage = defaultdict(list)
    for row in db.query(MetaArchetypeCard).filter(
        MetaArchetypeCard.archetype_id.in_([a.id for a in archs])
    ):
        usage[row.archetype_id].append(row)
    ids = {u.oracle_id for rows in usage.values() for u in rows}
    cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(ids))}
    tags = tags_for(db, ids)

    out = []
    for arch in archs:
        rows = usage.get(arch.id, [])
        interaction: Dict[str, float] = dict.fromkeys(INTERACTION_GROUPS, 0.0)
        curve: Dict[str, float] = defaultdict(float)
        core, inter_cards, side = [], [], []
        for u in rows:
            card = cards.get(u.oracle_id)
            expected = u.main_inclusion_pct / 100 * u.main_avg_copies
            is_land = bool(card) and is_land_card(card)
            fc = FieldCard(u.card_name, u.oracle_id, round(expected, 2), u.main_inclusion_pct, is_land)
            if u.main_inclusion_pct >= CORE_INCLUSION_PCT:
                core.append(fc)
            if card and expected > 0 and not is_land_card(card):
                curve[_bucket(castable_mana_value(card))] += expected
                card_tags = set(tags.get(u.oracle_id, []))
                hit = False
                for group in INTERACTION_GROUPS:
                    if _group_hit(card, card_tags, group):
                        interaction[group] += expected
                        hit = hit or group != "vantaggio carte"
                if hit and expected >= 0.5:
                    inter_cards.append(fc)
            if u.side_inclusion_pct >= 25:
                side.append(
                    FieldCard(
                        u.card_name,
                        u.oracle_id,
                        round(u.side_inclusion_pct / 100 * u.side_avg_copies, 2),
                        u.side_inclusion_pct,
                        is_land,
                    )
                )
        out.append(
            FieldArchetype(
                archetype=arch,
                lists_count=arch.decklists_count or 0,
                core=sorted(core, key=lambda c: -c.expected_copies),
                interaction={k: round(v, 1) for k, v in interaction.items()},
                interaction_cards=sorted(inter_cards, key=lambda c: -c.expected_copies)[:10],
                curve={k: round(curve.get(k, 0.0), 1) for k in ["0", "1", "2", "3", "4", "5+"]},
                likely_sideboard=sorted(side, key=lambda c: -c.inclusion_pct)[:8],
            )
        )
    return out


# ---------------------------------------------------------------------------
# List analytics
# ---------------------------------------------------------------------------


def _pips(cost: str) -> Counter:
    """Strict coloured pips: hybrid, Phyrexian and two-brid symbols are flexible."""
    out: Counter = Counter()
    for symbol in re.findall(r"\{([^}]+)\}", cost or ""):
        if symbol in WUBRG:
            out[symbol] += 1
    return out


def _tapped_kind(text: str) -> str:
    t = (text or "").lower()
    if not re.search(r"enters( the battlefield)? tapped", t):
        return "untapped"
    if re.search(r"unless|if you don't|you may pay|if you control|if it's not your", t):
        return "conditional"
    return "tapped"


def fetch_colors(text: str, deck_lands: List[Tuple[Card, dict]]) -> set:
    """Colours a fetch can find among the lands actually in the deck."""
    m = re.search(r"search your library for (?:an? |up to \w+ )?(.+?) cards?", (text or ""), re.I)
    if not m:
        return set()
    phrase = m.group(1)
    wanted = [t for t in BASIC_TYPES if t in phrase]
    basic_only = "basic" in phrase.lower()
    if not wanted and not basic_only:
        return set()
    colors = set()
    for card, face in deck_lands:
        type_line = face.get("type_line") or ""
        if basic_only and not card.is_basic_land:
            continue
        if wanted and not any(t in type_line for t in wanted):
            continue
        colors.update(c for c in card.produced_mana or [] if c in WUBRG)
    return colors


def p_at_least_one(copies: int, seen: int, deck: int = 60) -> float:
    if copies <= 0:
        return 0.0
    return 1 - comb(deck - copies, seen) / comb(deck, seen)


def p_at_least(k: int, copies: int, seen: int, deck: int = 60) -> float:
    return sum(
        comb(copies, i) * comb(deck - copies, seen - i) for i in range(k, min(copies, seen) + 1)
    ) / comb(deck, seen)


def analyze_list(
    db: Session,
    entries: Iterable[Tuple[Card, str, int]],
    key_cards: Sequence[str] = (),
) -> dict:
    entries = [(c, b, q) for c, b, q in entries if q > 0]
    main = [(c, q) for c, b, q in entries if b == "main"]
    side = [(c, q) for c, b, q in entries if b == "side"]
    main_size = sum(q for _, q in main) or 60

    lands = [(c, q, land_face(c)) for c, q in main if land_face(c)]
    deck_lands = [(c, f) for c, _, f in lands]
    sources: Dict[str, float] = dict.fromkeys(WUBRG, 0)
    tapped = {"untapped": 0, "conditional": 0, "tapped": 0}
    untapped_cards: List[str] = []
    conditional_cards: List[str] = []
    tapped_cards: List[str] = []
    land_count = mdfc_count = 0
    for card, qty, face in lands:
        mdfc = not is_land_card(card)
        if mdfc:
            mdfc_count += qty
        else:
            land_count += qty
        produced = {c for c in card.produced_mana or [] if c in WUBRG}
        produced |= fetch_colors(face.get("oracle_text") or "", deck_lands)
        for color in produced:
            sources[color] += qty
        if not mdfc:
            kind = _tapped_kind(face.get("oracle_text") or "")
            tapped[kind] += qty
            if kind == "untapped":
                untapped_cards.append(f"{qty} {card.name}")
            elif kind == "conditional":
                conditional_cards.append(f"{qty} {card.name}")
            elif kind == "tapped":
                tapped_cards.append(f"{qty} {card.name}")

    # Requirement per colour: the most demanding (pips, turn) among castable faces.
    requirements: Dict[str, dict] = {}
    curve: Dict[str, int] = {k: 0 for k in ["0", "1", "2", "3", "4", "5", "6+"]}
    nonland_mv = []
    for card, qty in main:
        if is_land_card(card):
            continue
        mv = castable_mana_value(card)
        curve["6+" if mv >= 6 else str(int(mv))] += qty
        nonland_mv.extend([mv] * qty)
        costs = [f.get("mana_cost") for f in _faces(card) if f.get("mana_cost")] or [
            card.mana_cost or ""
        ]
        for cost in costs:
            # X spells are not cast with X=0: assume at least X=1 for the turn they matter.
            face_mv = mana_value_of(cost) + ("{X}" in cost)
            for color, n in _pips(cost).items():
                n = min(n, 4)
                turn = int(min(6, max(face_mv, n, 1)))
                need = KARSTEN_60[n][max(turn, n)]
                if need > requirements.get(color, {}).get("required", 0):
                    requirements[color] = {"required": need, "card": card.name, "turn": turn, "pips": n}

    colors_report = []
    for color in WUBRG:
        req = requirements.get(color)
        if not req and not sources[color]:
            continue
        colors_report.append(
            {
                "color": color,
                "sources": int(sources[color]),
                "required": req["required"] if req else 0,
                "driver": req["card"] if req else None,
                "driver_turn": req["turn"] if req else None,
                "driver_pips": req["pips"] if req else None,
                "deficit": max(0, (req["required"] if req else 0) - int(sources[color])),
            }
        )

    ids = [c.oracle_id for c, _, _ in entries]
    tags = tags_for(db, ids)

    def interaction(board: List[Tuple[Card, int]]) -> Dict[str, dict]:
        out = {}
        for group in INTERACTION_GROUPS:
            hits = [(c, q) for c, q in board if _group_hit(c, set(tags.get(c.oracle_id, [])), group)]
            if hits:
                out[group] = {
                    "copies": sum(q for _, q in hits),
                    "cards": [f"{q} {c.name}" for c, q in sorted(hits, key=lambda h: -h[1])],
                }
        return out

    total_lands = land_count  # MDFC are spells first; reported separately
    p_keep_7 = sum(p_exact(k, total_lands, 7, main_size) for k in range(2, 6))
    odds = {
        "lands_in_opening_7": round(7 * total_lands / main_size, 2),
        "p_2_to_5_lands_in_7": round(p_keep_7, 3),
        # London mulligan: the second hand is again 7 cards, one goes to the bottom, so
        # 2-5 lands in those 7 leave a 6-card hand with 2-4 lands. Independent draws.
        "p_2_to_5_lands_within_one_mulligan": round(1 - (1 - p_keep_7) ** 2, 3),
        "p_3_lands_by_t3_play": round(p_at_least(3, total_lands, 9, main_size), 3),
        "p_3_lands_by_t3_draw": round(p_at_least(3, total_lands, 10, main_size), 3),
        "p_4_lands_by_t4_play": round(p_at_least(4, total_lands, 10, main_size), 3),
        "copies": {
            str(n): {
                "opening_7": round(p_at_least_one(n, 7, main_size), 3),
                "by_t3_play": round(p_at_least_one(n, 9, main_size), 3),
                "by_t3_draw": round(p_at_least_one(n, 10, main_size), 3),
            }
            for n in (1, 2, 3, 4)
        },
    }
    key_odds = []
    wanted = {k.split(" // ")[0].casefold() for k in key_cards}
    for card, qty in main:
        if card.name.split(" // ")[0].casefold() in wanted:
            key_odds.append(
                {
                    "card": card.name,
                    "copies": qty,
                    "opening_7": round(p_at_least_one(qty, 7, main_size), 3),
                    "by_t3_draw": round(p_at_least_one(qty, 10, main_size), 3),
                }
            )

    return {
        "main_count": sum(q for _, q in main),
        "side_count": sum(q for _, q in side),
        "land_count": land_count,
        "mdfc_land_count": mdfc_count,
        "avg_mana_value_nonland": round(sum(nonland_mv) / len(nonland_mv), 2) if nonland_mv else 0,
        "curve": curve,
        "colors": colors_report,
        "tapped_lands": {
            **tapped,
            "untapped_cards": untapped_cards,
            "conditional_cards": conditional_cards,
            "always_tapped_cards": tapped_cards,
        },
        "interaction_main": interaction(main),
        "interaction_side": interaction(side),
        "odds": odds,
        "key_card_odds": key_odds,
        "notes": [
            "Fonti: solo terre (le MDFC con faccia terra contano come fonte); le fetch contano i colori delle terre che possono davvero cercare in questa lista.",
            "Requisiti: tabella Karsten per 60 carte (~90% di lanciare la carta più esigente nel turno del suo costo).",
        ],
    }


def p_exact(k: int, copies: int, seen: int, deck: int = 60) -> float:
    if k > copies or k > seen:
        return 0.0
    return comb(copies, k) * comb(deck - copies, seen - k) / comb(deck, seen)


def analytics_warnings(analysis: dict) -> List[str]:
    warnings = []
    for c in analysis["colors"]:
        if c["deficit"]:
            warnings.append(
                f"Fonti {c['color']}: {c['sources']} contro {c['required']} richieste da "
                f"{c['driver']} (turno {c['driver_turn']}, {c['driver_pips']} simbol{'o' if c['driver_pips'] == 1 else 'i'})."
            )
    if analysis["tapped_lands"]["tapped"] >= 6:
        warnings.append(
            f"{analysis['tapped_lands']['tapped']} terre entrano sempre tappate."
        )
    return warnings



# ---------------------------------------------------------------------------
# Structure: what a list is built to do, compared with the field's archetypes
# ---------------------------------------------------------------------------

STRUCTURE_LABELS = {
    "creatures": "creature",
    "avg_mv": "MV medio",
    "interaction": "interazione",
    "card_advantage": "vantaggio carte",
    "sweepers": "sweeper",
    "counters": "counter",
    "lands": "terre",
}
# Lands say little about the plan: they stay out of the similarity measure.
SIMILARITY_METRICS = ("creatures", "avg_mv", "interaction", "card_advantage", "sweepers", "counters")
# Requested archetype -> source category it can be checked against. Midrange, ramp and
# tempo have no category of their own in the sources; combo lists differ too much from
# each other (a creature combo and a spell combo) to be a yardstick.
ROLE_CATEGORY = {"control": "control", "aggro": "aggro"}
INTERACTION_CORE = ("rimozioni", "counter", "sweeper", "scarto")


def structure_profile(db: Session, entries: Iterable[Tuple[Card, str, int]]) -> Dict[str, float]:
    """Main-deck structure: threats, interaction (removal, counters, sweepers, discard),
    card advantage and curve height."""
    main = [(c, q) for c, b, q in entries if b == "main" and q > 0]
    nonland = [(c, q) for c, q in main if not is_land_card(c)]
    tags = tags_for(db, [c.oracle_id for c, _ in nonland])

    def copies(groups: Sequence[str]) -> int:
        return sum(
            q
            for c, q in nonland
            if any(_group_hit(c, set(tags.get(c.oracle_id, [])), g) for g in groups)
        )

    mvs = [castable_mana_value(c) for c, q in nonland for _ in range(q)]
    return {
        "creatures": sum(q for c, q in nonland if "Creature" in (_faces(c)[0].get("type_line") or "")),
        "avg_mv": round(sum(mvs) / len(mvs), 2) if mvs else 0.0,
        "interaction": copies(INTERACTION_CORE),
        "card_advantage": copies(("vantaggio carte",)),
        "sweepers": copies(("sweeper",)),
        "counters": copies(("counter",)),
        "lands": sum(q for c, q in main if is_land_card(c)),
    }


def structure_text(structure: Dict[str, float]) -> str:
    return ", ".join(f"{label} {structure[k]:g}" for k, label in STRUCTURE_LABELS.items())


@dataclass
class ArchetypeStructure:
    name: str
    category: str
    share: float
    structure: Dict[str, float]


def archetype_structures(db: Session, snapshot: MetaSnapshot) -> List[ArchetypeStructure]:
    """Structure of every archetype's consensus list, by observed share."""
    out = []
    archs = (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == snapshot.id)
        .order_by(MetaArchetype.meta_share_pct.desc())
    )
    for arch in archs:
        con = consensus_list(db, arch)
        if con:
            out.append(
                ArchetypeStructure(
                    arch.name,
                    (arch.category or "other").lower(),
                    arch.meta_share_pct or 0.0,
                    structure_profile(db, con.entries()),
                )
            )
    return out


def nearest_structures(
    structure: Dict[str, float], field: Sequence[ArchetypeStructure], n: int = 3
) -> List[Tuple[ArchetypeStructure, float]]:
    """Field archetypes whose consensus list is built most like this one.
    Euclidean distance on metrics scaled by their spread across the field."""
    if len(field) < 2:
        return []
    scale = {}
    for m in SIMILARITY_METRICS:
        values = [a.structure[m] for a in field]
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        scale[m] = sd or 1.0
    scored = [
        (a, round(sum(((structure[m] - a.structure[m]) / scale[m]) ** 2 for m in SIMILARITY_METRICS) ** 0.5, 2))
        for a in field
    ]
    return sorted(scored, key=lambda s: s[1])[:n]


def role_issues(
    requested: Optional[str],
    nearest: Sequence[Tuple[ArchetypeStructure, float]],
    field: Sequence[ArchetypeStructure],
) -> List[str]:
    """The requested plan is a constraint: flag lists built like another category."""
    category = ROLE_CATEGORY.get((requested or "").lower())
    if not category or not nearest or not any(a.category == category for a in field):
        return []
    if any(a.category == category for a, _ in nearest[:2]):
        return []
    closest = ", ".join(f"{a.name} ({a.category})" for a, _ in nearest[:2])
    same = [a.name for a in field if a.category == category][:3]
    return [
        f"Archetipo richiesto {requested}, ma per struttura (creature, curva, interazione, "
        f"vantaggio carte) la lista è più vicina a {closest} che ai {category} del meta "
        f"({', '.join(same)}). Ricostruisci la struttura o motiva perché questo {requested} è diverso."
    ]


_STRUCTURE_CACHE: Dict[tuple, List[ArchetypeStructure]] = {}


def field_structures(db: Session, snapshot: Optional[MetaSnapshot]) -> List[ArchetypeStructure]:
    """archetype_structures, cached per snapshot: the builder asks on every edit."""
    if not snapshot:
        return []
    key = (id(db.get_bind()), snapshot.id, str(snapshot.fetched_at))
    if key not in _STRUCTURE_CACHE:
        _STRUCTURE_CACHE.clear()
        _STRUCTURE_CACHE[key] = archetype_structures(db, snapshot)
    return _STRUCTURE_CACHE[key]


def structure_summary(
    db: Session, entries: List[Tuple[Card, str, int]], fmt: str, requested: Optional[str] = None
) -> Dict[str, object]:
    """Structure of a list, the field archetypes built most like it and, when a plan is
    requested, whether the list is built like that plan."""
    values = structure_profile(db, entries)
    main_size = sum(q for _, b, q in entries if b == "main")
    # A list still being built would be compared with finished ones: wait for 60 cards.
    field = field_structures(db, latest_snapshot(db, fmt)) if main_size >= 60 else []
    near = nearest_structures(values, field)
    return {
        "values": values,
        "nearest": [{"archetype": a.name, "category": a.category, "distance": d} for a, d in near],
        "requested": requested or "",
        "issues": role_issues(requested, near, field),
    }
