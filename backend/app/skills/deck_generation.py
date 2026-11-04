"""Meta-aware deck generation.

1. Starting point: the consensus 75 of a meta archetype, or the user's thesis (brew)
   with two consensus references: the closest by colours and the closest by plan.
   The structure of every field archetype (creatures, curve, interaction, card
   advantage) shows the model what the requested plan looks like in this format, and
   the final list is checked against it.
2. Expected field: archetypes weighted by observed share, with interaction profiles.
3. AI build with full Oracle text, then deterministic checks and repairs.
4. Deterministic analytics on the final list (sources vs requirements, odds...).
5. Strategic critic with a different mandate; one revision only when it finds
   real problems or deterministic checks fail.
"""

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.models import AIRun, Card, Deck, DeckCard, MetaArchetype, MetaCardStat, SetModel
from app.routers.decks import _build_deck_detail, record_revision
from app.services import deck_engine
from app.services.ai_provider import get_active_ai_provider, get_skill_model_and_config
from app.services.card_knowledge import rulings_for
from app.services.deck_validator import (
    castable_with_colors,
    get_color_combination_label,
    resolve_card_by_name,
    validate_deck_entries,
)
from app.services.guide_quality import (
    evidence_context,
    key,
    require_fresh_catalog,
    validate_swaps,
)
from app.services.scryfall_sync import sort_colors_wubrg
from app.skills.common import archetype_summary, load_skill_prompt
from app.skills.schemas import (
    AIDeckCriticOutput,
    AIDeckGenerationOutput,
    AIDeckGenerationRequest,
)

log = logging.getLogger("uvicorn.error")

BASIC_BY_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
PLAN_TARGETS = 5  # top field archetypes every list needs a sideboard plan for
FIELD_SIZE = 8
POOL_SPELLS = 200
POOL_LANDS = 50
OPPONENT_CARDS = 120


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def oracle_text(card: Card) -> str:
    faces = card.card_faces or []
    if len(faces) > 1:
        text = " // ".join(
            f"{f.get('name')} {f.get('mana_cost') or ''} ({f.get('type_line') or ''}): {f.get('oracle_text') or ''}"
            for f in faces
        )
    else:
        text = card.oracle_text or ""
    return " ".join(text.split())


def card_line(card: Card, stat: Optional[MetaCardStat] = None, prefix: str = "") -> str:
    stats = ""
    if card.power is not None and card.toughness is not None:
        stats += f" {card.power}/{card.toughness}"
    if card.loyalty:
        stats += f" fedeltà {card.loyalty}"
    badge = ""
    if stat:
        badge = (
            f" [formato: main {stat.main_presence_pct:.1f}% ×{stat.main_avg_copies:.1f}"
            f", side {stat.side_presence_pct:.1f}% ×{stat.side_avg_copies:.1f}]"
        )
    return f"- {prefix}{card.name} | {card.mana_cost or '—'} | {card.type_line}{stats}{badge} | {oracle_text(card)}"


@dataclass
class GenerationContext:
    text: str
    field_text: str
    base: Optional[MetaArchetype]
    consensus: Optional[deck_engine.Consensus]
    references: List[deck_engine.Consensus]
    field: List[deck_engine.FieldArchetype]
    plan_targets: List[str]
    allowed_colors: Set[str]
    build_around: List[Card] = field(default_factory=list)
    reference_roles: Dict[int, str] = field(default_factory=dict)  # archetype id -> why
    structures: List[deck_engine.ArchetypeStructure] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return "meta" if self.consensus else "brew"


def field_text_block(snapshot, field_model: List[deck_engine.FieldArchetype], all_shares: float) -> str:
    if not snapshot:
        return "CAMPO ATTESO: metagame non disponibile. Dichiara l'incertezza e non inventare quote."
    source = snapshot.source or "n/d"
    if not snapshot.period_label or snapshot.period_label not in source:
        source += f", periodo {snapshot.period_label or 'n/d'}"
    header = (
        f"CAMPO ATTESO (fonte {source}, "
        f"{snapshot.decklists_count or 0} liste complete, copertura {snapshot.coverage_pct or 0}%"
        f"; quota fuori dagli archetipi elencati: {max(0.0, round(100 - all_shares, 1))}%). "
        "Valori per lista = inclusione × copie medie osservate nelle liste dell'archetipo."
    )
    blocks = [header]
    for i, f in enumerate(field_model, 1):
        core = ", ".join(
            f"{c.name} ×{c.expected_copies:g}" for c in f.core if not c.is_land
        )
        inter = ", ".join(f"{k} {v:g}" for k, v in f.interaction.items() if v >= 0.5)
        curve = " ".join(f"{k}:{v:g}" for k, v in f.curve.items() if v)
        threats = ", ".join(f"{c.name} ×{c.expected_copies:g}" for c in f.interaction_cards)
        side = ", ".join(f"{c.name} ({c.inclusion_pct:g}% liste)" for c in f.likely_sideboard)
        blocks.append(
            f"{i}. {archetype_summary(f.archetype)}\n"
            f"   Core (≥80% liste): {core or 'n/d'}\n"
            f"   Interazione attesa per lista: {inter or 'scarsa'}\n"
            f"   Curva non-terre per MV: {curve or 'n/d'}\n"
            f"   Interazione principale: {threats or 'n/d'}\n"
            f"   Sideboard probabile: {side or 'n/d'}"
        )
    return "\n".join(blocks)


def _reference_archetypes(
    db: Session, snapshot, colors: Set[str], requested: Optional[str]
) -> List[Tuple[MetaArchetype, str]]:
    """Two references for a brew: the closest by colours (cards already tested in those
    colours) and the closest by plan (what the requested archetype plays in this
    format). Colours alone would hand a "control" brew the stock list of an aggro deck."""
    archs = list(db.query(MetaArchetype).filter(MetaArchetype.snapshot_id == snapshot.id))
    category = deck_engine.ROLE_CATEGORY.get((requested or "").lower())

    def colour_score(a: MetaArchetype, weight: float) -> Optional[float]:
        a_cols = set(a.colors or [])
        if not colors:
            return a.meta_share_pct
        overlap = len(a_cols & colors)
        if not overlap:
            return None
        return a.meta_share_pct + weight * (overlap - len(a_cols - colors) / 2)

    picks: List[Tuple[MetaArchetype, str]] = []
    by_colour = sorted(
        ((sc, a) for a in archs if (sc := colour_score(a, 30)) is not None), key=lambda x: -x[0]
    )
    if by_colour:
        a = by_colour[0][1]
        same = category and (a.category or "").lower() == category
        picks.append((a, "per colori e piano" if same else f"per colori (piano {a.category or 'n/d'})"))
    if category and not any((a.category or "").lower() == category for a, _ in picks):
        same_plan = [a for a in archs if (a.category or "").lower() == category]
        # Colour overlap still matters, but less than the share: the plan comes first.
        scored = sorted(
            (
                (sc if (sc := colour_score(a, 10)) is not None else a.meta_share_pct - 10, a)
                for a in same_plan
            ),
            key=lambda x: -x[0],
        )
        if scored:
            picks.append((scored[0][1], f"per piano ({category})"))
    for _, a in by_colour[1:]:
        if len(picks) >= 2:
            break
        if all(a.id != p.id for p, _ in picks):
            picks.append((a, f"per colori (piano {a.category or 'n/d'})"))
    return picks


def consensus_block(con: deck_engine.Consensus, with_oracle: bool, role: str = "") -> str:
    a = con.archetype
    lines = [
        f"{a.name}{f' [riferimento {role}]' if role else ''}: piano {a.category or 'n/d'}, "
        f"quota {a.meta_share_pct}%, {con.lists_count} liste complete. "
        "Aggregazione deterministica delle liste (metodo Karsten): ogni copia entra se la giocano più liste."
    ]
    for label, cards in (("MAIN", con.main), ("SIDE", con.side)):
        lines.append(f"{label} ({sum(c.quantity for c in cards)}):")
        for c in cards:
            tag = "CORE" if label == "MAIN" and c.inclusion_pct >= deck_engine.CORE_INCLUSION_PCT else "flex"
            info = f"{c.quantity} {c.card.name} [{tag}: {c.inclusion_pct:g}% liste, media {c.avg_copies:g} copie]"
            lines.append(
                f"  {info} | {c.card.mana_cost or '—'} | {c.card.type_line} | {oracle_text(c.card)}"
                if with_oracle
                else f"  {info}"
            )
    return "\n".join(lines)


def structures_block(structures: List[deck_engine.ArchetypeStructure], requested: Optional[str]) -> str:
    if not structures:
        return ""
    category = deck_engine.ROLE_CATEGORY.get((requested or "").lower())
    lines = [
        "=== STRUTTURA DEGLI ARCHETIPI DEL CAMPO (calcolata dalle liste di consenso, solo main) ===",
        "Creature = copie di creature; interazione = rimozioni, counter, sweeper e scarto; "
        "vantaggio carte = carte che fanno guadagnare carte (tag Scryfall, esclusi cantrip, loot e selezione).",
    ]
    if category:
        lines.append(
            f"Archetipo richiesto: {requested}. Le liste '{category}' sotto mostrano come si gioca questo piano "
            "nel formato: scegli consapevolmente a quale famiglia somiglia la tua (per esempio pochi bersagli e "
            "molti counter/sweeper, oppure attrito con minacce resilienti) e dichiaralo nella strategia."
        )
    elif requested:
        lines.append(
            f"Archetipo richiesto: {requested}. Le fonti non hanno una categoria '{requested}': posiziona la lista "
            "tra le strutture sotto e dichiara nella strategia a quali somiglia."
        )
    for a in structures:
        mark = "→ " if category and a.category == category else "  "
        lines.append(f"{mark}{a.name} ({a.category}, {a.share:g}%): {deck_engine.structure_text(a.structure)}")
    return "\n".join(lines)


def structure_report(
    db: Session, entries: List[Tuple[Card, str, int]], ctx: "GenerationContext", requested: Optional[str]
) -> Tuple[Dict[str, Any], List[str]]:
    """The list's own structure, the field archetypes it resembles and, for a brew with
    a requested plan, whether it is built like that plan at all."""
    values = deck_engine.structure_profile(db, entries)
    near = deck_engine.nearest_structures(values, ctx.structures)
    issues = [] if ctx.consensus else deck_engine.role_issues(requested, near, ctx.structures)
    return {
        "values": values,
        "nearest": [
            {"archetype": a.name, "category": a.category, "distance": d} for a, d in near
        ],
        "requested": requested or "",
    }, issues


def structure_line(report: Dict[str, Any]) -> str:
    near = ", ".join(f"{n['archetype']} ({n['category']})" for n in report["nearest"])
    return (
        f"Struttura: {deck_engine.structure_text(report['values'])}."
        + (f" Per struttura somiglia di più a: {near}." if near else "")
    )


def analysis_text(analysis: dict) -> str:
    colors = "; ".join(
        f"{c['color']} {c['sources']} fonti / {c['required']} richieste"
        + (f" (da {c['driver']}, turno {c['driver_turn']})" if c["driver"] else "")
        for c in analysis["colors"]
    )
    curve = " ".join(f"{k}:{v}" for k, v in analysis["curve"].items() if v)
    inter = lambda block: "; ".join(  # noqa: E731
        f"{k} {v['copies']} ({', '.join(v['cards'])})" for k, v in block.items()
    ) or "nessuna"
    odds = analysis["odds"]
    tapped = analysis["tapped_lands"]
    return (
        f"Terre {analysis['land_count']} (+{analysis['mdfc_land_count']} MDFC con faccia terra); "
        f"MV medio non-terre {analysis['avg_mana_value_nonland']}; curva {curve}.\n"
        f"Fonti per colore: {colors or 'n/d'}.\n"
        f"Terre: {tapped['untapped']} stappate, {tapped['conditional']} condizionali, {tapped['tapped']} sempre tappate.\n"
        f"Interazione main: {inter(analysis['interaction_main'])}.\n"
        f"Interazione side: {inter(analysis['interaction_side'])}.\n"
        f"Probabilità: 2-5 terre in 7 carte {odds['p_2_to_5_lands_in_7']:.0%} "
        f"({odds['p_2_to_5_lands_within_one_mulligan']:.0%} entro un mulligan); "
        f"3 terre entro il turno 3 {odds['p_3_lands_by_t3_play']:.0%} on the play / {odds['p_3_lands_by_t3_draw']:.0%} on the draw."
    )


def build_context(db: Session, req: AIDeckGenerationRequest) -> GenerationContext:
    fmt = req.format_id
    leg_col = getattr(Card, f"legality_{fmt}")
    snapshot = deck_engine.latest_snapshot(db, fmt)

    base = None
    if req.base_archetype_id is not None:
        base = db.get(MetaArchetype, req.base_archetype_id)
        if not base or not snapshot or base.snapshot_id != snapshot.id:
            raise ValueError(
                "Archetipo di partenza non presente nel metagame corrente: aggiorna la pagina e riprova."
            )

    build_cards = [resolve_card_by_name(db, n) for n in req.build_around_cards]
    allowed: Set[str] = set(req.colors)
    consensus = deck_engine.consensus_list(db, base) if base else None
    if base and not consensus:
        raise ValueError(f"Nessuna lista completa disponibile per {base.name}: sincronizza il metagame.")
    if consensus:
        allowed |= set(base.colors or [])
        # Splash cards of the stock list stay legal for the validator.
        for c in consensus.main + consensus.side:
            if not castable_with_colors(c.card, allowed):
                allowed |= set(c.card.colors or [])
    for card in build_cards:
        allowed |= set(card.colors or [])

    field_model = deck_engine.field_model(db, snapshot, FIELD_SIZE) if snapshot else []
    all_shares = sum(
        a.meta_share_pct
        for a in db.query(MetaArchetype).filter(MetaArchetype.snapshot_id == snapshot.id)
    ) if snapshot else 0.0
    plan_targets = [f.archetype.name for f in field_model[:PLAN_TARGETS]]

    references: List[deck_engine.Consensus] = []
    reference_roles: Dict[int, str] = {}
    if snapshot and not consensus:
        for a, role in _reference_archetypes(db, snapshot, allowed, req.archetype):
            ref = deck_engine.consensus_list(db, a)
            if ref:
                references.append(ref)
                reference_roles[a.id] = role
    structures = deck_engine.field_structures(db, snapshot)

    stats = (
        {s.oracle_id: s for s in db.query(MetaCardStat).filter(MetaCardStat.snapshot_id == snapshot.id) if s.oracle_id}
        if snapshot
        else {}
    )

    # Opponents' key cards with Oracle text: the model reasons on facts, not memory.
    opp_ids: List[str] = []
    for f in field_model:
        for c in f.interaction_cards + f.core + f.likely_sideboard:
            if not c.is_land and c.oracle_id not in opp_ids:
                opp_ids.append(c.oracle_id)
    opp_ids = opp_ids[:OPPONENT_CARDS]
    opp_cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(opp_ids))}
    field_text = field_text_block(snapshot, field_model, all_shares)
    opp_lines = [card_line(opp_cards[oid]) for oid in opp_ids if oid in opp_cards]

    shown: Set[str] = set(opp_ids)
    sections: List[str] = []
    if consensus:
        sections.append(
            "=== PUNTO DI PARTENZA: LISTA DI CONSENSO ===\n" + consensus_block(consensus, with_oracle=True)
        )
        shown |= {c.card.oracle_id for c in consensus.main + consensus.side}
    else:
        ref_blocks = []
        for ref in references:
            analysis = deck_engine.analyze_list(db, ref.entries())
            ref_blocks.append(
                consensus_block(ref, with_oracle=False, role=reference_roles.get(ref.archetype.id, ""))
                + "\n  Densità: "
                + analysis_text(analysis).replace("\n", "\n  ")
            )
        sections.append(
            "=== PUNTO DI PARTENZA: BREW DALLA TESI DELL'UTENTE ===\n"
            "Liste di riferimento (densità e carte già testate, non vincoli). Un riferimento scelto solo per "
            "colori può avere un piano diverso da quello richiesto: prendine le carte che servono al tuo piano, "
            "non la struttura né le copie.\n"
            + ("\n\n".join(ref_blocks) if ref_blocks else "Nessuna lista di riferimento compatibile.")
        )

    if build_cards:
        rulings = rulings_for(db, [c.oracle_id for c in build_cards])
        lines = []
        for c in build_cards:
            lines.append(card_line(c, stats.get(c.oracle_id), prefix="[OBBLIGATORIA NEL MAIN] "))
            for r in rulings.get(c.oracle_id, [])[:6]:
                lines.append(f"    ruling {r.get('published_at')}: {r.get('comment')}")
            shown.add(c.oracle_id)
        sections.append("=== CARTE BUILD-AROUND RICHIESTE ===\n" + "\n".join(lines))

    # Candidate pool: cards observed in this format, castable in the allowed colours.
    observed = (
        db.query(Card).filter(leg_col == "legal", Card.oracle_id.in_(list(stats))).all() if stats else []
    )
    spells, lands = [], []
    for c in observed:
        if deck_engine.is_land_card(c):
            if c.is_basic_land:
                continue
            produced = set(c.produced_mana or [])
            if allowed and produced and not (produced & allowed) and not (set(c.color_identity or []) <= allowed):
                continue
            lands.append(c)
        elif not allowed or castable_with_colors(c, allowed):
            spells.append(c)
    spells.sort(key=lambda c: -stats[c.oracle_id].overall_presence_pct)
    lands.sort(key=lambda c: -stats[c.oracle_id].overall_presence_pct)
    pool_lines = [
        card_line(c, stats[c.oracle_id]) if c.oracle_id not in shown else f"- {c.name} (testo sopra)"
        for c in spells[:POOL_SPELLS]
    ]
    sections.append(
        f"=== POOL: CARTE OSSERVATE NEL FORMATO, LANCIABILI NEI COLORI ({len(pool_lines)}) ===\n"
        "Percentuali = presenza nel formato ponderata per quota. Base consigliata, non un limite: carte legali fuori dal pool sono ammesse se ne conosci il testo Oracle esatto e le motivi.\n"
        + "\n".join(pool_lines)
    )

    if allowed:
        catalog_lands = (
            db.query(Card)
            .filter(leg_col == "legal", Card.type_line.contains("Land"), Card.is_basic_land.is_(False))
            .all()
        )
        known = {c.oracle_id for c in lands}
        for c in sorted(catalog_lands, key=lambda c: c.name):
            ident = set(c.color_identity or [])
            if c.oracle_id in known or not ident or not ident <= allowed or len(lands) >= POOL_LANDS:
                continue
            lands.append(c)
    land_lines = [
        card_line(c, stats.get(c.oracle_id)) + ("" if c.oracle_id in stats else " [non osservata nel meta]")
        for c in lands[:POOL_LANDS]
    ]
    basics = [BASIC_BY_COLOR[c] for c in sort_colors_wubrg(list(allowed)) if c in BASIC_BY_COLOR] or list(
        BASIC_BY_COLOR.values()
    )
    sections.append(
        "=== TERRE NON BASE CANDIDATE ===\n" + "\n".join(land_lines)
        + f"\nTerre base disponibili (copie illimitate): {', '.join(basics)}"
    )
    sections.append(
        "=== REQUISITI DI FONTI COLORATE (calcolati dall'app, 60 carte, ~90% di lanciare in curva; Karsten) ===\n"
        + "\n".join(
            f"{pips} simbol{'o' if pips == 1 else 'i'} dello stesso colore: "
            + ", ".join(f"turno {t} → {n} fonti" for t, n in row.items())
            for pips, row in deck_engine.KARSTEN_60.items()
        )
        + "\nLe fetch contano solo per i colori che possono cercare; le terre che entrano tappate costano tempo."
    )

    banned = [n for (n,) in db.query(Card.name).filter(leg_col == "banned").order_by(Card.name)]
    set_col = getattr(SetModel, f"is_{fmt}_legal")
    sets_count = db.query(SetModel).filter(set_col.is_(True)).count()
    header = (
        f"=== FORMATO {fmt.upper()} ===\n"
        f"Set legali: {sets_count}. Banlist (rifiutate dal validatore): {', '.join(banned) or 'nessuna'}.\n"
        f"Archetipi principali per cui serve un piano di sideboard: {', '.join(plan_targets) or 'n/d'}."
    )
    opp_section = (
        "=== TESTI ORACLE DELLE CARTE CHIAVE AVVERSARIE ===\n" + "\n".join(opp_lines) if opp_lines else ""
    )
    struct_section = structures_block(structures, None if consensus else req.archetype)
    text = "\n\n".join(s for s in [header, field_text, struct_section, opp_section, *sections] if s)
    return GenerationContext(
        text=text,
        field_text=field_text,
        base=base,
        consensus=consensus,
        references=references,
        field=field_model,
        plan_targets=plan_targets,
        allowed_colors=allowed,
        build_around=build_cards,
        reference_roles=reference_roles,
        structures=structures,
    )


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------


def hard_errors(
    db: Session,
    fmt: str,
    out: AIDeckGenerationOutput,
    build_around_cards: Sequence[str],
    allowed_colors: Optional[Set[str]] = None,
) -> List[str]:
    """Rules violations: the list cannot be saved while any of these remain."""
    leg_attr = f"legality_{fmt}"
    errors: List[str] = []
    allowed = set(allowed_colors or [])

    main_cnt = sum(max(0, s.quantity) for s in out.mainboard)
    side_cnt = sum(max(0, s.quantity) for s in out.sideboard)
    if main_cnt != 60:
        errors.append(f"Il Mainboard ha {main_cnt} carte invece di esattamente 60.")
    if side_cnt != 15:
        errors.append(f"La Sideboard ha {side_cnt} carte invece di esattamente 15.")

    combined: Dict[str, Tuple[Card, int]] = {}
    for label, slots in (("Mainboard", out.mainboard), ("Sideboard", out.sideboard)):
        for slot in slots:
            if slot.quantity <= 0:
                continue
            card = resolve_card_by_name(db, slot.card_name)
            if not card:
                errors.append(f"[{label}] Carta inesistente nel database Scryfall: '{slot.card_name}'.")
                continue
            status = getattr(card, leg_attr, "not_legal")
            if status == "banned":
                errors.append(f"[{label}] VIOLAZIONE BANLIST: '{card.name}' è BANDITA in {fmt.upper()}.")
            elif status != "legal":
                errors.append(f"[{label}] CARTA NON LEGALE: '{card.name}' non è legale in {fmt.upper()} (stato: {status}).")
            if allowed and not castable_with_colors(card, allowed):
                errors.append(
                    f"[{label}] FUORI COLORE: '{card.name}' ({card.mana_cost}) richiede colori diversi da quelli richiesti ({''.join(sort_colors_wubrg(list(allowed)))})."
                )
            prev = combined.get(card.oracle_id, (card, 0))
            combined[card.oracle_id] = (prev[0], prev[1] + slot.quantity)

    for card, total in combined.values():
        if not card.is_basic_land and card.max_copies is not None and total > card.max_copies:
            errors.append(
                f"VIOLAZIONE LIMITE COPIE: '{card.name}' è presente in {total} copie totali tra Main e Side (massimo consentito: {card.max_copies})."
            )

    for name in build_around_cards:
        card = resolve_card_by_name(db, name)
        if card and getattr(card, leg_attr, "not_legal") == "legal":
            if not any(key(s.card_name) == key(card.name) and s.quantity > 0 for s in out.mainboard):
                errors.append(
                    f"CARTA BUILD-AROUND MANCANTE: '{card.name}' DEVE essere inclusa nel Mainboard."
                )
    return errors


def resolve_entries(db: Session, out: AIDeckGenerationOutput) -> List[Tuple[Card, str, int]]:
    merged: Dict[Tuple[str, str], Tuple[Card, str, int]] = {}
    for board, slots in (("main", out.mainboard), ("side", out.sideboard)):
        for slot in slots:
            card = resolve_card_by_name(db, slot.card_name)
            slot.card_name = card.name
            prior = merged.get((card.oracle_id, board), (card, board, 0))
            merged[(card.oracle_id, board)] = (card, board, prior[2] + slot.quantity)
    return list(merged.values())


def plan_issues(
    out: AIDeckGenerationOutput,
    entries: List[Tuple[Card, str, int]],
    ctx: GenerationContext,
) -> List[str]:
    """Checks on the reasoning the list must carry: deltas and sideboard plans."""
    issues: List[str] = []
    if ctx.consensus:
        names: Dict[str, str] = {}
        stock: Counter = Counter()
        for c in ctx.consensus.main + ctx.consensus.side:
            k = (key(c.card.name), "main" if c in ctx.consensus.main else "side")
            stock[k] += c.quantity
            names[k[0]] = c.card.name
        final: Counter = Counter()
        for card, board, qty in entries:
            final[(key(card.name), board)] += qty
            names[key(card.name)] = card.name
        diffs = {k: final[k] - stock[k] for k in set(stock) | set(final) if final[k] != stock[k]}
        declared: Counter = Counter()
        for d in out.deltas:
            declared[(key(d.card_name), d.board)] += d.change
            names.setdefault(key(d.card_name), d.card_name)
        for k, diff in sorted(diffs.items()):
            label = f"{names[k[0]]} ({k[1]})"
            if k not in declared:
                issues.append(f"Differenza non motivata rispetto al consenso: {diff:+d} {label}.")
            elif declared[k] != diff:
                issues.append(f"Delta di {label} dichiarato {declared[k]:+d}, nella lista è {diff:+d}.")
        for k in declared:
            if k not in diffs and declared[k]:
                issues.append(f"Delta dichiarato per {names[k[0]]} ({k[1]}), ma la lista coincide con il consenso.")

    plans = {key(p.opponent_archetype): p for p in out.matchup_plans}
    for name in ctx.plan_targets:
        plan = plans.get(key(name))
        if not plan:
            issues.append(f"Manca il piano di sideboard contro {name}.")
            continue
        for err in validate_swaps(plan.model_dump(), entries, "sideboard_in", "sideboard_out"):
            issues.append(f"Piano contro {name}: {err}")
    return issues


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _list_with_oracle(entries: List[Tuple[Card, str, int]]) -> str:
    out = []
    for board, label in (("main", "MAIN"), ("side", "SIDE")):
        rows = [(c, q) for c, b, q in entries if b == board]
        out.append(f"{label} ({sum(q for _, q in rows)}):")
        out.extend(f"  {q} {c.name} | {c.mana_cost or '—'} | {c.type_line} | {oracle_text(c)}" for c, q in rows)
    return "\n".join(out)


def _starting_point(ctx: GenerationContext) -> Dict[str, Any]:
    if ctx.consensus:
        con = ctx.consensus
        return {
            "mode": "meta",
            "archetype": con.archetype.name,
            "archetype_id": con.archetype.id,
            "meta_share_pct": con.archetype.meta_share_pct,
            "lists_count": con.lists_count,
            "main": [
                {"card_name": c.card.name, "quantity": c.quantity, "inclusion_pct": c.inclusion_pct, "core": c.inclusion_pct >= deck_engine.CORE_INCLUSION_PCT}
                for c in con.main
            ],
            "side": [
                {"card_name": c.card.name, "quantity": c.quantity, "inclusion_pct": c.inclusion_pct}
                for c in con.side
            ],
        }
    return {
        "mode": "brew",
        "references": [
            {
                "archetype": r.archetype.name,
                "meta_share_pct": r.archetype.meta_share_pct,
                "lists_count": r.lists_count,
                "category": r.archetype.category or "",
                "role": ctx.reference_roles.get(r.archetype.id, ""),
            }
            for r in ctx.references
        ],
    }


def run_deck_generation_skill(
    db: Session, req: AIDeckGenerationRequest, progress=None
) -> Dict[str, Any]:
    start_ts = time.time()

    def step(phase: str) -> None:
        # Called outside try blocks so that a cancellation is never swallowed.
        if progress:
            progress(phase)

    step("context")
    require_fresh_catalog(db)
    fmt = req.format_id.lower()
    provider = get_active_ai_provider(db)
    cfg = get_skill_model_and_config(db, "deck_generation", req.model_id)
    model_id = cfg["model_id"]
    prompt_ver, gen_sys = load_skill_prompt("deck_generation", cfg["prompt_version"])
    _, repair_sys = load_skill_prompt("deck_repair", get_skill_model_and_config(db, "deck_repair")["prompt_version"])
    _, critic_sys = load_skill_prompt("deck_critic", get_skill_model_and_config(db, "deck_critic", model_id)["prompt_version"])
    _, revision_sys = load_skill_prompt("deck_revision")

    for name in req.build_around_cards:
        card = resolve_card_by_name(db, name)
        if not card or getattr(card, f"legality_{fmt}", "not_legal") != "legal":
            raise ValueError(f"Build-around non riconosciuta o non legale: {name}")

    ctx = build_context(db, req)
    calls = 0

    def ask(system: str, prompt: str, model):
        nonlocal calls
        calls += 1
        return provider.generate_structured(
            model_id=model_id, system_instruction=system, user_prompt=prompt, response_model=model
        )

    request_block = (
        "RICHIESTA:\n"
        f"- Formato: {fmt.upper()}\n"
        f"- Punto di partenza: {('lista di consenso di ' + ctx.base.name) if ctx.base else 'brew dalla tesi del giocatore'}\n"
        f"- Archetipo desiderato: {(ctx.base.category if ctx.base else req.archetype) or 'scelta ottimale per il campo'}\n"
        f"- Colori: {''.join(sort_colors_wubrg(list(ctx.allowed_colors))) or 'liberi'} ({req.color_preset_name or 'auto'})\n"
        f"- Build-around: {', '.join(req.build_around_cards) or 'nessuna'}\n"
        f"- Obiettivo e vincoli del giocatore: {req.prompt or 'la lista più competitiva possibile contro il campo atteso.'}"
    )
    base_prompt = evidence_context(db, fmt) + "\n" + request_block + "\n\n" + ctx.text
    max_retries = max(1, int(cfg.get("max_retries", 3)))

    def until_valid(out: AIDeckGenerationOutput) -> Tuple[AIDeckGenerationOutput, List[str]]:
        errors = hard_errors(db, fmt, out, req.build_around_cards, ctx.allowed_colors)
        attempt = 0
        while errors and attempt < max_retries:
            attempt += 1
            step("repair")
            prompt = (
                f"IL VALIDATORE DEL FORMATO {fmt.upper()} HA RIFIUTATO LA LISTA (tentativo {attempt}):\n"
                + "\n".join("- " + e for e in errors)
                + f"\n\nLISTA DA CORREGGERE (JSON):\n{out.model_dump_json(indent=1)}\n\n{base_prompt}"
            )
            try:
                out = ask(repair_sys, prompt, AIDeckGenerationOutput)
            except Exception as exc:  # noqa: BLE001 - provider failure: keep the last errors
                log.warning("deck_generation repair %s failed: %s", attempt, type(exc).__name__)
                break
            errors = hard_errors(db, fmt, out, req.build_around_cards, ctx.allowed_colors)
        return out, errors

    step("generation")
    out, errors = until_valid(ask(gen_sys, base_prompt, AIDeckGenerationOutput))
    if errors:
        raise ValueError("Generazione non salvata: " + "; ".join(errors))
    requested = None if ctx.base else req.archetype

    def checks(out: AIDeckGenerationOutput):
        entries = resolve_entries(db, out)
        analysis = deck_engine.analyze_list(db, entries, key_cards=req.build_around_cards)
        structure, role = structure_report(db, entries, ctx, requested)
        analysis["structure"] = structure
        return entries, analysis, plan_issues(out, entries, ctx) + role

    entries, analysis, issues = checks(out)

    step("analysis")
    critic: Optional[AIDeckCriticOutput] = None
    critic_prompt = (
        evidence_context(db, fmt)
        + "\n"
        + request_block
        + "\n\n"
        + ctx.field_text
        + ("\n\n=== LISTA DI CONSENSO DI PARTENZA ===\n" + consensus_block(ctx.consensus, False) if ctx.consensus else "")
        + "\n\n=== LISTA PROPOSTA CON TESTI ORACLE ===\n"
        + _list_with_oracle(entries)
        + "\n\n=== ANALISI DETERMINISTICA (calcolata dall'app) ===\n"
        + analysis_text(analysis)
        + "\n"
        + structure_line(analysis["structure"])
        + ("\n\n" + structures_block(ctx.structures, requested) if ctx.structures else "")
        + "\n\n=== VERIFICHE DETERMINISTICHE NON SUPERATE ===\n"
        + ("\n".join("- " + i for i in issues) or "nessuna")
        + "\n\n=== PROPOSTA DEL COSTRUTTORE (JSON) ===\n"
        + out.model_dump_json(indent=1)
    )
    step("critic")
    try:
        critic = ask(critic_sys, critic_prompt, AIDeckCriticOutput)
    except Exception as exc:  # noqa: BLE001 - the list is already valid: a failed review is not fatal
        log.warning("deck_critic failed: %s", type(exc).__name__)

    revision = {"attempted": False, "applied": False, "note": ""}
    needs_revision = bool(issues) or bool(
        critic
        and (
            critic.verdict == "da_rivedere"
            or critic.oracle_errors
            # Concrete swaps are motivated recommendations: the builder weighs them.
            or critic.swaps
            or any(i.severity == "alta" for i in critic.issues)
        )
    )
    if needs_revision:
        step("revision")
        revision["attempted"] = True
        prompt = (
            "=== REVISIONE STRATEGICA ===\n"
            + (critic.model_dump_json(indent=1) if critic else "non disponibile")
            + "\n\n=== VERIFICHE DETERMINISTICHE NON SUPERATE ===\n"
            + ("\n".join("- " + i for i in issues) or "nessuna")
            + "\n\n=== ANALISI DETERMINISTICA DELLA LISTA ATTUALE ===\n"
            + analysis_text(analysis)
            + "\n"
            + structure_line(analysis["structure"])
            + f"\n\n=== PROPOSTA ATTUALE (JSON) ===\n{out.model_dump_json(indent=1)}\n\n"
            + base_prompt
        )
        try:
            revised, rev_errors = until_valid(ask(revision_sys, prompt, AIDeckGenerationOutput))
            if rev_errors:
                revision["note"] = "La revisione violava le regole del formato: resta la lista precedente."
            else:
                out = revised
                entries, analysis, issues = checks(out)
                revision["applied"] = True
        except Exception as exc:  # noqa: BLE001 - the previous list is valid and stays
            log.warning("deck_revision failed: %s", type(exc).__name__)
            revision["note"] = "Revisione non riuscita: resta la lista precedente."

    if ctx.base:
        out.base_archetype = ctx.base.name
        if key(ctx.base.name) not in key(out.deck_name):
            out.deck_name = f"{ctx.base.name} — {out.deck_name}"
    else:
        out.base_archetype = ""

    step("save")
    report = validate_deck_entries(fmt, entries)
    if not report.is_valid:
        raise ValueError("Generazione non salvata: " + "; ".join(i.message for i in report.issues))
    warnings = deck_engine.analytics_warnings(analysis) + issues

    sorted_cols, col_label = get_color_combination_label(
        [c for card, _, _ in entries for c in (card.colors or [])]
    )
    saved = None
    if req.save_deck:
        deck = Deck(
            name=out.deck_name,
            format_id=fmt,
            archetype=(ctx.base.category if ctx.base else out.archetype).lower(),
            colors=sorted_cols,
            color_label=col_label,
            description=out.strategy_overview,
            source="ai_generated",
        )
        db.add(deck)
        db.flush()
        for card, board, qty in entries:
            db.add(DeckCard(deck_id=deck.id, oracle_id=card.oracle_id, card_name=card.name, board=board, quantity=qty))
        db.flush()
        record_revision(db, deck)
        db.commit()
        db.refresh(deck)
        saved = _build_deck_detail(db, deck)

    starting_point = _starting_point(ctx)
    duration_ms = int((time.time() - start_ts) * 1000)
    db.add(
        AIRun(
            skill_name="deck_generation",
            prompt_version=prompt_ver,
            model_id=model_id,
            provider=provider.provider_name,
            usage_json=dict(getattr(provider, "usage", None) or {}) or None,
            format_id=fmt,
            deck_id=saved.id if saved else None,
            validation_attempts=calls,
            duration_ms=duration_ms,
            input_summary=req.model_dump(),
            output_json={
                "generation": out.model_dump(),
                "starting_point": starting_point,
                "analysis": analysis,
                "critic": critic.model_dump() if critic else None,
                "revision": revision,
                "warnings": warnings,
            },
        )
    )
    db.commit()
    return {
        "ai_result": out,
        "deck": saved,
        "starting_point": starting_point,
        "analysis": analysis,
        "critic": critic,
        "revision": revision,
        "warnings": warnings,
        "meta": {
            "skill": "deck_generation",
            "prompt_version": prompt_ver,
            "model_id": model_id,
            "provider": provider.provider_name,
            "validation_attempts": calls,
            "ai_calls": calls,
            "duration_ms": duration_ms,
        },
    }


def context_preview(db: Session, req: AIDeckGenerationRequest) -> str:
    """The exact evidence the generator receives (used by tests and diagnostics)."""
    return build_context(db, req).text

