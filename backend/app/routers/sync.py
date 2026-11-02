import asyncio
from typing import Dict, Optional
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Card, MetaSnapshot, SetModel, SyncLog
from app.schemas import SyncStatusOut
from app.services.meta_scraper import meta_state
from app.services.scryfall_sync import run_scryfall_sync, scryfall_state

router = APIRouter(prefix="/api/sync", tags=["Sync"])


@router.get("/status", response_model=SyncStatusOut)
def get_sync_status(db: Session = Depends(get_db)):
    total_cards = db.query(func.count(Card.oracle_id)).scalar() or 0
    total_sets = db.query(func.count(SetModel.code)).scalar() or 0

    last_scry = scryfall_state.last_sync
    if not last_scry:
        last_log = (
            db.query(SyncLog)
            .filter(SyncLog.source == "scryfall", SyncLog.status == "completed")
            .order_by(SyncLog.completed_at.desc())
            .first()
        )
        if last_log:
            last_scry = last_log.completed_at

    meta_last_by_fmt: Dict[str, Optional[object]] = {}
    for fmt in ("standard", "pioneer", "modern"):
        snap = (
            db.query(MetaSnapshot)
            .filter(MetaSnapshot.format_id == fmt)
            .order_by(MetaSnapshot.fetched_at.desc())
            .first()
        )
        meta_last_by_fmt[fmt] = snap.fetched_at if snap else None

    return SyncStatusOut(
        scryfall_status=scryfall_state.status,
        scryfall_progress_pct=scryfall_state.progress_pct,
        scryfall_message=scryfall_state.message,
        scryfall_last_sync=last_scry,
        total_cards_in_db=total_cards,
        total_sets_in_db=total_sets,
        meta_status=meta_state.status,
        meta_message=meta_state.message,
        meta_last_sync_by_format=meta_last_by_fmt,
    )


@router.post("/scryfall")
async def trigger_scryfall_sync(
    background_tasks: BackgroundTasks,
    force_download: bool = False,
):
    if scryfall_state.status == "running":
        return {
            "status": "already_running",
            "progress_pct": scryfall_state.progress_pct,
            "message": scryfall_state.message,
        }
    background_tasks.add_task(run_scryfall_sync, force_download=force_download)
    return {
        "status": "started",
        "message": "Sincronizzazione catalogo Scryfall completo avviata in background.",
    }
