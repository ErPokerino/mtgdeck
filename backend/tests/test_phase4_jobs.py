import pytest
from sqlalchemy.orm import sessionmaker
from test_phase2_generation import (  # noqa: F401  (fixtures)
    DELTAS,
    MAIN_CHANGED,
    PLANS,
    SIDE,
    FakeProvider,
    cards,
    meta,
    output,
)

from app.models import AIJob, Deck
from app.services import ai_jobs
from app.skills import deck_generation
from app.skills.schemas import AIDeckCriticOutput


@pytest.fixture
def worker(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    monkeypatch.setattr(ai_jobs, "SessionLocal", factory)
    monkeypatch.setattr(ai_jobs._executor, "submit", lambda *_: None)
    ai_jobs._workers.clear()
    done = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    provider = FakeProvider([done], AIDeckCriticOutput(verdict="solida", summary="ok"))
    monkeypatch.setattr(deck_generation, "get_active_ai_provider", lambda _: provider)
    yield provider
    ai_jobs._workers.clear()


def start(client, meta):
    return client.post(
        "/api/ai/jobs/deck-generation",
        json={"format_id": "modern", "base_archetype_id": meta.id},
    )


def test_generation_job_returns_at_once_and_stores_the_result(client, db, meta, worker):
    first = start(client, meta).json()
    assert first["status"] == "queued" and first["kind"] == "deck_generation"
    assert start(client, meta).json()["id"] == first["id"]  # double click joins
    ai_jobs._work(first["id"])
    db.expire_all()
    job = client.get(f"/api/ai/jobs/{first['id']}").json()
    assert job["status"] == "completed"
    assert job["result"]["ai_result"]["base_archetype"] == "Mono Red"
    assert job["result"]["deck"]["id"] == db.query(Deck).one().id
    listed = client.get("/api/ai/jobs", params={"format_id": "modern", "kind": "deck_generation"})
    assert listed.json()["jobs"][0]["id"] == first["id"]


def test_cancelled_generation_saves_nothing(client, db, meta, worker, monkeypatch):
    job_id = start(client, meta).json()["id"]
    original = worker.generate_structured

    def cancel_then_answer(**kwargs):
        client.post(f"/api/ai/jobs/{job_id}/cancel")
        return original(**kwargs)

    monkeypatch.setattr(worker, "generate_structured", cancel_then_answer)
    ai_jobs._work(job_id)
    db.expire_all()
    assert db.get(AIJob, job_id).status == "cancelled"
    assert db.query(Deck).count() == 0


def test_failed_generation_reports_a_readable_error(client, db, meta, worker):
    worker.generations = [output({"Bolt": 4, "Mountain": 50}, SIDE)]
    job_id = start(client, meta).json()["id"]
    ai_jobs._work(job_id)
    db.expire_all()
    job = db.get(AIJob, job_id)
    assert job.status == "failed" and job.error.startswith("Generazione non salvata")


def test_restart_marks_running_jobs_as_failed(db):
    db.add(AIJob(kind="matchup_spot", format_id="modern", request_json={}, status="running"))
    db.commit()
    ai_jobs.recover_interrupted_jobs(db)
    assert db.query(AIJob).one().status == "failed"


def test_builder_analysis_includes_requirements_and_interaction(client, cards):
    body = {
        "name": "Burn",
        "format_id": "modern",
        "cards": [
            {"oracle_id": "Bolt", "card_name": "Bolt", "board": "main", "quantity": 4},
            {"oracle_id": "Blaze", "card_name": "Blaze", "board": "main", "quantity": 4},
            {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 52},
        ],
    }
    competitive = client.post("/api/decks/analyze", json=body).json()["competitive"]
    red = competitive["colors"][0]
    assert red["color"] == "R" and red["sources"] == 52 and red["required"] == 21
    assert competitive["interaction_main"]["rimozioni"]["copies"] == 4
    body["cards"] = []
    assert client.post("/api/decks/analyze", json=body).json()["competitive"] is None


def test_card_search_filters_by_function(db, cards):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.routers import cards as cards_router

    app = FastAPI()
    app.include_router(cards_router.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as http:
        names = [
            c["name"]
            for c in http.get(
                "/api/cards/search", params={"format_id": "modern", "tag": "removal"}
            ).json()["cards"]
        ]
    assert names == ["Bolt"]


def test_builder_analysis_says_which_field_archetypes_the_list_is_built_like(client, meta):
    body = {
        "name": "Burn",
        "format_id": "modern",
        "archetype": "aggro",
        "cards": [
            {"oracle_id": "Bolt", "card_name": "Bolt", "board": "main", "quantity": 4},
            {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 56},
        ],
    }
    structure = client.post("/api/decks/analyze", json=body).json()["competitive"]["structure"]
    assert structure["values"]["interaction"] == 4 and structure["requested"] == "aggro"
    # Only Mono Red has complete lists in the fixture: one archetype is no yardstick.
    assert structure["nearest"] == [] and structure["issues"] == []
