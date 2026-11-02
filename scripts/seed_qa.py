"""Seed a disposable, offline browser-test database, without touching personal decks."""

import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
qa_path = root / "tmp" / "qa" / "fixture.db"
qa_path.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + qa_path.as_posix()
os.environ["ENABLE_SCHEDULER"] = "false"
sys.path.insert(0, str(root / "backend"))
from app.database import Base, engine, SessionLocal, init_fts5_index
from app.models import Card, MetaSnapshot, SyncLog, GuideVersion, utcnow
from app.services.scryfall_sync import ensure_default_formats
from sqlalchemy import text

Base.metadata.create_all(engine)
init_fts5_index()
with SessionLocal() as db:
    ensure_default_formats(db)
    for card in json.loads(
        (root / "backend/tests/fixtures/cards.json").read_text(encoding="utf-8")
    ):
        db.merge(Card(**card))
    for fmt in ["standard", "pioneer", "modern"]:
        if not db.query(MetaSnapshot).filter_by(format_id=fmt).first():
            db.add(
                MetaSnapshot(
                    format_id=fmt, source="Offline QA fixture", total_decks_analyzed=0
                )
            )
    db.add(
        SyncLog(
            source="scryfall",
            status="completed",
            completed_at=utcnow(),
            message="Offline QA fixture; not production data",
        )
    )
    if not db.query(GuideVersion).filter_by(deck_name="QA Reference Primer").first():
        guide = json.loads(
            (root / "backend/tests/fixtures/guide.json").read_text(encoding="utf-8")
        )
        db.add(
            GuideVersion(
                deck_name="QA Reference Primer",
                format_id="modern",
                model_id="offline-fixture",
                deck_snapshot=[
                    {"card_name": "Mountain", "quantity": 60, "board": "main"}
                ],
                guide_json=guide,
            )
        )
    db.flush()
    db.execute(text("DELETE FROM cards_fts"))
    db.execute(
        text(
            "INSERT INTO cards_fts (oracle_id,name,type_line,oracle_text) SELECT oracle_id,name,type_line,COALESCE(oracle_text,'') FROM cards"
        )
    )
    db.commit()
print(qa_path)
