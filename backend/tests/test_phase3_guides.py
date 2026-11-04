from copy import deepcopy

from test_phase2_generation import cards, meta  # noqa: F401  (fixtures)

from app.models import CardRuling, GuideVersion
from app.skills import runner
from app.skills.schemas import AIDeckGuideOutput, AIDeckGuideRequest, GuideReviewOutput

DECK = "4 Bolt\n56 Mountain\nSideboard\n4 Smash\n4 Flame\n4 Spark\n3 Blaze"


def plan(name, key_cards):
    return dict(
        opponent_archetype=name,
        tier=1,
        expected_winrate_pct=55,
        matchup_difficulty="Equilibrato",
        confidence="bassa",
        role_pre_side="Beatdown",
        role_post_side="Beatdown",
        opponent_key_cards=[
            dict(card_name=c, why_it_matters="m", our_answer="a") for c in key_cards
        ],
        gameplan_pre_side="Pre",
        gameplan_post_side="Post",
        on_the_play_notes="Play",
        on_the_draw_notes="Draw",
        cards_in=[],
        cards_out=[],
        estimate_rationale="Clock e risposte",
    )


def run_guide(db, monkeypatch, guide):
    prompts = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            prompts.append(kwargs["user_prompt"])
            if kwargs["response_model"] is GuideReviewOutput:
                return GuideReviewOutput()
            return AIDeckGuideOutput(**guide)

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(
        db, AIDeckGuideRequest(format_id="modern", decklist_text=DECK)
    )
    return result, prompts


def test_guide_receives_field_rulings_and_computed_facts(db, meta, guide_data, monkeypatch):
    db.add(CardRuling(oracle_id="Bolt", rulings=[{"published_at": "2024-01-01", "comment": "Bolt ruling text."}]))
    db.commit()
    guide = deepcopy(guide_data)
    guide["mulligan_examples"] = []
    guide["card_roles"] = []
    guide["sideboard_guide"] = [plan("Mono Red", ["Bolt", "Smash"]), plan("Green Stompy", ["Grizzly", "Grizzly"])]
    result, prompts = run_guide(db, monkeypatch, guide)
    draft_prompt = prompts[0]
    assert "CAMPO ATTESO" in draft_prompt and "Bolt ruling text." in draft_prompt
    assert "Fonti per colore: R 56 fonti / 14 richieste" in draft_prompt
    assert "MATCHUP OBBLIGATORI (usa questi nomi esatti): Mono Red, Green Stompy" in draft_prompt
    assert "Creature — Bear" in draft_prompt  # Oracle of the opponents' key cards
    assert "pro_score" not in draft_prompt
    assert result["guide"]["quality_review"]["status"] == "passed"
    assert db.query(GuideVersion).count() == 1


def test_invented_opponent_card_is_published_as_open_issue(db, meta, guide_data, monkeypatch):
    guide = deepcopy(guide_data)
    guide["mulligan_examples"] = []
    guide["card_roles"] = []
    guide["sideboard_guide"] = [plan("Mono Red", ["Bolt", "Smash"]), plan("Green Stompy", ["Grizzly", "Tarmogoyf"])]
    result, _ = run_guide(db, monkeypatch, guide)
    review = result["guide"]["quality_review"]
    assert review["status"] == "warnings"
    assert any("Tarmogoyf" in issue for issue in review["open_issues"])


def test_pdf_renders_matrix_key_cards_and_open_issues(guide_data):
    from io import BytesIO

    from pypdf import PdfReader

    from app.services.guide_pdf import render_guide_pdf

    guide = deepcopy(guide_data)
    guide["tier_assessment"] = "Scelta solida contro un campo aggressivo, confidenza media."
    guide["quality_review"] = {"status": "warnings", "open_issues": ["Rilievo aperto di prova"]}
    aggro = plan("Aggro", ["Bolt", "Goblin Guide"])
    aggro["cards_in"] = [{"card_name": "Island", "quantity": 2, "reason": "r"}]
    aggro["cards_out"] = [{"card_name": "Plains", "quantity": 2, "reason": "r"}]
    guide["sideboard_guide"] = [aggro]
    pdf = render_guide_pdf(
        guide, "Guida", "modern", [{"quantity": 60, "board": "main", "card_name": "Plains"}]
    )
    text = "".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for expected in [
        "Matrice di sideboard",
        "Carte avversarie da rispettare",
        "Goblin Guide",
        "PUBBLICATA CON PUNTI DA VERIFICARE",
        "Rilievo aperto di prova",
        "confidenza media",
    ]:
        assert expected in text, expected


def test_valid_patches_survive_a_malformed_one_in_the_same_pass(db, guide_data):
    import json

    from app.services.guide_pipeline import review_guide
    from app.skills.schemas import GuideJSONPatch

    guide = deepcopy(guide_data)
    guide["executive_summary"] = "Plains infligge 2 danni."
    reviews = [
        GuideReviewOutput(
            patches=[
                GuideJSONPatch(
                    path="/executive_summary",
                    original_json=json.dumps("infligge 2 danni"),
                    replacement_json=json.dumps("produce mana bianco"),
                    reason="Plains non infligge danni",
                    source_quote="Basic Land",
                ),
                GuideJSONPatch(
                    path="/missing/0",
                    original_json='"a"',
                    replacement_json='"b"',
                    reason="Percorso inventato",
                    source_quote="Basic Land",
                ),
            ]
        ),
        GuideReviewOutput(),
    ]

    class Provider:
        def generate_structured(self, **kwargs):
            if kwargs["response_model"] is AIDeckGuideOutput:
                return AIDeckGuideOutput(**guide)
            prompt = kwargs["user_prompt"]
            if len(reviews) == 1:
                assert "VERIFICA SOLO QUESTE CORREZIONI" in prompt
                assert "CORREZIONI PROPOSTE MA NON APPLICATE" in prompt
            return reviews.pop(0)

    plains = db.get(__import__("app.models", fromlist=["Card"]).Card, "Plains")
    result, issues = review_guide(
        Provider(), "m", "sys", "user", "60x Plains [Basic Land]", [(plains, "main", 60)],
        [], {}, lambda _: None,
    )
    assert result.executive_summary == "Plains produce mana bianco."
    assert issues == []
