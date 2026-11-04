from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import GuideVersion, Card
from app.services.guide_quality import archived_guide_warnings
from app.services.guide_images import load_guide_images
from app.services.guide_pdf import render_guide_pdf

router = APIRouter(prefix="/api/guides", tags=["Guide library"])


@router.get("")
def list_guides(
    format_id: str | None = None,
    deck_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(GuideVersion)
    if format_id:
        q = q.filter_by(format_id=format_id)
    if deck_id:
        q = q.filter_by(deck_id=deck_id)
    return [
        {
            "id": g.id,
            "deck_id": g.deck_id,
            "deck_name": g.deck_name,
            "format_id": g.format_id,
            "model_id": g.model_id,
            "created_at": g.created_at,
            "weighted_winrate_pct": g.guide_json.get("meta_estimate", {}).get(
                "weighted_winrate_pct"
            ),
        }
        for g in q.order_by(GuideVersion.created_at.desc()).all()
    ]


def reviewed_guide(db, version):
    ids = [c.get("oracle_id") for c in version.deck_snapshot if c.get("oracle_id")]
    cards = {
        c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(ids)).all()
    }
    entries = [
        (cards[x["oracle_id"]], x["board"], x["quantity"])
        for x in version.deck_snapshot
        if x.get("oracle_id") in cards
    ]
    guide = dict(version.guide_json)
    guide["rules_warnings"] = archived_guide_warnings(guide, entries)
    return guide, cards


def get_version(db, guide_id):
    version = db.get(GuideVersion, guide_id)
    if not version:
        raise HTTPException(404, "Guida non trovata")
    return version


@router.get("/{guide_id}")
def get_guide(guide_id: int, db: Session = Depends(get_db)):
    g = get_version(db, guide_id)
    guide, _ = reviewed_guide(db, g)
    return {
        "id": g.id,
        "deck_id": g.deck_id,
        "deck_name": g.deck_name,
        "guide": guide,
        "deck_snapshot": g.deck_snapshot,
        "created_at": g.created_at,
    }


@router.get("/{guide_id}/pdf")
def export_guide_pdf(guide_id: int, db: Session = Depends(get_db)):
    g = get_version(db, guide_id)
    guide, cards = reviewed_guide(db, g)
    images = load_guide_images(cards.values())
    return Response(
        render_guide_pdf(guide, g.deck_name, g.format_id, g.deck_snapshot, images),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="aetherdeck-guide-{guide_id}.pdf"'
        },
    )


@router.delete("/{guide_id}")
def delete_guide(guide_id: int, db: Session = Depends(get_db)):
    from app.models import Deck

    g = get_version(db, guide_id)
    deck_id = g.deck_id
    db.delete(g)
    db.flush()
    if deck_id:
        deck = db.get(Deck, deck_id)
        # Only preserve a guide as current when it describes this exact list.
        if deck and deck.guide_json == g.guide_json:
            deck.guide_json = None
    db.commit()
    return {"status": "deleted"}
