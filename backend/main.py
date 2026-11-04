import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func
from app.config import settings
from app.database import Base, SessionLocal, engine, init_fts5_index
from app.migrations import run_startup_repairs
from app.models import Card, MetaSnapshot, SyncLog
from app.routers import (
    guides,
    ai,
    cards,
    decks,
    formats,
    meta,
    quality as quality_router,
    settings as settings_router,
    sync,
)
from app.services.meta_scraper import run_meta_sync_all
from app.services.scryfall_sync import ensure_default_formats, run_scryfall_sync

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Inizializza tabelle SQL + indice FTS5
    Base.metadata.create_all(bind=engine)
    run_startup_repairs(engine, SessionLocal)
    from app.services import ai_jobs
    from app.services.guide_jobs import recover_interrupted_jobs

    with SessionLocal() as jobs_db:
        recover_interrupted_jobs(jobs_db)
        ai_jobs.recover_interrupted_jobs(jobs_db)
    init_fts5_index()
    from app.models import Deck, GuideVersion

    with SessionLocal() as migration_db:
        for deck in migration_db.query(Deck).filter(Deck.guide_json.isnot(None)):
            if not migration_db.query(GuideVersion).filter_by(deck_id=deck.id).first():
                snapshot = [
                    {
                        "oracle_id": c.oracle_id,
                        "card_name": c.card_name,
                        "board": c.board,
                        "quantity": c.quantity,
                    }
                    for c in deck.cards
                ]
                migration_db.add(
                    GuideVersion(
                        deck_id=deck.id,
                        deck_name=deck.name,
                        format_id=deck.format_id,
                        model_id="legacy",
                        deck_snapshot=snapshot,
                        guide_json=deck.guide_json,
                    )
                )
        migration_db.commit()

    db = SessionLocal()
    try:
        ensure_default_formats(db)
        card_count = db.query(func.count(Card.oracle_id)).scalar() or 0
        meta_count = db.query(func.count(MetaSnapshot.id)).scalar() or 0
        last_sync = (
            db.query(func.max(SyncLog.completed_at))
            .filter(SyncLog.source == "scryfall", SyncLog.status == "completed")
            .scalar()
        )
    finally:
        db.close()

    # 2. Se il DB locale è vuoto, avvia automaticamente la prima sincronizzazione completa di Scryfall
    if card_count == 0:
        asyncio.create_task(run_scryfall_sync(force_download=False))
    elif meta_count == 0:
        asyncio.create_task(run_meta_sync_all())
    elif settings.enable_scheduler and _older_than(last_sync, hours=24):
        # The interval job first fires 24h after start: after downtime, AI features would stay blocked.
        asyncio.create_task(run_scryfall_sync(force_download=False))

    # 3. Scheduler periodico per sincronizzazione Scryfall e Meta (MTGTop8)
    if settings.enable_scheduler:
        scheduler.add_job(
            run_scryfall_sync,
            "interval",
            hours=settings.scryfall_sync_interval_hours,
            id="scryfall_daily_sync",
            replace_existing=True,
        )
        scheduler.add_job(
            run_meta_sync_all,
            "interval",
            hours=settings.meta_sync_interval_hours,
            id="meta_periodic_sync",
            replace_existing=True,
        )
        scheduler.start()

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Backend API per MTG Pro AI Workbench — Dati Scryfall, Meta Analytics, Deck Builder e AI Skills.",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    # The API has no auth and stores the provider key: refuse writes initiated by other sites.
    origin = request.headers.get("origin")
    if (
        origin
        and request.method not in ("GET", "HEAD", "OPTIONS")
        and origin not in ALLOWED_ORIGINS
        and origin != f"{request.url.scheme}://{request.url.netloc}"
    ):
        return JSONResponse({"detail": "Origine non autorizzata."}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _older_than(stamp, hours: int) -> bool:
    if stamp is None:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp > timedelta(hours=hours)

app.include_router(formats.router)
app.include_router(cards.router)
app.include_router(decks.router)
app.include_router(meta.router)
app.include_router(ai.router)
app.include_router(guides.router)
app.include_router(sync.router)
app.include_router(settings_router.router)
app.include_router(quality_router.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "environment": settings.environment}


from fastapi.staticfiles import StaticFiles
from app.config import ROOT_DIR

_frontend = ROOT_DIR / "frontend" / "dist"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
