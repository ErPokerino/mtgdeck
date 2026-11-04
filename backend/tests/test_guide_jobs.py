import json
import pytest
from sqlalchemy.orm import sessionmaker
from app.models import GuideJob, GuideVersion
from app.services import guide_jobs, guide_pipeline
from app.skills import runner
from app.skills.schemas import (
    AIDeckGuideOutput,
    GuideReviewOutput,
    GuideJSONPatch,
    AIDeckGuideRequest,
)


@pytest.fixture
def jobs(db, monkeypatch, guide_data):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    monkeypatch.setattr(guide_jobs, "SessionLocal", factory)
    monkeypatch.setattr(guide_jobs._executor, "submit", lambda *_: None)
    guide_jobs._workers.clear()

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            return (
                AIDeckGuideOutput(**guide_data)
                if kwargs["response_model"] is AIDeckGuideOutput
                else GuideReviewOutput()
            )

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    yield factory
    guide_jobs._workers.clear()


def test_job_returns_immediately_deduplicates_and_publishes_atomically(
    client, db, payload, jobs
):
    did = client.post("/api/decks", json=payload).json()["id"]
    req = dict(deck_id=did, format_id="modern", deck_name=payload["name"])
    first = client.post("/api/ai/guide-jobs", json=req)
    assert first.status_code == 200 and first.json()["status"] == "queued"
    jid = first.json()["id"]
    assert client.post("/api/ai/guide-jobs", json=req).json()["id"] == jid
    assert db.query(GuideVersion).count() == 0
    guide_jobs._work(jid)
    db.expire_all()
    result = client.get(f"/api/ai/guide-jobs/{jid}").json()
    assert result["status"] == "completed"
    assert result["result"]["meta"]["guide_id"]
    assert db.query(GuideVersion).count() == 1


def test_cancel_while_model_is_running_never_publishes(
    client, db, payload, jobs, monkeypatch, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    jid = client.post(
        "/api/ai/guide-jobs", json=dict(deck_id=did, format_id="modern")
    ).json()["id"]

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            with jobs() as session:
                job = session.get(GuideJob, jid)
                job.status = "cancelled"
                session.commit()
            return AIDeckGuideOutput(**guide_data)

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    guide_jobs._work(jid)
    db.expire_all()
    assert db.get(GuideJob, jid).status == "cancelled"
    assert db.query(GuideVersion).count() == 0


def test_review_timeout_publishes_the_draft_with_open_issues(
    client, db, payload, jobs, monkeypatch, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    jid = client.post(
        "/api/ai/guide-jobs", json=dict(deck_id=did, format_id="modern")
    ).json()["id"]
    calls = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            calls.append(kwargs["response_model"])
            if kwargs["response_model"] is AIDeckGuideOutput:
                return AIDeckGuideOutput(**guide_data)
            raise TimeoutError("upstream timeout")

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    guide_jobs._work(jid)
    db.expire_all()
    assert db.get(GuideJob, jid).status == "completed"
    review = db.query(GuideVersion).one().guide_json["quality_review"]
    assert review["status"] == "warnings"
    assert any("Revisione non completata" in i for i in review["open_issues"])
    assert calls == [AIDeckGuideOutput, GuideReviewOutput]


def test_resume_from_a_saved_draft_skips_generation(
    client, db, payload, jobs, monkeypatch, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    from app.services.ai_provider import get_skill_model_and_config

    request = AIDeckGuideRequest(
        deck_id=did,
        format_id="modern",
        model_id=get_skill_model_and_config(db, "deck_guide")["model_id"],
    )
    failed = GuideJob(
        format_id="modern",
        deck_id=did,
        request_json=request.model_dump(),
        status="failed",
        draft_json=guide_data,
    )
    db.add(failed)
    db.commit()
    new = client.post(f"/api/ai/guide-jobs/{failed.id}/resume").json()["id"]

    class ResumeProvider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            assert kwargs["response_model"] is GuideReviewOutput
            return GuideReviewOutput()

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: ResumeProvider())
    guide_jobs._work(new)
    db.expire_all()
    assert db.get(GuideJob, new).status == "completed"
    assert db.query(GuideVersion).count() == 1


def test_restart_preserves_unpublished_draft(db, jobs, guide_data):
    job = GuideJob(
        format_id="modern", request_json={}, status="running", draft_json=guide_data
    )
    db.add(job)
    db.commit()
    guide_jobs.recover_interrupted_jobs(db)
    assert job.status == "failed" and job.draft_json == guide_data
    assert db.query(GuideVersion).count() == 0


def test_identical_sideboard_plan_is_explicit_and_not_ambiguous(db, guide_data):
    from app.services.guide_quality import validate_guide
    from app.models import Card

    plan = dict(
        opponent_archetype="Aggro",
        cards_in=[],
        cards_out=[],
        on_the_play_uses_base=True,
    )
    guide_data["sideboard_guide"] = [plan]
    entries = [
        (db.get(Card, "Plains"), "main", 60),
        (db.get(Card, "Island"), "side", 15),
    ]
    assert validate_guide(guide_data, entries) == []
    plan["on_the_play_in"] = [dict(card_name="Island", quantity=1)]
    plan["on_the_play_out"] = [dict(card_name="Plains", quantity=1)]
    assert any(
        "rappresentazione univoca" in e for e in validate_guide(guide_data, entries)
    )


def test_changed_deck_rejects_resume_instead_of_attaching_wrong_guide(
    client, db, payload, jobs, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    job = GuideJob(
        format_id="modern",
        deck_id=did,
        request_json=AIDeckGuideRequest(
            deck_id=did, format_id="modern", model_id="gemini-3.8-flash"
        ).model_dump(),
        status="failed",
        draft_json=guide_data,
        signature="old-snapshot",
    )
    db.add(job)
    db.commit()
    result = client.post(f"/api/ai/guide-jobs/{job.id}/resume")
    guide_jobs._work(result.json()["id"])
    db.expire_all()
    assert db.get(GuideJob, result.json()["id"]).status == "failed"
    assert db.query(GuideVersion).count() == 0


def test_deadline_is_shared_and_unverified_patches_are_flagged(
    db, guide_data, monkeypatch
):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(guide_pipeline.time, "monotonic", lambda: clock[0])

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            calls.append(kwargs["timeout_seconds"])
            clock[0] += kwargs["timeout_seconds"]
            if kwargs["response_model"] is AIDeckGuideOutput:
                return AIDeckGuideOutput(**guide_data)
            if len(calls) == 4:
                return GuideReviewOutput()
            original = (
                guide_data["executive_summary"]
                if len(calls) == 2
                else "Prima correzione"
            )
            return GuideReviewOutput(
                patches=[
                    GuideJSONPatch(
                        path="/executive_summary",
                        original_json=json.dumps(original),
                        replacement_json=json.dumps(
                            "Prima correzione"
                            if len(calls) == 2
                            else "Seconda correzione"
                        ),
                        reason="Oracle",
                        source_quote="Basic Land",
                    )
                ]
            )

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(
        db, AIDeckGuideRequest(format_id="modern", decklist_text="60 Plains")
    )
    # Draft, full review, then the verification consumes the rest of the shared budget.
    assert calls == [420, 210, 90]
    review = result["guide"]["quality_review"]
    assert review["status"] == "warnings"
    assert any("applicata ma non verificata" in i for i in review["open_issues"])
    assert result["guide"]["executive_summary"] == "Prima correzione"
    assert db.query(GuideVersion).count() == 1

