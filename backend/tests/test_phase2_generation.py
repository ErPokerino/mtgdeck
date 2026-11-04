import re

import pytest

from app.models import (
    AIRun,
    Card,
    CardTag,
    Deck,
    MetaArchetype,
    MetaArchetypeCard,
    MetaCardStat,
    MetaSnapshot,
    TournamentDecklist,
)
from app.services import deck_engine
from app.skills import deck_generation
from app.skills.schemas import (
    AIDeckCriticOutput,
    AIDeckGenerationOutput,
    AIDeckGenerationRequest,
)

LONG_TEXT = (
    "When this creature enters, it deals 2 damage to any target. "
    "Whenever you cast an instant or sorcery spell, put a +1/+1 counter on it. "
    "At the beginning of your end step, if you cast two or more spells this turn, draw a card. "
    "This text is deliberately longer than the old 135-character truncation."
)


def card(db, name, **fields):
    defaults = dict(
        oracle_id=name,
        scryfall_id=name,
        name=name,
        normalized_name=name.lower(),
        type_line="Instant",
        set_code="tst",
        max_copies=4,
        legality_standard="legal",
        legality_pioneer="legal",
        legality_modern="legal",
    )
    obj = Card(**{**defaults, **fields})
    db.add(obj)
    return obj


def red(db, name, cost="{R}", **fields):
    return card(db, name, mana_cost=cost, colors=["R"], color_identity=["R"], **fields)


@pytest.fixture
def cards(db):
    card(db, "Mountain", type_line="Basic Land — Mountain", produced_mana=["R"], is_basic_land=True, max_copies=None)
    card(db, "Forest", type_line="Basic Land — Forest", produced_mana=["G"], is_basic_land=True, max_copies=None)
    for name in ["Bolt", "Shock", "Smash", "Flame", "Spark"]:
        red(db, name)
    red(db, "Blaze", cost="{R}{R}", type_line="Sorcery")
    red(db, "Long Text", cost="{1}{R}", type_line="Creature — Wizard", oracle_text=LONG_TEXT, power="1", toughness="1")
    card(db, "Grizzly", mana_cost="{1}{G}", colors=["G"], color_identity=["G"], type_line="Creature — Bear")
    card(
        db,
        "Wooded Ridge",
        type_line="Land",
        oracle_text="{T}, Sacrifice this land: Search your library for a Mountain or Forest card, put it onto the battlefield, then shuffle.",
    )
    card(db, "Slow Land", type_line="Land", oracle_text="This land enters tapped.\n{T}: Add {R}.", produced_mana=["R"])
    card(
        db,
        "Shock Land",
        type_line="Land — Mountain Forest",
        oracle_text="As this land enters, you may pay 2 life. If you don't, it enters tapped.",
        produced_mana=["R", "G"],
    )
    db.add_all([CardTag(oracle_id="Bolt", tag="removal"), CardTag(oracle_id="Bolt", tag="burn")])
    db.commit()
    return {c.name: c for c in db.query(Card)}


def deck_cards(main, side):
    return [
        {"oracle_id": n, "card_name": n, "board": board, "quantity": q}
        for board, rows in (("main", main), ("side", side))
        for n, q in rows.items()
    ]


SIDE = {"Smash": 4, "Flame": 4, "Spark": 4, "Blaze": 3}


@pytest.fixture
def meta(db, cards):
    snap = MetaSnapshot(
        format_id="modern",
        source="MTGTop8 · Last 2 Months",
        period_label="Last 2 Months",
        coverage_pct=90.0,
        decklists_count=3,
    )
    db.add(snap)
    db.flush()
    lists = [
        {"Bolt": 4, "Mountain": 56},
        {"Bolt": 3, "Shock": 1, "Mountain": 56},
        {"Bolt": 4, "Shock": 1, "Mountain": 55},
    ]
    ids = []
    for i, main in enumerate(lists):
        row = TournamentDecklist(
            source="mtgtop8",
            source_deck_id=str(i),
            format_id="modern",
            archetype_name="Mono Red",
            cards=deck_cards(main, SIDE),
            is_complete=True,
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    red_arch = MetaArchetype(
        snapshot_id=snap.id, format_id="modern", name="Mono Red", slug="mono-red", category="aggro",
        tier=1, colors=["R"], color_name="Mono-Red", meta_share_pct=12.5, winrate_pct=None,
        decklist_ids=ids, decklists_count=3,
    )
    green = MetaArchetype(
        snapshot_id=snap.id, format_id="modern", name="Green Stompy", slug="green-stompy", category="aggro",
        tier=1, colors=["G"], color_name="Mono-Green", meta_share_pct=8.0, winrate_pct=None,
        decklist_ids=[], decklists_count=0,
    )
    db.add_all([red_arch, green])
    db.flush()
    db.add_all(
        [
            MetaArchetypeCard(snapshot_id=snap.id, archetype_id=red_arch.id, oracle_id="Bolt", card_name="Bolt", lists_count=3, main_inclusion_pct=100.0, main_avg_copies=3.67),
            MetaArchetypeCard(snapshot_id=snap.id, archetype_id=red_arch.id, oracle_id="Smash", card_name="Smash", lists_count=3, side_inclusion_pct=100.0, side_avg_copies=4.0),
            MetaArchetypeCard(snapshot_id=snap.id, archetype_id=green.id, oracle_id="Grizzly", card_name="Grizzly", lists_count=2, main_inclusion_pct=100.0, main_avg_copies=4.0),
            MetaCardStat(snapshot_id=snap.id, format_id="modern", card_name="Bolt", oracle_id="Bolt", overall_presence_pct=12.5, main_presence_pct=12.5, main_avg_copies=3.67),
            MetaCardStat(snapshot_id=snap.id, format_id="modern", card_name="Long Text", oracle_id="Long Text", overall_presence_pct=3.3, main_presence_pct=3.3, main_avg_copies=2.0, side_presence_pct=1.1, side_avg_copies=1.0),
            MetaCardStat(snapshot_id=snap.id, format_id="modern", card_name="Grizzly", oracle_id="Grizzly", overall_presence_pct=8.0, main_presence_pct=8.0, main_avg_copies=4.0),
        ]
    )
    db.commit()
    return red_arch


def test_consensus_list_aggregates_copies_like_karsten(db, meta):
    con = deck_engine.consensus_list(db, meta)
    main = {c.card.name: c.quantity for c in con.main}
    assert main == {"Bolt": 4, "Shock": 1, "Mountain": 55}
    assert {c.card.name: c.quantity for c in con.side} == SIDE
    shock = next(c for c in con.main if c.card.name == "Shock")
    assert shock.inclusion_pct == 66.7 and shock not in con.core
    assert {c.card.name for c in con.core} == {"Bolt", "Mountain"}


def test_consensus_skips_cards_banned_after_the_event(db, meta):
    db.get(Card, "Shock").legality_modern = "banned"
    db.commit()
    con = deck_engine.consensus_list(db, meta)
    assert {c.card.name: c.quantity for c in con.main} == {"Bolt": 4, "Mountain": 56}


def test_analysis_counts_fetch_targets_tapped_lands_and_requirements(db, cards):
    entries = [
        (cards["Wooded Ridge"], "main", 4),
        (cards["Shock Land"], "main", 4),
        (cards["Slow Land"], "main", 4),
        (cards["Mountain"], "main", 8),
        (cards["Blaze"], "main", 4),
        (cards["Bolt"], "main", 4),
        (cards["Long Text"], "main", 32),
        (cards["Smash"], "side", 15),
    ]
    analysis = deck_engine.analyze_list(db, entries, key_cards=["Blaze"])
    colors = {c["color"]: c for c in analysis["colors"]}
    # Fetches find Mountains and the Mountain Forest dual: both colours count.
    assert colors["R"]["sources"] == 20 and colors["G"]["sources"] == 8
    # {R}{R} on turn 2 needs 21 sources: one short.
    assert colors["R"]["required"] == 21 and colors["R"]["driver"] == "Blaze"
    assert colors["R"]["deficit"] == 1
    assert analysis["tapped_lands"]["tapped"] == 4 and analysis["tapped_lands"]["conditional"] == 4
    assert analysis["interaction_main"]["rimozioni"]["copies"] == 4
    assert analysis["key_card_odds"][0]["card"] == "Blaze"
    assert deck_engine.analytics_warnings(analysis)[0].startswith("Fonti R: 20 contro 21")


def test_hypergeometric_helpers():
    assert deck_engine.p_at_least_one(4, 7) == pytest.approx(0.3995, abs=1e-3)
    assert deck_engine.p_at_least(3, 24, 9) == pytest.approx(0.7887, abs=1e-3)  # simulated: 0.7885


def output(main, side, **extra):
    slots = lambda rows: [  # noqa: E731
        {"card_name": n, "quantity": q, "role": "r", "reason": "r"} for n, q in rows.items()
    ]
    return AIDeckGenerationOutput(
        deck_name="Burn",
        archetype="aggro",
        color_combination_name="Mono-Red",
        strategy_overview="tesi",
        mana_curve_notes="mana",
        key_synergies=[],
        mainboard=slots(main),
        sideboard=slots(side),
        **extra,
    )


MAIN_CHANGED = {"Bolt": 4, "Shock": 2, "Mountain": 54}
PLANS = [
    {"opponent_archetype": "Mono Red", "plan": "mirror", "sideboard_in": [], "sideboard_out": []},
    {
        "opponent_archetype": "Green Stompy",
        "plan": "rimozioni",
        "sideboard_in": [{"card_name": "Smash", "quantity": 2}],
        "sideboard_out": [{"card_name": "Shock", "quantity": 2}],
    },
]
DELTAS = [
    {"card_name": "Shock", "board": "main", "change": 1, "reason": "aggro"},
    {"card_name": "Mountain", "board": "main", "change": -1, "reason": "curva"},
]


def test_plan_issues_require_motivated_deltas_and_balanced_plans(db, meta):
    ctx = deck_generation.build_context(db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=meta.id))
    bare = output(MAIN_CHANGED, SIDE)
    issues = deck_generation.plan_issues(bare, deck_generation.resolve_entries(db, bare), ctx)
    assert "Differenza non motivata rispetto al consenso: +1 Shock (main)." in issues
    assert "Differenza non motivata rispetto al consenso: -1 Mountain (main)." in issues
    assert "Manca il piano di sideboard contro Green Stompy." in issues

    unbalanced = [dict(PLANS[1], sideboard_out=[{"card_name": "Shock", "quantity": 1}]), PLANS[0]]
    done = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=unbalanced)
    issues = deck_generation.plan_issues(done, deck_generation.resolve_entries(db, done), ctx)
    assert len(issues) == 1 and "non bilanciati" in issues[0]
    done = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    assert deck_generation.plan_issues(done, deck_generation.resolve_entries(db, done), ctx) == []


def test_context_carries_only_observed_numbers_and_full_oracle(db, meta):
    text = deck_generation.build_context(
        db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=meta.id)
    ).text
    assert LONG_TEXT in text
    assert "WR" not in text and "Constructed Staple" not in text and "Sideboard Tech" not in text
    assert "rimozioni 3.7" in text  # Bolt: tagged removal, 100% x 3.67 copies per list
    observed = {12.5, 8.0, 90.0, 3.3, 1.1, 100.0, 66.7, 79.5}
    method = {80.0, 90.0}  # core threshold and Karsten consistency target
    found = {float(n) for n in re.findall(r"(\d+(?:\.\d+)?)%", text)}
    assert found <= observed | method, found - observed - method


class FakeProvider:
    provider_name = "fake"

    def __init__(self, generations, critic):
        self.generations = list(generations)
        self.critic = critic
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs["response_model"].__name__)
        if kwargs["response_model"] is AIDeckCriticOutput:
            return self.critic
        return self.generations.pop(0) if len(self.generations) > 1 else self.generations[0]


def run(db, monkeypatch, provider, **req):
    monkeypatch.setattr(deck_generation, "get_active_ai_provider", lambda _: provider)
    return deck_generation.run_deck_generation_skill(db, AIDeckGenerationRequest(format_id="modern", **req))


def test_pipeline_reviews_and_applies_a_motivated_revision(db, meta, monkeypatch):
    first = output(MAIN_CHANGED, SIDE)
    revised = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    critic = AIDeckCriticOutput(verdict="solida", summary="ok")
    provider = FakeProvider([first, revised], critic)
    result = run(db, monkeypatch, provider, base_archetype_id=meta.id)

    assert provider.calls == ["AIDeckGenerationOutput", "AIDeckCriticOutput", "AIDeckGenerationOutput"]
    assert result["revision"]["applied"] and result["warnings"] == []
    assert result["ai_result"].deck_name.startswith("Mono Red")
    assert result["ai_result"].base_archetype == "Mono Red"
    assert result["starting_point"]["mode"] == "meta"
    deck = db.query(Deck).one()
    assert deck.archetype == "aggro" and sum(c.quantity for c in deck.cards if c.board == "main") == 60
    stored = db.query(AIRun).one().output_json
    assert stored["analysis"]["main_count"] == 60 and stored["critic"]["verdict"] == "solida"


def test_invalid_revision_keeps_the_valid_list(db, meta, monkeypatch):
    first = output(MAIN_CHANGED, SIDE)
    broken = output({"Bolt": 4, "Mountain": 55}, SIDE)  # 59 cards, repairs keep failing
    critic = AIDeckCriticOutput(
        verdict="da_rivedere",
        summary="manca reach",
        issues=[{"severity": "alta", "area": "slot", "finding": "f", "recommendation": "r"}],
    )
    result = run(db, monkeypatch, FakeProvider([first, broken], critic), base_archetype_id=meta.id)
    assert not result["revision"]["applied"] and "regole" in result["revision"]["note"]
    assert {s.card_name: s.quantity for s in result["ai_result"].mainboard} == MAIN_CHANGED
    assert any("non motivata" in w for w in result["warnings"])
    assert db.query(Deck).count() == 1


def test_solid_brew_skips_revision(db, meta, monkeypatch):
    brew = output({"Long Text": 4, "Bolt": 4, "Mountain": 52}, SIDE, matchup_plans=PLANS[:1] + [
        {"opponent_archetype": "Green Stompy", "plan": "p", "sideboard_in": [], "sideboard_out": []}
    ])
    provider = FakeProvider([brew], AIDeckCriticOutput(verdict="solida", summary="ok"))
    result = run(db, monkeypatch, provider, colors=["R"], build_around_cards=["Long Text"])
    assert provider.calls == ["AIDeckGenerationOutput", "AIDeckCriticOutput"]
    assert not result["revision"]["attempted"]
    assert result["starting_point"]["mode"] == "brew"
    assert result["starting_point"]["references"][0]["archetype"] == "Mono Red"
    assert result["ai_result"].base_archetype == ""


def test_unknown_base_archetype_is_rejected(db, meta):
    with pytest.raises(ValueError, match="metagame corrente"):
        deck_generation.build_context(db, AIDeckGenerationRequest(format_id="modern", base_archetype_id=999))


def test_critic_swaps_trigger_a_revision_even_on_a_solid_verdict(db, meta, monkeypatch):
    done = output(MAIN_CHANGED, SIDE, deltas=DELTAS, matchup_plans=PLANS)
    critic = AIDeckCriticOutput(
        verdict="solida",
        summary="ok",
        swaps=[{"board": "side", "card_out": "Blaze", "card_in": "Shock", "quantity": 1, "reason": "r"}],
    )
    provider = FakeProvider([done], critic)
    result = run(db, monkeypatch, provider, base_archetype_id=meta.id)
    assert provider.calls[-1] == "AIDeckGenerationOutput" and result["revision"]["applied"]


def test_x_spells_are_judged_with_x_at_least_one(db, cards):
    agadeem = card(db, "Awakening", mana_cost="{X}{B}{B}{B}", colors=["B"], type_line="Sorcery")
    swamp = card(db, "Swamp", type_line="Basic Land — Swamp", produced_mana=["B"], is_basic_land=True, max_copies=None)
    db.commit()
    analysis = deck_engine.analyze_list(db, [(agadeem, "main", 1), (swamp, "main", 59)])
    black = next(c for c in analysis["colors"] if c["color"] == "B")
    assert black["driver_turn"] == 4 and black["required"] == 20
