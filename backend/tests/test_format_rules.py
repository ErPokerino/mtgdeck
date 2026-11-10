"""Every AI skill knows the format's banlist and never publishes a card the format forbids."""

from app.models import Card
from app.services import deck_engine
from app.services.format_rules import (
    CardNameIndex,
    card_index,
    format_rules_block,
    illegal_mention_errors,
)
from app.services.guide_quality import evidence_context
from app.skills.runner import guide_card_errors
from test_phase2_generation import card, cards, meta  # noqa: F401 - shared fixtures


def ban(db, name, fmt="modern"):
    setattr(db.get(Card, name), f"legality_{fmt}", "banned")
    db.commit()


def test_every_skill_context_carries_scope_and_banlist(db):
    card(db, "The One Ring", type_line="Legendary Artifact", legality_modern="banned")
    db.commit()
    block = format_rules_block(db, "modern")
    assert "Banlist MODERN" in block and "The One Ring" in block
    assert "Eighth Edition" in block
    assert "The One Ring" in evidence_context(db, "modern")
    assert "The One Ring" not in format_rules_block(db, "pioneer")


def test_banned_card_named_in_text_is_an_error():
    index = CardNameIndex(
        "modern",
        [("The One Ring", "banned"), ("Memory Deluge", "legal"), ("Fury", "banned"), ("Fury Sliver", "legal")],
    )
    guide = {"card_roles": [{"alternatives_considered": "Memory Deluge o The One Ring: più lente."}]}
    errors = illegal_mention_errors(index, guide)
    assert len(errors) == 1 and "The One Ring" in errors[0] and "bandita in MODERN" in errors[0]
    assert "/card_roles/0/alternatives_considered" in errors[0]
    # The longest name wins: a legal card is not read as the banned word it contains.
    assert not illegal_mention_errors(index, {"t": "Fury Sliver dà double strike."})
    assert illegal_mention_errors(index, {"t": "Fury resta un'opzione."})


def test_figures_of_speech_keywords_and_archetypes_are_not_card_choices():
    index = CardNameIndex(
        "modern",
        [("Time Walk", "not_legal"), ("Force Spike", "not_legal"), ("Flash", "not_legal"),
         ("Lightning Bolt", "not_legal"), ("Hogaak, Arisen Necropolis", "banned")],
    )
    text = {
        "a": "Funge da Time Walk contro i mazzi di creature.",
        "b": "Nei primi turni funziona come Force Spike.",
        "c": "Le creature con Flash puniscono la tappata.",
        "opponent_archetype": "Lightning Bolt Tribal",
    }
    assert not illegal_mention_errors(index, text)
    assert not illegal_mention_errors(
        index, {"t": "Contro Hogaak, Arisen Necropolis Combo"}, ignore=["Hogaak, Arisen Necropolis Combo"]
    )
    assert illegal_mention_errors(index, {"t": "Lightning Bolt al posto di Shock."})


def test_card_index_reads_the_catalog_of_the_format(db):
    card(db, "The One Ring", type_line="Legendary Artifact", legality_modern="banned")
    card(db, "Treasure", type_line="Token Artifact — Treasure",
         legality_standard="not_legal", legality_pioneer="not_legal", legality_modern="not_legal")
    db.commit()
    index = card_index(db, "modern")
    assert index.illegal_in_text("The One Ring e Lightning Bolt") == [("The One Ring", "banned")]
    assert not card_index(db, "pioneer").illegal_in_text("The One Ring")
    # Tokens are not cards anyone registers.
    assert all(name != "Treasure" for rows in index.by_first.values() for _, name, _ in rows)


def test_guide_card_fields_agree_with_the_list_and_the_format(db, cards):
    card(db, "The One Ring", type_line="Legendary Artifact", legality_modern="banned")
    db.commit()
    entries = [(cards["Bolt"], "main", 4), (cards["Mountain"], "main", 56), (cards["Smash"], "side", 15)]
    guide = {
        "excluded_cards_and_donts": [
            {"card_name": "The One Ring", "why_excluded": "troppo lenta"},
            {"card_name": "Bolt", "why_excluded": "non serve"},
            {"card_name": "Shock", "why_excluded": "meno danni"},
        ],
        "flex_slots": [{"card_name": "Bolt", "trigger": "se cresce X"}, {"card_name": "Spark", "trigger": "y"}],
    }
    errors = guide_card_errors(db, "modern", card_index(db, "modern"), guide, entries, [])
    assert any("The One Ring" in e and "bandita" in e for e in errors)
    assert any("Carta esclusa che è nella lista" in e and "Bolt" in e for e in errors)
    assert any("Flex slot non presente" in e and "Spark" in e for e in errors)
    assert not any("Shock" in e for e in errors)


def test_opponents_field_drops_cards_banned_after_the_event(db, meta):
    before = deck_engine.field_model(db, meta.snapshot)
    assert "Bolt" in {c.name for c in before[0].core}
    ban(db, "Bolt")
    after = deck_engine.field_model(db, meta.snapshot)
    assert "Bolt" not in {c.name for c in after[0].core + after[0].interaction_cards}


def test_guide_with_a_banned_alternative_is_corrected_before_publication(db, guide_data, monkeypatch):
    import json

    from app.models import GuideVersion
    from app.skills import runner
    from app.skills.schemas import AIDeckGuideOutput, AIDeckGuideRequest, GuideJSONPatch, GuideReviewOutput

    card(db, "The One Ring", type_line="Legendary Artifact", legality_modern="banned")
    db.commit()
    draft = dict(guide_data, executive_summary="Tesi. Scartata The One Ring.")
    prompts = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            prompts.append(kwargs["user_prompt"])
            if kwargs["response_model"] is AIDeckGuideOutput:
                return AIDeckGuideOutput(**draft)
            if len(prompts) == 2:
                return GuideReviewOutput(
                    patches=[
                        GuideJSONPatch(
                            path="/executive_summary",
                            original_json=json.dumps("Scartata The One Ring."),
                            replacement_json=json.dumps("Scartata Lightning Bolt."),
                            reason="Carta bandita in Modern",
                            source_quote="",
                        )
                    ]
                )
            return GuideReviewOutput()

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(db, AIDeckGuideRequest(format_id="modern", decklist_text="60 Plains"))
    assert "Banlist MODERN" in prompts[0] and "ALTERNATIVE LEGALI OSSERVATE" in prompts[0]
    assert "ERRORI DETERMINISTICI" in prompts[1] and "'The One Ring' è bandita in MODERN" in prompts[1]
    assert "Banlist MODERN" in prompts[1]
    assert "The One Ring" not in json.dumps(result["guide"])
    assert db.query(GuideVersion).count() == 1


def test_generation_drops_notes_and_reviewer_swaps_that_name_unplayable_cards(db, cards, meta):
    from app.skills import deck_generation
    from app.skills.schemas import AIDeckCriticOutput, AIDeckGenerationRequest

    card(db, "The One Ring", type_line="Legendary Artifact", legality_modern="banned")
    db.commit()
    ctx = deck_generation.build_context(
        db, AIDeckGenerationRequest(format_id="modern", colors=["R"], archetype="aggro")
    )
    out = deck_generation.AIDeckGenerationOutput.model_construct(
        excluded_cards_or_traps=["The One Ring: troppo lenta", "Blaze: costo RR"],
        flex_rules=["se cresce Mono Red, Smash al posto di Spark"],
    )
    deck_generation.drop_illegal_notes(card_index(db, "modern"), out, ctx)
    assert out.excluded_cards_or_traps == ["Blaze: costo RR"]
    assert out.flex_rules == ["se cresce Mono Red, Smash al posto di Spark"]

    critic = AIDeckCriticOutput.model_validate(
        {
            "verdict": "da_rivedere",
            "summary": "s",
            "swaps": [
                {"board": "main", "card_out": "Spark", "card_in": "The One Ring", "quantity": 1, "reason": "r"},
                {"board": "main", "card_out": "Spark", "card_in": "bolt", "quantity": 1, "reason": "r"},
            ],
        }
    )
    assert deck_generation.legal_critic_swaps(db, "modern", critic) == ["The One Ring"]
    assert [s.card_in for s in critic.swaps] == ["Bolt"]
