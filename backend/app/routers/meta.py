from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from app.database import get_db
from app.models import (
    Card,
    Deck,
    DeckCard,
    MetaArchetype,
    MetaArchetypeCard,
    MetaCardStat,
    MetaMatchup,
    MetaSnapshot,
    TournamentDecklist,
)
from app.routers.decks import _build_deck_detail, record_revision
from app.schemas import CardMetaInfo, CardOut
from app.services.deck_validator import parse_decklist_text, resolve_card_by_name
from app.services.meta_scraper import (
    decklist_label,
    run_meta_sync_all,
    run_meta_sync_for_format,
)

router = APIRouter(prefix="/api/meta", tags=["Metagame"])


@router.get("/{format_id}", response_model=None)
def get_format_meta(
    format_id: str, db: Session = Depends(get_db)
) -> Dict[str, Any] | JSONResponse:
    fmt = format_id.lower()
    if fmt not in ("standard", "pioneer", "modern"):
        raise HTTPException(status_code=400, detail=f"Formato non valido: {format_id}")

    latest_snap = (
        db.query(MetaSnapshot)
        .filter(MetaSnapshot.format_id == fmt)
        .order_by(MetaSnapshot.fetched_at.desc())
        .first()
    )

    if not latest_snap:
        # A scrape takes minutes: start it in background instead of holding the request.
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Metagame non ancora disponibile: sincronizzazione avviata, riprova tra qualche minuto."
            },
            background=BackgroundTask(run_meta_sync_for_format, fmt),
        )

    archetypes_q = (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == latest_snap.id)
        .order_by(MetaArchetype.tier.asc(), MetaArchetype.meta_share_pct.desc())
        .all()
    )

    matchups_q = (
        db.query(MetaMatchup).filter(MetaMatchup.snapshot_id == latest_snap.id).all()
    )

    card_stats_q = (
        db.query(MetaCardStat)
        .filter(MetaCardStat.snapshot_id == latest_snap.id)
        .order_by(MetaCardStat.overall_presence_pct.desc())
        .all()
    )

    archetypes_out: List[Dict[str, Any]] = []
    for a in archetypes_q:
        resolved_key_cards: List[Dict[str, Any]] = []
        for kc_name in a.key_cards or []:
            c_obj = resolve_card_by_name(db, kc_name)
            if c_obj:
                resolved_key_cards.append(
                    {
                        "oracle_id": c_obj.oracle_id,
                        "name": c_obj.name,
                        "mana_cost": c_obj.mana_cost,
                        "image_small": (c_obj.image_uris or {}).get("small")
                        or (c_obj.image_uris or {}).get("normal"),
                        "card": CardOut.model_validate(c_obj).model_dump(),
                    }
                )
            else:
                resolved_key_cards.append({"name": kc_name})

        archetypes_out.append(
            {
                "id": a.id,
                "name": a.name,
                "slug": a.slug,
                "category": a.category,
                "tier": a.tier,
                "colors": a.colors or [],
                "color_name": a.color_name,
                "meta_share_pct": a.meta_share_pct,
                "winrate_pct": a.winrate_pct,
                "matches_count": a.matches_count,
                "decklists_count": a.decklists_count,
                "key_cards": resolved_key_cards,
                "sample_decklists": a.sample_decklists or [],
                "source_url": a.source_url,
            }
        )

    matrix_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for m in matchups_q:
        if m.archetype_a_name not in matrix_map:
            matrix_map[m.archetype_a_name] = {}
        # The scraper never collects head-to-head results: every cell is a heuristic estimate.
        matrix_map[m.archetype_a_name][m.archetype_b_name] = {
            "winrate_pct": m.winrate_a_pct,
            "matches_count": 0,
            "estimate_kind": "heuristic",
        }

    oracle_ids_needed = [st.oracle_id for st in card_stats_q if st.oracle_id]
    cards_by_oracle: Dict[str, Card] = {}
    if oracle_ids_needed:
        for c_item in (
            db.query(Card).filter(Card.oracle_id.in_(oracle_ids_needed)).all()
        ):
            cards_by_oracle[c_item.oracle_id] = c_item

    top_cards_out: List[Dict[str, Any]] = []
    for st in card_stats_q:
        c_obj: Optional[Card] = (
            cards_by_oracle.get(st.oracle_id) if st.oracle_id else None
        )
        if not c_obj:
            c_obj = resolve_card_by_name(db, st.card_name)

        c_dump = None
        if c_obj:
            c_out = CardOut.model_validate(c_obj)
            c_out.meta_info = CardMetaInfo(
                overall_presence_pct=st.overall_presence_pct,
                main_presence_pct=st.main_presence_pct,
                main_avg_copies=st.main_avg_copies,
                side_presence_pct=st.side_presence_pct,
                side_avg_copies=st.side_avg_copies,
                top_archetypes=st.top_archetypes or [],
            )
            c_dump = c_out.model_dump()

        top_cards_out.append(
            {
                "id": st.id,
                "card_name": st.card_name,
                "oracle_id": c_obj.oracle_id if c_obj else st.oracle_id,
                "overall_presence_pct": st.overall_presence_pct,
                "main_presence_pct": st.main_presence_pct,
                "main_avg_copies": st.main_avg_copies,
                "side_presence_pct": st.side_presence_pct,
                "side_avg_copies": st.side_avg_copies,
                "top_archetypes": st.top_archetypes or [],
                "card": c_dump,
            }
        )

    return {
        "snapshot": {
            "id": latest_snap.id,
            "format_id": latest_snap.format_id,
            "source": latest_snap.source,
            "fetched_at": latest_snap.fetched_at,
            "total_decks_analyzed": latest_snap.total_decks_analyzed,
            "notes": latest_snap.notes,
            "period_label": latest_snap.period_label,
            "coverage_pct": latest_snap.coverage_pct,
            "decklists_count": latest_snap.decklists_count,
            "quality_status": latest_snap.quality_status,
            "quality_warnings": latest_snap.quality_warnings or [],
        },
        "archetypes": archetypes_out,
        "matchup_matrix": matrix_map,
        "top_cards": top_cards_out,
    }


@router.post("/sync")
async def trigger_meta_sync(
    background_tasks: BackgroundTasks,
    format_id: Optional[str] = None,
):
    if format_id and format_id.lower() in ("standard", "pioneer", "modern"):
        res = await run_meta_sync_for_format(format_id.lower())
        return res
    background_tasks.add_task(run_meta_sync_all)
    return {
        "status": "started",
        "message": "Sincronizzazione Meta per tutti i formati avviata.",
    }


@router.get("/{format_id}/consensus-lists")
def consensus_lists(format_id: str, limit: int = 8, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Current consensus 75 of the most played archetypes, as importable text.

    Replaces hand-written sample lists, which went stale with every set and ban."""
    from app.services import deck_engine

    snap = deck_engine.latest_snapshot(db, format_id.lower())
    if not snap:
        return []
    out = []
    archs = (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == snap.id)
        .order_by(MetaArchetype.meta_share_pct.desc())
    )
    for arch in archs:
        if len(out) >= max(1, min(limit, 20)):
            break
        con = deck_engine.consensus_list(db, arch)
        if not con:
            continue
        lines = ["Deck", *(f"{c.quantity} {c.card.name}" for c in con.main)]
        if con.side:
            lines += ["", "Sideboard", *(f"{c.quantity} {c.card.name}" for c in con.side)]
        out.append(
            {
                "archetype_id": arch.id,
                "name": arch.name,
                "meta_share_pct": arch.meta_share_pct,
                "lists_count": con.lists_count,
                "text": "\n".join(lines),
            }
        )
    return out


@router.get("/{format_id}/archetypes/{archetype_id}")
def get_archetype_detail(
    format_id: str, archetype_id: int, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Observed card usage across the archetype's collected lists, plus the lists themselves."""
    arch = db.get(MetaArchetype, archetype_id)
    if not arch or arch.format_id != format_id.lower():
        raise HTTPException(404, "Archetipo non trovato")
    usage = (
        db.query(MetaArchetypeCard)
        .filter_by(archetype_id=arch.id)
        .order_by(
            MetaArchetypeCard.main_inclusion_pct.desc(),
            MetaArchetypeCard.side_inclusion_pct.desc(),
        )
        .all()
    )
    cards = {
        c.oracle_id: c
        for c in db.query(Card).filter(Card.oracle_id.in_([u.oracle_id for u in usage]))
    } if usage else {}
    decks = (
        db.query(TournamentDecklist)
        .filter(TournamentDecklist.id.in_(arch.decklist_ids or []))
        .order_by(TournamentDecklist.played_on.desc())
        .all()
    )
    return {
        "id": arch.id,
        "name": arch.name,
        "decklists_count": arch.decklists_count or 0,
        "cards": [
            {
                "oracle_id": u.oracle_id,
                "card_name": u.card_name,
                "type_line": cards[u.oracle_id].type_line if u.oracle_id in cards else "",
                "mana_cost": cards[u.oracle_id].mana_cost if u.oracle_id in cards else "",
                "main_inclusion_pct": u.main_inclusion_pct,
                "main_avg_copies": u.main_avg_copies,
                "side_inclusion_pct": u.side_inclusion_pct,
                "side_avg_copies": u.side_avg_copies,
            }
            for u in usage
        ],
        "decklists": [
            {
                "id": d.id,
                "title": d.deck_title,
                "pilot": d.pilot,
                "event": d.event_name,
                "placement": d.placement,
                "played_on": d.played_on,
            }
            for d in decks
        ],
    }


@router.post("/{format_id}/load-archetype-deck/{archetype_id}")
def load_archetype_sample_deck(
    format_id: str,
    archetype_id: int,
    decklist_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    arch = db.query(MetaArchetype).filter(MetaArchetype.id == archetype_id).first()
    if not arch or arch.format_id != format_id.lower():
        raise HTTPException(404, "Archetipo non trovato")

    if decklist_id is not None:
        if decklist_id not in (arch.decklist_ids or []):
            raise HTTPException(404, "Lista non associata a questo archetipo")
        source = db.get(TournamentDecklist, decklist_id)
        cards = {
            c.oracle_id: c
            for c in db.query(Card).filter(
                Card.oracle_id.in_([c["oracle_id"] for c in source.cards])
            )
        }
        resolved = [
            (cards[c["oracle_id"]], c["board"], c["quantity"])
            for c in source.cards
            if c["oracle_id"] in cards
        ]
        unresolved = [c["card_name"] for c in source.cards if c["oracle_id"] not in cards]
        sample = {
            "name": decklist_label(arch.name, source.deck_title, source.pilot),
            "event": f"{source.event_name} #{source.placement}, {source.played_on}",
            "pilot": source.pilot,
        }
    else:
        if not arch.sample_decklists:
            raise HTTPException(404, "Sample decklist non disponibile per questo archetipo")
        sample = arch.sample_decklists[0]
        resolved, unresolved = parse_decklist_text(db, sample.get("decklist_text", ""))
    if not resolved or unresolved:
        raise HTTPException(
            422,
            "Sample non importato: lista vuota o carte non riconosciute. "
            + ", ".join(unresolved),
        )
    sample_name = sample.get("name", f"{arch.name} ({format_id.capitalize()})")

    # Import is a new working copy; never overwrite an edited tournament deck.
    deck = Deck(
        name=sample_name,
        format_id=format_id.lower(),
        archetype=arch.category,
        colors=arch.colors or [],
        color_label=arch.color_name,
        description=f"Copia da {sample.get('event', 'Metagame')} - {sample.get('pilot', 'pilota non specificato')}",
        source="meta_sample",
    )
    db.add(deck)
    db.flush()

    for card, board, qty in resolved:
        db.add(
            DeckCard(
                deck_id=deck.id,
                oracle_id=card.oracle_id,
                card_name=card.name,
                board=board,
                quantity=qty,
            )
        )
    db.flush()
    record_revision(db, deck)
    db.commit()
    db.refresh(deck)
    return _build_deck_detail(db, deck)
