from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from sqlalchemy import func
from app.models import (
    AIRun,
    Card,
    Deck,
    DeckCard,
    DeckArchive,
    DeckRevision,
    GuideJob,
    GuideVersion,
    utcnow,
)
from app.routers.cards import get_meta_stats_map
from app.schemas import (
    CardOut,
    DeckCardEntryIn,
    DeckCardOut,
    DeckCreateIn,
    DeckDetailOut,
    DeckExportOut,
    DeckImportIn,
    DeckSummaryOut,
    DeckUpdateIn,
)
from app.services.deck_validator import (
    compute_deck_analytics,
    export_decklist_formats,
    get_color_combination_label,
    parse_decklist_text,
    resolve_card_by_name,
    validate_deck_entries,
)

router = APIRouter(prefix="/api/decks", tags=["Decks"])


def _resolve_input_entries(
    db: Session, raw_entries: List[DeckCardEntryIn]
) -> List[Tuple[Card, str, int]]:
    aggregated: Dict[Tuple[str, str], Tuple[Card, int]] = {}
    for entry in raw_entries:
        if entry.quantity <= 0:
            continue
        card: Optional[Card] = None
        if entry.oracle_id:
            card = db.query(Card).filter(Card.oracle_id == entry.oracle_id).first()
        if not card and entry.card_name:
            card = resolve_card_by_name(db, entry.card_name)
        if not card:
            raise HTTPException(
                422, f"Carta non riconosciuta: {entry.card_name or entry.oracle_id}"
            )
        board = entry.board if entry.board in ("main", "side", "companion") else "main"
        key = (card.oracle_id, board)
        if key in aggregated:
            prev_c, prev_q = aggregated[key]
            aggregated[key] = (prev_c, prev_q + entry.quantity)
        else:
            aggregated[key] = (card, entry.quantity)
    return [(card, board, qty) for (_, board), (card, qty) in aggregated.items()]


def _build_deck_detail(db: Session, deck: Deck) -> DeckDetailOut:
    oracle_ids = [dc.oracle_id for dc in deck.cards]
    cards_map: Dict[str, Card] = {}
    if oracle_ids:
        db_cards = db.query(Card).filter(Card.oracle_id.in_(oracle_ids)).all()
        cards_map = {c.oracle_id: c for c in db_cards}

    resolved_tuples: List[Tuple[Card, str, int]] = []
    for dc in deck.cards:
        c_obj = cards_map.get(dc.oracle_id)
        if c_obj and dc.quantity > 0:
            resolved_tuples.append((c_obj, dc.board, dc.quantity))

    meta_map = get_meta_stats_map(
        db,
        deck.format_id,
        [c.oracle_id for c, _, _ in resolved_tuples],
        [c.name for c, _, _ in resolved_tuples],
    )

    cards_out: List[DeckCardOut] = []
    for dc in deck.cards:
        c_obj = cards_map.get(dc.oracle_id)
        if not c_obj or dc.quantity <= 0:
            continue
        c_out = CardOut.model_validate(c_obj)
        c_out.meta_info = (
            meta_map.get(c_obj.oracle_id)
            or meta_map.get(c_obj.name.lower())
            or meta_map.get(c_obj.name.split(" // ")[0].lower())
        )
        cards_out.append(
            DeckCardOut(
                id=dc.id,
                oracle_id=dc.oracle_id,
                card_name=c_obj.name,
                board=dc.board,
                quantity=dc.quantity,
                card=c_out,
            )
        )

    # Ordina per CMC crescente e poi nome
    cards_out.sort(key=lambda item: (item.card.cmc, item.card_name))

    validation = validate_deck_entries(deck.format_id, resolved_tuples)
    analytics = compute_deck_analytics(resolved_tuples)

    guide = dict(deck.guide_json) if deck.guide_json else None
    if guide:
        from app.services.guide_quality import archived_guide_warnings

        guide["rules_warnings"] = archived_guide_warnings(guide, resolved_tuples)
    return DeckDetailOut(
        id=deck.id,
        name=deck.name,
        format_id=deck.format_id,
        archetype=deck.archetype,
        colors=deck.colors or [],
        color_label=deck.color_label,
        description=deck.description,
        source=deck.source,
        guide_json=guide,
        created_at=deck.created_at,
        updated_at=deck.updated_at,
        cards=cards_out,
        validation=validation,
        analytics=analytics,
    )


@router.get("", response_model=List[DeckSummaryOut])
def list_decks(
    format_id: Optional[str] = Query(None),
    archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(Deck)
    archived_ids = db.query(DeckArchive.deck_id)
    q = q.filter(Deck.id.in_(archived_ids) if archived else ~Deck.id.in_(archived_ids))
    if format_id:
        q = q.filter(Deck.format_id == format_id.lower())
    decks = q.order_by(Deck.updated_at.desc()).all()
    ids = [d.id for d in decks]
    entries_by_deck: Dict[int, List[Tuple[Card, str, int]]] = {i: [] for i in ids}
    if ids:
        rows = (
            db.query(DeckCard, Card)
            .join(Card, Card.oracle_id == DeckCard.oracle_id)
            .filter(DeckCard.deck_id.in_(ids), DeckCard.quantity > 0)
        )
        for dc, card in rows:
            entries_by_deck[dc.deck_id].append((card, dc.board, dc.quantity))

    def counts(model) -> Dict[int, int]:
        if not ids:
            return {}
        return dict(
            db.query(model.deck_id, func.count())
            .filter(model.deck_id.in_(ids))
            .group_by(model.deck_id)
        )

    guide_counts, revision_counts = counts(GuideVersion), counts(DeckRevision)

    out: List[DeckSummaryOut] = []
    for d in decks:
        validation = validate_deck_entries(d.format_id, entries_by_deck[d.id])
        out.append(
            DeckSummaryOut(
                id=d.id,
                name=d.name,
                format_id=d.format_id,
                archetype=d.archetype,
                colors=d.colors or [],
                color_label=d.color_label,
                source=d.source,
                mainboard_count=validation.mainboard_count,
                sideboard_count=validation.sideboard_count,
                is_valid=validation.is_valid,
                updated_at=d.updated_at,
                archived=archived,
                guide_count=guide_counts.get(d.id, 0),
                revision_count=revision_counts.get(d.id, 0),
            )
        )
    return out


@router.post("", response_model=DeckDetailOut)
def create_deck(payload: DeckCreateIn, db: Session = Depends(get_db)):
    resolved = _resolve_input_entries(db, payload.cards)

    # Calcola automaticamente i colori dal mazzo se non passati
    inferred_colors: List[str] = list(payload.colors or [])
    if not inferred_colors and resolved:
        col_accum: List[str] = []
        for card, _, _ in resolved:
            col_accum.extend(card.colors or [])
        inferred_colors = col_accum
    sorted_cols, col_label = get_color_combination_label(inferred_colors)

    deck = Deck(
        name=payload.name.strip() or "Nuovo Mazzo Competitivo",
        format_id=payload.format_id.lower(),
        archetype=payload.archetype,
        colors=sorted_cols,
        color_label=payload.color_label or col_label,
        description=payload.description,
        source=payload.source,
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


@router.get("/{deck_id}", response_model=DeckDetailOut)
def get_deck(deck_id: int, db: Session = Depends(get_db)):
    deck = db.query(Deck).filter(Deck.id == deck_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Mazzo non trovato")
    return _build_deck_detail(db, deck)


@router.put("/{deck_id}", response_model=DeckDetailOut)
def update_deck(deck_id: int, payload: DeckUpdateIn, db: Session = Depends(get_db)):
    deck = db.query(Deck).filter(Deck.id == deck_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Mazzo non trovato")

    if payload.name is not None:
        deck.name = payload.name.strip() or deck.name
    if payload.format_id is not None:
        new_format = payload.format_id.lower()
        if new_format != deck.format_id:
            deck.guide_json = None
        deck.format_id = new_format
    if payload.archetype is not None:
        deck.archetype = payload.archetype
    if payload.description is not None:
        deck.description = payload.description

    if payload.cards is not None:
        resolved = _resolve_input_entries(db, payload.cards)
        before = sorted((c.oracle_id, c.board, c.quantity) for c in deck.cards)
        after = sorted((c.oracle_id, b, q) for c, b, q in resolved)
        if before != after:
            deck.guide_json = None
        db.query(DeckCard).filter(DeckCard.deck_id == deck.id).delete()
        col_accum: List[str] = []
        for card, board, qty in resolved:
            col_accum.extend(card.colors or [])
            db.add(
                DeckCard(
                    deck_id=deck.id,
                    oracle_id=card.oracle_id,
                    card_name=card.name,
                    board=board,
                    quantity=qty,
                )
            )
        sorted_cols, col_label = get_color_combination_label(
            payload.colors if payload.colors is not None else col_accum
        )
        deck.colors = sorted_cols
        deck.color_label = payload.color_label or col_label
    elif payload.colors is not None:
        sorted_cols, col_label = get_color_combination_label(payload.colors)
        deck.colors = sorted_cols
        deck.color_label = payload.color_label or col_label

    deck.updated_at = utcnow()
    db.flush()
    record_revision(db, deck)
    db.commit()
    db.refresh(deck)
    return _build_deck_detail(db, deck)


@router.delete("/{deck_id}")
def delete_deck(deck_id: int, db: Session = Depends(get_db)):
    deck = db.query(Deck).filter(Deck.id == deck_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Mazzo non trovato")
    db.query(DeckArchive).filter_by(deck_id=deck_id).delete()
    db.query(DeckRevision).filter_by(deck_id=deck_id).delete()
    db.query(GuideVersion).filter_by(deck_id=deck_id).update({"deck_id": None})
    db.query(AIRun).filter_by(deck_id=deck_id).update({"deck_id": None})
    db.query(GuideJob).filter(
        GuideJob.deck_id == deck_id, GuideJob.status.in_(["queued", "running"])
    ).update({"status": "cancelled", "finished_at": utcnow()})
    db.query(GuideJob).filter_by(deck_id=deck_id).update({"deck_id": None})
    db.delete(deck)
    db.commit()
    return {"status": "deleted", "deck_id": deck_id}


@router.post("/analyze")
def analyze_stateless_deck(
    payload: DeckCreateIn, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Valida e calcola curva/analytics in tempo reale senza necessità di salvare su DB."""
    resolved = _resolve_input_entries(db, payload.cards)
    validation = validate_deck_entries(payload.format_id, resolved)
    analytics = compute_deck_analytics(resolved)
    col_accum: List[str] = []
    for c, _, _ in resolved:
        col_accum.extend(c.colors or [])
    sorted_cols, col_label = get_color_combination_label(col_accum)
    arena_txt, mtgo_txt = export_decklist_formats(resolved)
    from app.services.deck_engine import analyze_list, structure_summary

    has_main = any(board == "main" for _, board, _ in resolved)
    competitive = analyze_list(db, resolved) if has_main else None
    if competitive:
        # How the list is built and which field archetypes are built the same way.
        competitive["structure"] = structure_summary(
            db, resolved, payload.format_id, payload.archetype
        )
    return {
        "colors": sorted_cols,
        "color_label": col_label,
        "validation": validation,
        "analytics": analytics,
        # Sources vs Karsten requirements, tapped lands, interaction and odds.
        "competitive": competitive,
        "export": {"arena_format": arena_txt, "mtgo_format": mtgo_txt},
    }


@router.post("/import")
def import_decklist(
    payload: DeckImportIn, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    resolved, unresolved = parse_decklist_text(db, payload.text)
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail="Nessuna carta riconosciuta. Usa righe come: 4 Lightning Bolt.",
        )
    if unresolved and payload.save_to_db:
        raise HTTPException(
            status_code=422,
            detail="Importazione annullata, carte non riconosciute: "
            + ", ".join(unresolved),
        )

    col_accum: List[str] = []
    for card, _, _ in resolved:
        col_accum.extend(card.colors or [])
    sorted_cols, col_label = get_color_combination_label(col_accum)

    deck_name = (
        payload.name or ""
    ).strip() or f"Imported {col_label} ({payload.format_id.capitalize()})"

    deck = Deck(
        name=deck_name,
        format_id=payload.format_id.lower(),
        archetype=payload.archetype,
        colors=sorted_cols,
        color_label=col_label,
        source="imported",
    )
    if payload.save_to_db:
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
        detail = _build_deck_detail(db, deck)
        return {
            "deck": detail,
            "unresolved_cards": unresolved,
        }

    # Modalità preview senza salvataggio
    validation = validate_deck_entries(payload.format_id, resolved)
    analytics = compute_deck_analytics(resolved)
    return {
        "cards": [
            {
                "oracle_id": c.oracle_id,
                "card_name": c.name,
                "board": b,
                "quantity": q,
                "card": CardOut.model_validate(c),
            }
            for c, b, q in resolved
        ],
        "colors": sorted_cols,
        "color_label": col_label,
        "validation": validation,
        "analytics": analytics,
        "unresolved_cards": unresolved,
    }


@router.get("/{deck_id}/export", response_model=DeckExportOut)
def export_deck(deck_id: int, db: Session = Depends(get_db)):
    deck = db.query(Deck).filter(Deck.id == deck_id).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Mazzo non trovato")
    oracle_ids = [dc.oracle_id for dc in deck.cards]
    cards_map = (
        {
            c.oracle_id: c
            for c in db.query(Card).filter(Card.oracle_id.in_(oracle_ids)).all()
        }
        if oracle_ids
        else {}
    )
    entries = [
        (cards_map[dc.oracle_id], dc.board, dc.quantity)
        for dc in deck.cards
        if dc.oracle_id in cards_map
    ]
    arena_str, mtgo_str = export_decklist_formats(entries)
    return DeckExportOut(arena_format=arena_str, mtgo_format=mtgo_str)


def deck_snapshot(db: Session, deck: Deck) -> Dict[str, Any]:
    # Explicit query avoids stale ORM collections after a bulk replacement.
    return {
        "name": deck.name,
        "format_id": deck.format_id,
        "archetype": deck.archetype,
        "description": deck.description,
        "cards": [
            {
                "oracle_id": c.oracle_id,
                "card_name": c.card_name,
                "board": c.board,
                "quantity": c.quantity,
            }
            for c in db.query(DeckCard)
            .filter_by(deck_id=deck.id)
            .order_by(DeckCard.oracle_id, DeckCard.board)
        ],
    }


def record_revision(db: Session, deck: Deck) -> None:
    snapshot = deck_snapshot(db, deck)
    last = (
        db.query(DeckRevision)
        .filter_by(deck_id=deck.id)
        .order_by(DeckRevision.id.desc())
        .first()
    )
    if not last or last.snapshot != snapshot:
        db.add(DeckRevision(deck_id=deck.id, snapshot=snapshot))


@router.put("/{deck_id}/archive")
def archive_deck(deck_id: int, archived: bool = True, db: Session = Depends(get_db)):
    if not db.get(Deck, deck_id):
        raise HTTPException(404, "Mazzo non trovato")
    row = db.get(DeckArchive, deck_id)
    if archived and not row:
        db.add(DeckArchive(deck_id=deck_id))
    elif not archived and row:
        db.delete(row)
    db.commit()
    return {"archived": archived}


@router.get("/{deck_id}/revisions")
def deck_revisions(deck_id: int, db: Session = Depends(get_db)):
    if not db.get(Deck, deck_id):
        raise HTTPException(404, "Mazzo non trovato")
    return [
        {"id": r.id, "created_at": r.created_at, "snapshot": r.snapshot}
        for r in db.query(DeckRevision)
        .filter_by(deck_id=deck_id)
        .order_by(DeckRevision.id.desc())
    ]


@router.post("/{deck_id}/restore/{revision_id}", response_model=DeckDetailOut)
def restore_revision(deck_id: int, revision_id: int, db: Session = Depends(get_db)):
    revision = db.query(DeckRevision).filter_by(id=revision_id, deck_id=deck_id).first()
    if not revision:
        raise HTTPException(404, "Versione non trovata")
    return update_deck(deck_id, DeckUpdateIn(**revision.snapshot), db)


@router.post("/{deck_id}/duplicate", response_model=DeckDetailOut)
def duplicate_deck(deck_id: int, db: Session = Depends(get_db)):
    deck = db.get(Deck, deck_id)
    if not deck:
        raise HTTPException(404, "Mazzo non trovato")
    snapshot = deck_snapshot(db, deck)
    snapshot["name"] += " - copia"
    return create_deck(DeckCreateIn(**snapshot), db)
