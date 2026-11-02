from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Card, Format, SetModel
from app.schemas import BannedCardOut, FormatDetailOut, FormatOut, SetOut
from app.services.scryfall_sync import ensure_default_formats

router = APIRouter(prefix="/api/formats", tags=["Formats"])


def _get_legality_col(format_id: str):
    fmt = format_id.lower()
    if fmt == "standard":
        return Card.legality_standard
    if fmt == "pioneer":
        return Card.legality_pioneer
    if fmt == "modern":
        return Card.legality_modern
    raise HTTPException(status_code=400, detail=f"Formato non supportato: {format_id}")


def _get_set_legality_col(format_id: str):
    fmt = format_id.lower()
    if fmt == "standard":
        return SetModel.is_standard_legal
    if fmt == "pioneer":
        return SetModel.is_pioneer_legal
    if fmt == "modern":
        return SetModel.is_modern_legal
    raise HTTPException(status_code=400, detail=f"Formato non supportato: {format_id}")


@router.get("", response_model=List[FormatOut])
def list_formats(db: Session = Depends(get_db)):
    ensure_default_formats(db)
    formats = db.query(Format).all()
    order_map = {"standard": 0, "pioneer": 1, "modern": 2}
    formats.sort(key=lambda f: order_map.get(f.id, 99))

    out: List[FormatOut] = []
    for f in formats:
        leg_col = _get_legality_col(f.id)
        set_col = _get_set_legality_col(f.id)
        legal_cards = (
            db.query(func.count(Card.oracle_id)).filter(leg_col == "legal").scalar()
            or 0
        )
        banned_cards = (
            db.query(func.count(Card.oracle_id)).filter(leg_col == "banned").scalar()
            or 0
        )
        legal_sets = (
            db.query(func.count(SetModel.code)).filter(set_col.is_(True)).scalar() or 0
        )
        out.append(
            FormatOut(
                id=f.id,
                name=f.name,
                description=f.description,
                min_mainboard=f.min_mainboard,
                max_sideboard=f.max_sideboard,
                max_copies=f.max_copies,
                legal_sets_count=legal_sets,
                legal_cards_count=legal_cards,
                banned_cards_count=banned_cards,
            )
        )
    return out


@router.get("/{format_id}", response_model=FormatDetailOut)
def get_format_detail(format_id: str, db: Session = Depends(get_db)):
    ensure_default_formats(db)
    fmt_id = format_id.lower()
    fmt = db.query(Format).filter(Format.id == fmt_id).first()
    if not fmt:
        raise HTTPException(
            status_code=404, detail=f"Formato '{format_id}' non trovato"
        )

    leg_col = _get_legality_col(fmt_id)
    set_col = _get_set_legality_col(fmt_id)

    legal_sets_q = (
        db.query(SetModel)
        .filter(set_col.is_(True))
        .order_by(SetModel.released_at.desc())
        .all()
    )
    banned_cards_q = (
        db.query(Card).filter(leg_col == "banned").order_by(Card.name.asc()).all()
    )
    legal_cards_count = (
        db.query(func.count(Card.oracle_id)).filter(leg_col == "legal").scalar() or 0
    )

    return FormatDetailOut(
        id=fmt.id,
        name=fmt.name,
        description=fmt.description,
        min_mainboard=fmt.min_mainboard,
        max_sideboard=fmt.max_sideboard,
        max_copies=fmt.max_copies,
        legal_sets_count=len(legal_sets_q),
        legal_cards_count=legal_cards_count,
        banned_cards_count=len(banned_cards_q),
        legal_sets=[SetOut.model_validate(s) for s in legal_sets_q],
        banned_cards=[
            BannedCardOut(
                oracle_id=c.oracle_id,
                name=c.name,
                mana_cost=c.mana_cost,
                type_line=c.type_line,
                set_code=c.set_code,
                image_uris=c.image_uris or {},
            )
            for c in banned_cards_q
        ],
    )
