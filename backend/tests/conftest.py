import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.models import Card, Format, SyncLog, utcnow
from app.routers import ai, decks, guides, settings


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    for fmt in ["standard", "pioneer", "modern"]:
        session.add(Format(id=fmt, name=fmt))
    for name in ["Plains", "Island", "Lightning Bolt", "Lesson Test"]:
        basic = name in ["Plains", "Island"]
        session.add(
            Card(
                oracle_id=name,
                scryfall_id=name,
                name=name,
                normalized_name=name.lower(),
                type_line="Basic Land"
                if basic
                else "Sorcery - Lesson"
                if name == "Lesson Test"
                else "Instant",
                set_code="tst",
                is_basic_land=basic,
                max_copies=None if basic else 4,
                legality_standard="legal",
                legality_pioneer="legal",
                legality_modern="legal",
            )
        )
    session.add(SyncLog(source="scryfall", status="completed", completed_at=utcnow()))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(ai.router)
    app.include_router(decks.router)
    app.include_router(guides.router)
    app.include_router(settings.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def payload():
    return {
        "name": "Test tournament",
        "format_id": "modern",
        "cards": [
            {"card_name": "Plains", "board": "main", "quantity": 60},
            {"card_name": "Island", "board": "side", "quantity": 15},
        ],
    }


@pytest.fixture
def guide_data():
    return dict(
        executive_summary="Tesi <verificabile> & coerente",
        pro_score=7,
        pro_score_rationale="Ipotesi da testare",
        meta_positioning="Snapshot locale",
        card_roles=[],
        synergies=[],
        early_game_plan="Turni 1-3",
        mid_game_plan="Turni 4-6",
        late_game_plan="Finale",
        mulligan_heuristics="Piano di gioco prima delle carte",
        mulligan_examples=[
            dict(
                hand_cards=["Plains"] * 7,
                context="Game 1",
                verdict="MULLIGAN",
                analysis="Nessuna azione",
            )
        ],
        strengths=["Consistenza"],
        weaknesses=["Nessun clock"],
        sideboard_guide=[],
    )
