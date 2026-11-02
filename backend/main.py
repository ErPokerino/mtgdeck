import asyncio
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from app.config import settings
from app.database import Base, SessionLocal, engine, init_fts5_index
from app.models import Card, MetaSnapshot
from app.routers import (
    guides,
    ai,
    cards,
    decks,
    formats,
    meta,
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
    from app.services.guide_jobs import recover_interrupted_jobs

    with SessionLocal() as jobs_db:
        recover_interrupted_jobs(jobs_db)
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
    finally:
        db.close()

    # 2. Se il DB locale è vuoto, avvia automaticamente la prima sincronizzazione completa di Scryfall
    if card_count == 0:
        asyncio.create_task(run_scryfall_sync(force_download=False))
    elif meta_count == 0:
        asyncio.create_task(run_meta_sync_all())

    # 3. Scheduler periodico per sincronizzazione Scryfall e Meta (MTGDecks + MTGTop8)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(formats.router)
app.include_router(cards.router)
app.include_router(decks.router)
app.include_router(meta.router)
app.include_router(ai.router)
app.include_router(guides.router)
app.include_router(sync.router)
app.include_router(settings_router.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "environment": settings.environment}


from fastapi.staticfiles import StaticFiles
from app.config import ROOT_DIR

_frontend = ROOT_DIR / "frontend" / "dist"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
