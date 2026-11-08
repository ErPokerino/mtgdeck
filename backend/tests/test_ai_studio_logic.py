"""Matchup comparison, deck improvement and generation: facts follow from the lists."""

from test_phase2_generation import (  # noqa: F401  (fixtures)
    DELTAS,
    MAIN_CHANGED,
    PLANS,
    SIDE,
    FakeProvider,
    card,
    cards,
    meta,
    output,
    run,
)

from app.models import Deck, MetaArchetype
from app.skills import deck_generation, runner
from app.skills.schemas import (
    AIDeckCriticOutput,
    AIDeckGenerationRequest,
    AIDeckImprovementOutput,
    AIDeckImprovementRequest,
    AIDeckSwapSuggestion,
    AIMatchupSpotOutput,
    AIMatchupSpotRequest,
)

DECK = "4 Bolt\n56 Mountain\nSideboard\n4 Smash\n4 Flame\n4 Spark\n3 Blaze"


def matchup(cards_in=(("Smash", 1),), cards_out=(("Bolt", 1),), pre=60.0, post=50.0, overall=99.0):
    plan = dict(
        cards_in=[dict(card_name=n, quantity=q, reason="r") for n, q in cards_in],
        cards_out=[dict(card_name=n, quantity=q, reason="r") for n, q in cards_out],
        post_side_adjustments="a",
    )
    return AIMatchupSpotOutput(
        matchup_title="A vs B",
        expected_winrate_deck_a_pre_side_pct=pre,
        expected_winrate_deck_a_post_side_pct=post,
        overall_expected_winrate_deck_a_pct=overall,
        whos_the_beatdown="b",
        deck_a_strategy="a",
        deck_b_strategy="b",
        critical_turns_and_interactions=["t"],
        key_cards=[],
        sideboard_plan_for_deck_a=plan,
        sideboard_plan_for_deck_b=plan,
    )


class ScriptedMatchup:
    provider_name = "fake"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def generate_structured(self, **kwargs):
        self.prompts.append(kwargs["user_prompt"])
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def run_matchup(db, monkeypatch, provider, **request):
    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: provider)
    return runner.run_matchup_spot_skill(
        db, AIMatchupSpotRequest(format_id="modern", deck_a_text=DECK, **request)
    )


def test_bo3_winrate_follows_the_two_game_estimates():
    assert runner.bo3_winrate(50, 50) == 50.0
    assert runner.bo3_winrate(60, 50) == 55.0  # 0.3 + 0.15 + 0.1
    assert runner.bo3_winrate(100, 0) == 0.0


def test_matchup_overall_estimate_cannot_contradict_game_estimates(db, cards, monkeypatch):
    provider = ScriptedMatchup(matchup())
    result = run_matchup(db, monkeypatch, provider, deck_b_text=DECK)
    assert result["analysis"].overall_expected_winrate_deck_a_pct == 55.0


def test_unbalanced_sideboard_plan_is_repaired_instead_of_losing_the_analysis(db, cards, monkeypatch):
    bad = matchup(cards_in=(("Smash", 2),), cards_out=(("Bolt", 1),))
    provider = ScriptedMatchup(bad, matchup())
    result = run_matchup(db, monkeypatch, provider, deck_b_text=DECK)
    assert len(provider.prompts) == 2
    assert "CORREGGI QUESTI ERRORI" in provider.prompts[1] and "non bilanciati" in provider.prompts[1]
    assert result["analysis"].sideboard_plan_for_deck_a.cards_in[0].quantity == 1


def test_matchup_against_an_archetype_uses_its_consensus_list(db, meta, monkeypatch):
    meta.sample_decklists = [{"decklist_text": "broken sample"}]
    db.commit()
    provider = ScriptedMatchup(matchup())
    result = run_matchup(db, monkeypatch, provider, deck_b_archetype_id=meta.id)
    assert result["analysis"].matchup_title == "A vs B"
    assert "=== MAZZO B (AVVERSARIO: Mono Red) ===" in provider.prompts[0]
    assert "4x Bolt" in provider.prompts[0].split("MAZZO B")[1]


def test_matchup_prompt_states_power_and_toughness(db, cards, monkeypatch):
    deck_b = "4 Long Text\n56 Mountain\nSideboard\n4 Smash\n4 Flame\n4 Spark\n3 Blaze"
    provider = ScriptedMatchup(matchup(cards_in=(), cards_out=()))
    run_matchup(db, monkeypatch, provider, deck_b_text=deck_b)
    assert "Long Text ({1}{R}) [Creature — Wizard] 1/1 MV" in provider.prompts[0]


def improvement(*swaps):
    return AIDeckImprovementOutput(
        deck_name="Migliorato",
        archetype="aggro",
        verdict="migliorabile",
        overall_assessment="a",
        manabase_diagnosis="b",
        curve_and_interaction_diagnosis="c",
        meta_positioning_diagnosis="d",
        suggested_swaps=list(swaps),
    )


def swap(card_in, card_out="Bolt", quantity=1):
    return AIDeckSwapSuggestion(
        board="main", card_out=card_out, card_in=card_in, quantity=quantity, role="r", reason_out="o", reason_in="i"
    )


def run_improvement(db, monkeypatch, output_, text=DECK):
    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            return output_

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    return runner.run_deck_improvement_skill(
        db, AIDeckImprovementRequest(format_id="modern", decklist_text=text)
    )


def test_a_rainbow_utility_land_does_not_change_the_colours_of_the_deck(db, cards, monkeypatch):
    card(db, "Rainbow Land", type_line="Land", produced_mana=list("WUBRG"), mana_cost="")
    db.commit()
    text = "4 Bolt\n4 Rainbow Land\n52 Mountain\nSideboard\n4 Smash\n4 Flame\n4 Spark\n3 Blaze"
    result = run_improvement(db, monkeypatch, improvement(), text)
    assert result["source_deck"]["colors"] == ["R"]
    assert result["improved_deck_preview"]["colors"] == ["R"]


def test_swap_outside_the_mana_of_the_deck_is_flagged(db, cards, monkeypatch):
    result = run_improvement(db, monkeypatch, improvement(swap("Grizzly")))
    assert any("Grizzly" in w and "manabase" in w for w in result["warnings"])
    assert run_improvement(db, monkeypatch, improvement(swap("Shock")))["warnings"] == []


def test_consensus_card_with_equal_figures_in_main_and_side_counts_on_both_boards(db, meta):
    ctx = deck_generation.build_context(
        db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=meta.id)
    )
    row = ctx.consensus.main[0]
    clone = type(row)(card=row.card, quantity=row.quantity, inclusion_pct=row.inclusion_pct, avg_copies=row.avg_copies)
    ctx.consensus.side.append(clone)
    same = output({row.card.name: row.quantity, "Mountain": 60 - row.quantity}, {row.card.name: row.quantity})
    issues = deck_generation.plan_issues(same, deck_generation.resolve_entries(db, same), ctx)
    assert not any(f"{row.card.name} (side)" in i for i in issues)


def test_delta_counts_are_facts_of_the_list(db, meta):
    ctx = deck_generation.build_context(
        db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=meta.id)
    )
    wrong = [
        dict(DELTAS[0], change=3),
        DELTAS[1],
        {"card_name": "Smash", "board": "main", "change": 1, "reason": "non cambia nulla"},
    ]
    out = output(MAIN_CHANGED, SIDE, deltas=wrong, matchup_plans=PLANS)
    entries = deck_generation.resolve_entries(db, out)
    deck_generation.align_deltas(out, entries, ctx)
    assert {d.card_name: d.change for d in out.deltas} == {"Shock": 1, "Mountain": -1}
    assert deck_generation.plan_issues(out, entries, ctx) == []


def test_generation_closes_the_checks_still_open_after_the_revision(db, meta, monkeypatch):
    first = output(MAIN_CHANGED, SIDE)
    revised = output(MAIN_CHANGED, SIDE, deltas=DELTAS)  # sideboard plans still missing
    final = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    provider = FakeProvider([first, revised, final], AIDeckCriticOutput(verdict="solida", summary="ok"))
    result = run(db, monkeypatch, provider, base_archetype_id=meta.id)
    assert provider.calls.count("AIDeckGenerationOutput") == 3
    assert result["warnings"] == []
    assert db.query(Deck).count() == 1


def test_generation_survives_an_archetype_without_category(db, meta, monkeypatch):
    db.query(MetaArchetype).filter_by(id=meta.id).update({"category": ""})
    db.commit()
    final = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    run(db, monkeypatch, FakeProvider([final], AIDeckCriticOutput(verdict="solida", summary="ok")), base_archetype_id=meta.id)
    assert db.query(Deck).one().archetype == "aggro"
