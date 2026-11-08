from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deck, GuideVersion, MatchRecord, QualityRating
from app.services import quality

router = APIRouter(prefix="/api/quality", tags=["Qualità"])


@router.get("/report")
def quality_report(format_id: str, db: Session = Depends(get_db)):
    if format_id not in ("standard", "pioneer", "modern"):
        raise HTTPException(400, "Formato non valido")
    return quality.report(db, format_id)


@router.get("/estimate")
def cost_estimate(
    skill: Literal["deck_generation", "deck_guide", "matchup_spot", "deck_improvement"],
    model_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Duration, tokens and (with a configured price) cost of the next run."""
    return quality.estimate(db, skill, model_id)


class RatingIn(BaseModel):
    target_kind: Literal["guide", "deck"]
    target_id: int
    depth: int = Field(ge=1, le=5)
    correctness: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=1000)


@router.post("/ratings")
def add_rating(payload: RatingIn, db: Session = Depends(get_db)):
    model = GuideVersion if payload.target_kind == "guide" else Deck
    if not db.get(model, payload.target_id):
        raise HTTPException(404, "Elemento da valutare non trovato")
    db.add(QualityRating(**payload.model_dump()))
    db.commit()
    return quality.ratings_for(db, payload.target_kind, [payload.target_id]).get(
        payload.target_id
    )


@router.get("/ratings")
def get_ratings(target_kind: Literal["guide", "deck"], target_id: int, db: Session = Depends(get_db)):
    return quality.ratings_for(db, target_kind, [target_id]).get(target_id)


class RecordIn(BaseModel):
    opponent_archetype: str = Field(min_length=1, max_length=128)
    games_won: int = Field(ge=0, le=3)
    games_lost: int = Field(ge=0, le=3)
    on_the_play: Optional[bool] = None
    played_on: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    event: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=1000)


def _record_out(r: MatchRecord):
    return {
        "id": r.id,
        "opponent_archetype": r.opponent_archetype,
        "games_won": r.games_won,
        "games_lost": r.games_lost,
        "on_the_play": r.on_the_play,
        "played_on": r.played_on,
        "event": r.event,
        "note": r.note,
    }


@router.get("/decks/{deck_id}/records")
def list_records(deck_id: int, db: Session = Depends(get_db)):
    if not db.get(Deck, deck_id):
        raise HTTPException(404, "Mazzo non trovato")
    rows = (
        db.query(MatchRecord)
        .filter(MatchRecord.deck_id == deck_id)
        .order_by(MatchRecord.played_on.desc(), MatchRecord.id.desc())
        .all()
    )
    return {"records": [_record_out(r) for r in rows], "summary": quality.record_summary(db, deck_id)}


@router.post("/decks/{deck_id}/records")
def add_record(deck_id: int, payload: RecordIn, db: Session = Depends(get_db)):
    deck = db.get(Deck, deck_id)
    if not deck:
        raise HTTPException(404, "Mazzo non trovato")
    if payload.games_won == payload.games_lost == 0:
        raise HTTPException(400, "Indica almeno un game giocato.")
    db.add(MatchRecord(deck_id=deck_id, format_id=deck.format_id, **payload.model_dump()))
    db.commit()
    return list_records(deck_id, db)


@router.delete("/records/{record_id}")
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.get(MatchRecord, record_id)
    if not record:
        raise HTTPException(404, "Risultato non trovato")
    deck_id = record.deck_id
    db.delete(record)
    db.commit()
    return list_records(deck_id, db)
