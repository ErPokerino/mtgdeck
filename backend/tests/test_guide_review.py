import json
from app.models import GuideVersion
from app.skills import runner
from app.skills.schemas import (
    AIDeckGuideOutput,
    AIDeckGuideRequest,
    GuideReviewOutput,
    GuideJSONPatch,
)


def test_invalid_review_quote_is_repaired_without_rewriting_the_guide(
    db, guide_data, monkeypatch
):
    calls = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            kind = kwargs["response_model"]
            calls.append(kind)
            if kind is AIDeckGuideOutput:
                return AIDeckGuideOutput(**guide_data)
            assert db.query(GuideVersion).count() == 0
            if len(calls) == 4:
                assert "VERIFICA SOLO QUESTE CORREZIONI" in kwargs["user_prompt"]
                return GuideReviewOutput()
            if len(calls) == 3:
                assert "CORREZIONI PROPOSTE MA NON APPLICATE" in kwargs["user_prompt"]
                assert "current_fields" in kwargs["user_prompt"]
            return GuideReviewOutput(
                patches=[
                    GuideJSONPatch(
                        path="/executive_summary",
                        original_json=json.dumps("Tesi"),
                        replacement_json=json.dumps("Piano"),
                        reason="Correzione",
                        source_quote="Quote invented by reviewer"
                        if len(calls) == 2
                        else "Basic Land",
                    )
                ]
            )

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(
        db, AIDeckGuideRequest(format_id="modern", decklist_text="60 Plains")
    )
    assert result["guide"]["executive_summary"].startswith("Piano")
    assert calls == [
        AIDeckGuideOutput,
        GuideReviewOutput,
        GuideReviewOutput,
        GuideReviewOutput,
    ]
    assert db.query(GuideVersion).count() == 1


def test_source_quote_cannot_drop_nonlegendary_prefix():
    from app.services.guide_pipeline import evidence_key

    source = evidence_key("another target nonlegendary creature you control")
    assert f" {evidence_key('legendary creature')} " not in f" {source} "
    assert f" {evidence_key('nonlegendary creature')} " in f" {source} "


def test_provider_forwards_the_whole_call_deadline_and_reasoning_profile(guide_data):
    from types import SimpleNamespace
    from app.services.ai_provider import AIProvider

    received = {}

    def create(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(output_text=json.dumps(guide_data))

    class Provider(AIProvider):
        provider_name = "fake"

        def get_client(self):
            return SimpleNamespace(interactions=SimpleNamespace(create=create))

        def resolve_provider_model_id(self, logical_model_id):
            return logical_model_id

    output = Provider().generate_structured(
        model_id="test-model",
        system_instruction="test",
        user_prompt="test",
        response_model=AIDeckGuideOutput,
        timeout_seconds=7.5,
        max_output_tokens=900,
        thinking_level="medium",
    )
    assert output.executive_summary == guide_data["executive_summary"]
    assert received["timeout"] == 7.5
    assert received["generation_config"] == {
        "max_output_tokens": 900,
        "thinking_level": "medium",
    }
