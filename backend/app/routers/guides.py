from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import GuideVersion, Card
from app.services.guide_quality import reflection_copy_errors
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from urllib.parse import urlparse
import httpx
from io import BytesIO
from PIL import Image as PILImage
from app.config import settings
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
    guide["rules_warnings"] = reflection_copy_errors(guide, entries)
    return guide, cards


@lru_cache(maxsize=256)
def fetch_card_image(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cards.scryfall.io":
        return None
    try:
        with httpx.Client(
            timeout=4,
            follow_redirects=False,
            headers={"User-Agent": settings.scryfall_user_agent, "Accept": "image/*"},
        ) as client:
            r = client.get(url)
            if (
                r.status_code == 200
                and r.headers.get("content-type", "").startswith("image/")
                and len(r.content) < 2_000_000
            ):
                with PILImage.open(BytesIO(r.content)) as image:
                    image.verify()
                return r.content
    except (httpx.HTTPError, OSError, ValueError):
        pass
    return None


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
    selected = [r.get("card_name", "") for r in guide.get("card_roles", [])[:3]]
    examples = guide.get("mulligan_examples", [])
    if examples:
        selected.extend(examples[0].get("hand_cards", []))
    selected = {n.casefold().split(" // ")[0] for n in selected}
    urls = {}
    for card in cards.values():
        name = card.name.casefold().split(" // ")[0]
        if name in selected:
            uris = card.image_uris or {}
            faces = card.card_faces or []
            url = (
                uris.get("small")
                or uris.get("normal")
                or (faces[0].get("image_uris", {}).get("small") if faces else None)
            )
            if url:
                urls[name] = url
    with ThreadPoolExecutor(max_workers=6) as pool:
        images = dict(zip(urls, pool.map(fetch_card_image, urls.values())))
    images = {k: v for k, v in images.items() if v}
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
