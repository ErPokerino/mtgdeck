from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_phase2_generation import (  # noqa: F401  (fixtures)
    MAIN_CHANGED,
    SIDE,
    FakeProvider,
    cards,
    meta,
    output,
)
from test_phase3_guides import plan

from app.database import get_db
from app.models import Deck, GuideVersion, MatchRecord
from app.routers import decks as decks_router
from app.routers import quality as quality_router
from app.services import deck_engine, quality
from app.skills import deck_generation, runner
from app.skills.schemas import (
    AIDeckCriticOutput,
    AIDeckGenerationRequest,
    AIDeckGuideOutput,
    AIDeckGuideRequest,
    GuideReviewOutput,
)


@pytest.fixture
def http(db):
    app = FastAPI()
    app.include_router(quality_router.router)
    app.include_router(decks_router.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


def test_consensus_overlaps_itself_completely(db, meta):
    con = deck_engine.consensus_list(db, meta)
    metrics = quality.deck_metrics(db, con.entries(), [(meta, con)])
    assert metrics["consensus_overlap_pct"] == 100.0
    assert metrics["nearest_archetype"] == "Mono Red"
    assert metrics["interaction_main"] == 4 and metrics["total_deficit"] == 0


def test_guide_metrics_measure_depth_and_coverage(meta, guide_data):
    guide = deepcopy(guide_data)
    guide["tier_assessment"] = "solida"
    guide["card_roles"] = []
    guide["mulligan_examples"] = []
    guide["sideboard_guide"] = [plan("Mono Red", ["Bolt", "Smash"])]
    green = type("A", (), {"name": "Green Stompy", "meta_share_pct": 8.0})
    metrics = quality.guide_metrics(guide, [], [meta, green], {"mono red": {"bolt", "smash"}})
    assert metrics["matchups_covered"] == 1 and metrics["matchups_required"] == 2
    assert metrics["avg_opponent_cards"] == 2.0 and metrics["avg_words_main_matchups"] > 0
    assert metrics["validator_errors"] >= 1  # Green Stompy is missing
    assert metrics["legacy_schema"] is False
    assert metrics["play_draw_differentiated"] == 1


def test_report_scores_reference_and_generated_decks(db, meta, http, monkeypatch):
    provider = FakeProvider([output(MAIN_CHANGED, SIDE)], AIDeckCriticOutput(verdict="solida", summary="ok"))
    monkeypatch.setattr(deck_generation, "get_active_ai_provider", lambda _: provider)
    deck_generation.run_deck_generation_skill(
        db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=meta.id)
    )
    report = http.get("/api/quality/report", params={"format_id": "modern"}).json()
    assert report["reference"][0]["name"] == "Mono Red"
    generated = report["generated_decks"][0]
    assert generated["mode"] == "meta" and generated["unmotivated_deltas"] == 2
    assert generated["consensus_overlap_pct"] == 98.3  # 59 of 60 cards shared
    run = next(r for r in report["runs"] if r["skill"] == "deck_generation")
    assert run["runs"] == 1 and run["with_warnings"] == 1


def test_ratings_are_bounded_and_averaged(db, http, payload):
    deck_id = http.post("/api/decks", json=payload).json()["id"]
    body = dict(target_kind="deck", target_id=deck_id, depth=4, correctness=5, usefulness=3)
    http.post("/api/quality/ratings", json=body)
    summary = http.post("/api/quality/ratings", json=dict(body, depth=2)).json()
    assert summary == {"count": 2, "depth": 3.0, "correctness": 5.0, "usefulness": 3.0}
    assert http.post("/api/quality/ratings", json=dict(body, depth=6)).status_code == 422
    assert http.post("/api/quality/ratings", json=dict(body, target_id=999)).status_code == 404


def test_real_results_reach_the_guide_prompt_and_go_with_the_deck(
    db, http, payload, guide_data, monkeypatch
):
    deck_id = http.post("/api/decks", json=payload).json()["id"]
    url = f"/api/quality/decks/{deck_id}/records"
    http.post(url, json={"opponent_archetype": "Aggro", "games_won": 2, "games_lost": 1})
    out = http.post(url, json={"opponent_archetype": "Aggro", "games_won": 0, "games_lost": 2}).json()
    assert out["summary"] == [
        {"opponent_archetype": "Aggro", "matches_won": 1, "matches_lost": 1, "matches_drawn": 0, "games_won": 2, "games_lost": 3}
    ]
    assert http.post(url, json={"opponent_archetype": "Aggro", "games_won": 0, "games_lost": 0}).status_code == 400

    prompts = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            prompts.append(kwargs["user_prompt"])
            if kwargs["response_model"] is GuideReviewOutput:
                return GuideReviewOutput()
            return AIDeckGuideOutput(**guide_data)

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    runner.run_deck_guide_skill(db, AIDeckGuideRequest(deck_id=deck_id, format_id="modern"))
    assert "contro Aggro: match 1-1, game 2-3" in prompts[0]
    assert db.query(GuideVersion).count() == 1

    http.delete(f"/api/decks/{deck_id}")
    db.expire_all()
    assert db.get(Deck, deck_id) is None and db.query(MatchRecord).count() == 0


def test_provider_usage_is_recorded_and_priced(monkeypatch):
    from types import SimpleNamespace

    from app.services import ai_provider

    provider = ai_provider.GeminiDeveloperProvider(api_key="test")
    provider._record_usage(
        SimpleNamespace(usage=SimpleNamespace(total_input_tokens=1000, total_output_tokens=200, total_thought_tokens=300, total_cached_tokens=0))
    )
    provider._record_usage(SimpleNamespace(usage=None))
    assert provider.usage == {"calls": 2, "input": 1000, "output": 200, "thought": 300, "cached": 0}
    price = {"inputPerMillion": 1.0, "outputPerMillion": 10.0}
    assert quality.run_cost(provider.usage, price) == pytest.approx(0.006)
    assert quality.run_cost(provider.usage, None) is None
