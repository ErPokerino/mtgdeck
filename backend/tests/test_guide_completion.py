"""A guide is published only when its review is concluded and its list is verified."""

import json
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy.orm import sessionmaker

from app.models import Card, Deck, GuideJob, GuideVersion, MetaArchetype, MetaSnapshot
from app.services import guide_jobs, guide_pipeline
from app.services.guide_pdf import render_guide_pdf
from app.services.guide_quality import (
    legality_report,
    normalize_guide,
    validate_guide,
    validate_stated_facts,
)
from app.skills import runner
from app.skills.schemas import (
    AIDeckGuideOutput,
    AIDeckGuideRequest,
    GuideJSONPatch,
    GuideReviewOutput,
)


def patch(path, old, new, quote="Basic Land", reason="Correzione"):
    return GuideJSONPatch(
        path=path,
        original_json=json.dumps(old),
        replacement_json=json.dumps(new),
        reason=reason,
        source_quote=quote,
    )


class ScriptedProvider:
    """Draft from `guide`, then one scripted answer per review round (last one repeats)."""

    provider_name = "fake"

    def __init__(self, guide, reviews):
        self.guide, self.reviews, self.prompts = guide, list(reviews), []

    def generate_structured(self, **kwargs):
        if kwargs["response_model"] is AIDeckGuideOutput:
            return AIDeckGuideOutput(**self.guide)
        self.prompts.append(kwargs["user_prompt"])
        answer = self.reviews.pop(0) if len(self.reviews) > 1 else self.reviews[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def run(db, monkeypatch, provider, **request):
    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: provider)
    request = request or dict(format_id="modern", decklist_text="60 Plains")
    return runner.run_deck_guide_skill(db, AIDeckGuideRequest(**request))


# ---------------------------------------------------------------------------
# The review always concludes before publication
# ---------------------------------------------------------------------------


def test_correction_found_in_the_third_round_is_applied_and_verified(db, guide_data, monkeypatch):
    """The reported bug: a fix proposed by the last allowed round was discarded and printed."""
    guide = deepcopy(guide_data)
    guide["executive_summary"] = "Una due tre"
    provider = ScriptedProvider(
        guide,
        [
            GuideReviewOutput(patches=[patch("/executive_summary", "Una", "Uno")]),
            GuideReviewOutput(patches=[patch("/executive_summary", "due", "Due")]),
            GuideReviewOutput(patches=[patch("/executive_summary", "tre", "Tre")]),
            GuideReviewOutput(),
        ],
    )
    result = run(db, monkeypatch, provider)
    review = result["guide"]["quality_review"]
    assert result["guide"]["executive_summary"] == "Uno Due Tre"
    assert review["status"] == "passed" and review["open_issues"] == []
    assert review["revision_count"] == 3
    assert len(provider.prompts) == 4


def test_reviewer_that_never_closes_blocks_publication(db, guide_data, monkeypatch):
    guide = deepcopy(guide_data)
    guide["executive_summary"] = "a b"
    flip = [
        GuideReviewOutput(patches=[patch("/executive_summary", "a b", "a c")]),
        GuideReviewOutput(patches=[patch("/executive_summary", "a c", "a b")]),
    ] * 20
    with pytest.raises(ValueError, match="Guida non salvata"):
        run(db, monkeypatch, ScriptedProvider(guide, flip))
    assert db.query(GuideVersion).count() == 0


def test_open_doubt_is_closed_before_publication(db, guide_data, monkeypatch):
    provider = ScriptedProvider(
        guide_data,
        [
            GuideReviewOutput(unresolved_issues=["Dubbio su Plains"]),
            GuideReviewOutput(),
        ],
    )
    result = run(db, monkeypatch, provider)
    assert result["guide"]["quality_review"]["status"] == "passed"
    assert len(provider.prompts) == 2
    assert "Dubbio su Plains" in provider.prompts[1]


def test_doubt_that_stays_open_blocks_publication(db, guide_data, monkeypatch):
    provider = ScriptedProvider(guide_data, [GuideReviewOutput(unresolved_issues=["Dubbio"])])
    with pytest.raises(ValueError, match="Guida non salvata"):
        run(db, monkeypatch, provider)
    assert db.query(GuideVersion).count() == 0


def test_failed_deterministic_check_blocks_publication_even_with_an_empty_review(
    db, guide_data, monkeypatch
):
    snapshot = MetaSnapshot(format_id="modern", source="fixture")
    db.add(snapshot)
    db.flush()
    db.add(
        MetaArchetype(
            snapshot_id=snapshot.id, format_id="modern", name="Aggro", slug="aggro", meta_share_pct=30
        )
    )
    db.commit()
    provider = ScriptedProvider(guide_data, [GuideReviewOutput()])
    with pytest.raises(ValueError, match="Guida non salvata"):
        run(db, monkeypatch, provider)
    assert db.query(GuideVersion).count() == 0
    assert "Manca il matchup obbligatorio" in provider.prompts[-1]


def test_transient_review_failure_is_retried_within_the_round(db, guide_data, monkeypatch):
    provider = ScriptedProvider(guide_data, [TimeoutError("upstream"), GuideReviewOutput()])
    result = run(db, monkeypatch, provider)
    assert result["guide"]["quality_review"]["status"] == "passed"
    assert len(provider.prompts) == 2


def test_unsupported_patch_is_dropped_after_one_repair_round(db, guide_data, monkeypatch):
    """A claim the reviewer cannot source is not a demonstrated error: it cannot block a guide."""
    invented = patch("/executive_summary", "Tesi", "Altro", quote="Testo inventato dal revisore")
    provider = ScriptedProvider(guide_data, [GuideReviewOutput(patches=[invented])])
    result = run(db, monkeypatch, provider)
    assert result["guide"]["executive_summary"] == guide_data["executive_summary"]
    assert result["guide"]["quality_review"]["status"] == "passed"
    assert len(provider.prompts) == 2


def test_later_rounds_see_the_current_guide_to_fix_every_occurrence(db, guide_data, monkeypatch):
    guide = deepcopy(guide_data)
    guide["executive_summary"] = "Una tesi"
    provider = ScriptedProvider(
        guide,
        [GuideReviewOutput(patches=[patch("/executive_summary", "Una", "Questa")]), GuideReviewOutput()],
    )
    run(db, monkeypatch, provider)
    assert "GUIDA ATTUALE" in provider.prompts[1] and "Questa tesi" in provider.prompts[1]


def test_reviewer_can_add_a_missing_matchup_and_remove_a_wrong_entry(guide_data):
    guide = deepcopy(guide_data)
    guide["strengths"] = ["Vera", "Falsa"]
    plan = dict(
        opponent_archetype="Aggro",
        tier=1,
        expected_winrate_pct=50,
        matchup_difficulty="Equilibrato",
        gameplan_pre_side="a",
        gameplan_post_side="b",
        on_the_play_notes="c",
        on_the_draw_notes="d",
        cards_in=[],
        cards_out=[],
    )
    added = GuideJSONPatch(
        path="/sideboard_guide/-", original_json="null", replacement_json=json.dumps(plan), reason="r"
    )
    removed = GuideJSONPatch(
        path="/strengths/1", original_json='"Falsa"', replacement_json="null", reason="r"
    )
    result, changed = guide_pipeline.apply_review_patches(guide, [added, removed])
    assert [p.opponent_archetype for p in result.sideboard_guide] == ["Aggro"]
    assert result.strengths == ["Vera"]
    assert set(changed) == {"/sideboard_guide/-", "/strengths/1"}


# ---------------------------------------------------------------------------
# Durable job: nothing unverified reaches the archive, the work is resumable
# ---------------------------------------------------------------------------


@pytest.fixture
def jobs(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    monkeypatch.setattr(guide_jobs, "SessionLocal", factory)
    monkeypatch.setattr(guide_jobs._executor, "submit", lambda *_: None)
    guide_jobs._workers.clear()
    yield factory
    guide_jobs._workers.clear()


def test_unconcluded_review_keeps_corrections_and_resume_publishes(
    client, db, payload, jobs, monkeypatch, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    guide = deepcopy(guide_data)
    guide["executive_summary"] = "Bozza"
    jid = client.post("/api/ai/guide-jobs", json=dict(deck_id=did, format_id="modern")).json()["id"]
    first = ScriptedProvider(
        guide,
        [
            GuideReviewOutput(patches=[patch("/executive_summary", "Bozza", "Corretta")]),
            TimeoutError("upstream"),
        ],
    )
    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: first)
    guide_jobs._work(jid)
    db.expire_all()
    job = db.get(GuideJob, jid)
    assert job.status == "failed" and db.query(GuideVersion).count() == 0
    assert job.draft_json["executive_summary"] == "Corretta"
    assert "non è stata pubblicata" in job.error

    second = ScriptedProvider(guide, [GuideReviewOutput()])
    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: second)
    new = client.post(f"/api/ai/guide-jobs/{jid}/resume").json()["id"]
    guide_jobs._work(new)
    db.expire_all()
    assert db.get(GuideJob, new).status == "completed"
    stored = db.query(GuideVersion).one().guide_json
    assert stored["executive_summary"] == "Corretta"
    assert stored["quality_review"]["status"] == "passed"


def test_archived_guide_with_open_issues_can_complete_its_review(
    client, db, payload, jobs, monkeypatch, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    snapshot = [
        {"oracle_id": "Plains", "card_name": "Plains", "board": "main", "quantity": 60},
        {"oracle_id": "Island", "card_name": "Island", "board": "side", "quantity": 15},
    ]
    archived = dict(
        guide_data,
        executive_summary="Testo da correggere",
        quality_review={"status": "warnings", "open_issues": ["Correzione proposta ma non verificata"]},
    )
    version = GuideVersion(
        deck_id=did, deck_name="Test", format_id="modern", model_id="gemini-3.8-flash",
        deck_snapshot=snapshot, guide_json=archived,
    )
    db.add(version)
    db.commit()
    reviewer = ScriptedProvider(
        guide_data,
        [GuideReviewOutput(patches=[patch("/executive_summary", "da correggere", "corretto")]), GuideReviewOutput()],
    )
    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: reviewer)
    started = client.post(f"/api/guides/{version.id}/complete-review")
    assert started.status_code == 200 and started.json()["has_draft"]
    guide_jobs._work(started.json()["id"])
    db.expire_all()
    newest = db.query(GuideVersion).order_by(GuideVersion.id.desc()).first()
    assert newest.id != version.id
    assert newest.guide_json["executive_summary"] == "Testo corretto"
    assert newest.guide_json["quality_review"] ["status"] == "passed"
    assert db.get(Deck, did).guide_json["quality_review"]["status"] == "passed"


def test_passed_guide_has_nothing_to_complete(client, db, payload, guide_data):
    did = client.post("/api/decks", json=payload).json()["id"]
    version = GuideVersion(
        deck_id=did, deck_name="Test", format_id="modern", model_id="m", deck_snapshot=[],
        guide_json=dict(guide_data, quality_review={"status": "passed", "open_issues": []}),
    )
    db.add(version)
    db.commit()
    assert client.post(f"/api/guides/{version.id}/complete-review").status_code == 400


# ---------------------------------------------------------------------------
# Deterministic checks found in the reported guide
# ---------------------------------------------------------------------------


def make_card(name, type_line, **kw):
    return Card(oracle_id=name, name=name, scryfall_id=name, set_code="tst", type_line=type_line, **kw)


def facts_entries():
    archaic = make_card("The Dawning Archaic", "Legendary Creature — Avatar", power="7", toughness="7")
    ice = make_card(
        "Thing in the Ice // Awoken Horror",
        "Creature — Horror // Creature — Kraken Horror",
        power="0",
        toughness="4",
        layout="transform",
        card_faces=[
            {"name": "Thing in the Ice", "power": "0", "toughness": "4", "type_line": "Creature — Horror"},
            {"name": "Awoken Horror", "power": "7", "toughness": "8", "type_line": "Creature — Kraken Horror"},
        ],
    )
    island = make_card("Island", "Basic Land — Island", is_basic_land=True, produced_mana=["U"])
    return [(archaic, "main", 3), (ice, "main", 4), (island, "main", 6)]


def test_stated_sums_must_add_up_and_the_message_names_the_field():
    guide = {
        "manabase_and_probability_analysis": "Sblocca {B} con 11 carte (6 Island, 1 Swamp, 4 Watery Grave).",
        "card_roles": [
            {"card_name": "Gloomlake Verge", "explanation": "appena controlliamo una delle 10 terre con sottotipo Island o Swamp (6 Island, 1 Swamp, 4 Watery Grave)."}
        ],
    }
    errors = validate_stated_facts(guide, facts_entries())
    assert len(errors) == 1
    assert "/card_roles/0/explanation" in errors[0] and "11" in errors[0] and "10" in errors[0]


def test_stated_sums_ignore_text_that_is_not_a_count_of_cards():
    guide = {
        "executive_summary": (
            "Abbiamo 12 terre stappate (4 Gloomlake Verge, 6 Island, 1 Otawara, Soaring City, 1 Swamp). "
            "Il mazzo preda gli aggro (UR Aggro 16%, Jund 4%) e costa 2 mana (Thing in the Ice 0/4)."
        )
    }
    assert validate_stated_facts(guide, facts_entries()) == []


def test_stated_power_and_toughness_must_match_the_oracle():
    wrong = {"format_context_and_magic_numbers": "The Dawning Archaic (5/5) e Awoken Horror (7/8) superano i 4 danni."}
    errors = validate_stated_facts(wrong, facts_entries())
    assert len(errors) == 1 and "The Dawning Archaic" in errors[0] and "7/7" in errors[0]
    right = {"format_context_and_magic_numbers": "The Dawning Archaic (7/7), Thing in the Ice (0/4), Awoken Horror 7/8."}
    assert validate_stated_facts(right, facts_entries()) == []


def test_kept_seven_card_hand_needs_at_least_two_lands():
    island = make_card("Island", "Basic Land — Island", is_basic_land=True, produced_mana=["U"])
    opt = make_card("Opt", "Instant", mana_cost="{U}", colors=["U"])
    entries = [(island, "main", 20), (opt, "main", 40)]
    hand = lambda lands, verdict="KEEP": {  # noqa: E731
        "hand_cards": ["Island"] * lands + ["Opt"] * (7 - lands),
        "verdict": verdict,
        "context": "G1",
        "analysis": "a",
    }
    assert any("una sola terra" in e for e in validate_guide({"mulligan_examples": [hand(1)]}, entries))
    assert any("una sola terra" in e for e in validate_guide({"mulligan_examples": [hand(1, "KEEP CONDIZIONALE")]}, entries))
    assert validate_guide({"mulligan_examples": [hand(1, "MULLIGAN")]}, entries) == []
    assert validate_guide({"mulligan_examples": [hand(2)]}, entries) == []


def test_mechanical_inconsistencies_are_fixed_without_a_paid_round():
    island = make_card("Island", "Basic Land — Island", is_basic_land=True)
    bolt = make_card("Bolt", "Instant")
    entries = [(island, "main", 56), (bolt, "main", 2), (bolt, "side", 2), (island, "side", 13)]
    guide = {
        "card_roles": [
            {"card_name": "Bolt", "quantity": 2, "explanation": "x"},
            {"card_name": "Inventata", "quantity": 2, "explanation": "x"},
        ],
        "sideboard_guide": [
            {
                "opponent_archetype": "A",
                "expected_winrate_pct": 60,
                "matchup_difficulty": "Equilibrato",
                "cards_in": [{"card_name": "Bolt", "quantity": 1, "reason": "r"}],
                "cards_out": [{"card_name": "Island", "quantity": 1, "reason": "r"}],
                "on_the_play_in": [{"card_name": "Bolt", "quantity": 1, "reason": "altra"}],
                "on_the_play_out": [{"card_name": "Island", "quantity": 1, "reason": "altra"}],
                "on_the_draw_uses_base": False,
            }
        ],
    }
    fixed = normalize_guide(guide, entries)
    assert fixed["card_roles"][0]["quantity"] == 4
    assert fixed["card_roles"][1]["quantity"] == 2  # not in the list: the reviewer must decide
    plan = fixed["sideboard_guide"][0]
    assert plan["on_the_draw_uses_base"] is True  # no distinct plan means the base plan
    assert plan["on_the_play_uses_base"] is True and not plan["on_the_play_in"]  # same as base
    assert plan["matchup_difficulty"] == "Favorevole"
    assert guide["card_roles"][0]["quantity"] == 2  # the input is not mutated


def test_guide_prompt_carries_power_toughness_and_mana_value_of_every_face(db, guide_data, monkeypatch):
    db.add(
        make_card(
            "The Dawning Archaic",
            "Legendary Creature — Avatar",
            normalized_name="the dawning archaic",
            mana_cost="{10}",
            cmc=10.0,
            power="7",
            toughness="7",
            oracle_text="Reach",
            max_copies=4,
            legality_modern="legal",
        )
    )
    db.add(
        make_card(
            "Thing in the Ice // Awoken Horror",
            "Creature — Horror // Creature — Kraken Horror",
            normalized_name="thing in the ice // awoken horror",
            mana_cost="{1}{U}",
            cmc=2.0,
            layout="transform",
            max_copies=4,
            legality_modern="legal",
            card_faces=[
                {"name": "Thing in the Ice", "mana_cost": "{1}{U}", "type_line": "Creature — Horror", "oracle_text": "Defender", "power": "0", "toughness": "4"},
                {"name": "Awoken Horror", "type_line": "Creature — Kraken Horror", "oracle_text": "x", "power": "7", "toughness": "8"},
            ],
        )
    )
    db.commit()
    seen = {}

    class Provider(ScriptedProvider):
        def generate_structured(self, **kwargs):
            seen.setdefault(kwargs["response_model"], kwargs["user_prompt"])
            return super().generate_structured(**kwargs)

    run(
        db,
        monkeypatch,
        Provider(guide_data, [GuideReviewOutput()]),
        format_id="modern",
        decklist_text="4 The Dawning Archaic\n4 Thing in the Ice\n52 Plains",
    )
    for prompt in seen.values():
        assert "7/7" in prompt and "MV 10" in prompt
        assert "Thing in the Ice {1}{U} (Creature — Horror) 0/4" in prompt
        assert "Awoken Horror  (Creature — Kraken Horror) 7/8" in prompt


# ---------------------------------------------------------------------------
# Legality is verified by the app, and the reader is not asked to do it
# ---------------------------------------------------------------------------


def test_new_guide_records_the_automatic_legality_check_and_no_formula(db, guide_data, monkeypatch):
    result = run(db, monkeypatch, ScriptedProvider(guide_data, [GuideReviewOutput()]))
    guide = result["guide"]
    assert guide["legality"]["status"] == "legal" and guide["legality"]["catalog_synced_at"]
    assert "formula" not in guide["meta_estimate"]
    assert "evidence" not in guide


def test_reading_an_archived_guide_rechecks_legality_against_the_current_catalog(
    client, db, payload, guide_data
):
    did = client.post("/api/decks", json=payload).json()["id"]
    snapshot = [
        {"oracle_id": "Lightning Bolt", "card_name": "Lightning Bolt", "board": "main", "quantity": 4},
        {"oracle_id": "Plains", "card_name": "Plains", "board": "main", "quantity": 56},
    ]
    version = GuideVersion(
        deck_id=did, deck_name="Test", format_id="modern", model_id="m",
        deck_snapshot=snapshot, guide_json=guide_data,
    )
    db.add(version)
    db.commit()
    assert client.get(f"/api/guides/{version.id}").json()["guide"]["legality"]["status"] == "legal"
    db.get(Card, "Lightning Bolt").legality_modern = "banned"
    db.commit()
    legality = client.get(f"/api/guides/{version.id}").json()["guide"]["legality"]
    assert legality["status"] == "not_legal"
    assert "Lightning Bolt" in legality["issues"][0]
    pdf = client.get(f"/api/guides/{version.id}/pdf").content
    assert "non è legale" in pdf_text(pdf) or "bandita" in pdf_text(pdf)


def test_deck_guide_is_annotated_with_the_legality_check(client, db, payload, guide_data):
    did = client.post("/api/decks", json=payload).json()["id"]
    db.get(Deck, did).guide_json = guide_data
    db.commit()
    assert client.get(f"/api/decks/{did}").json()["guide_json"]["legality"]["status"] == "legal"


def test_legality_report_names_missing_cards(db):
    report = legality_report(db, "modern", [(db.get(Card, "Plains"), "main", 60)], missing=["Sparita"])
    assert report["status"] == "not_legal" and "Sparita" in report["issues"][0]


def pdf_text(raw):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(raw)).pages)


def verified_guide(guide_data):
    return dict(
        guide_data,
        generated_at="2026-11-08T09:59:27",
        legality={
            "status": "legal",
            "issues": [],
            "checked_at": "2026-11-08T09:59:27",
            "catalog_synced_at": "2026-11-07T15:55:49",
        },
        quality_review={"status": "passed", "open_issues": []},
        meta_estimate={
            "status": "available",
            "weighted_winrate_pct": 54,
            "coverage_pct": 64,
            "source": "MTGTop8 · Last 2 Months",
            "snapshot_id": 20,
            "fetched_at": "2026-11-04T20:09:36",
            "note": "Stima del modello sul 64% del meta, non risultati di partite.",
            # What older guides still carry: it must not be printed anymore.
            "formula": "Somma(quota meta × WR teorico Bo3) / somma(quote coperte)",
        },
        evidence="Le legalità sono una fotografia locale, non una verifica live.",
    )


def test_pdf_states_the_verified_legality_and_drops_technical_notes(guide_data):
    text = pdf_text(
        render_guide_pdf(
            verified_guide(guide_data), "Guida", "pioneer", [{"quantity": 60, "board": "main", "card_name": "Plains"}]
        )
    )
    assert "Lista legale in PIONEER" in text and "08/11/2026" in text and "07/11/2026" in text
    assert "MTGTop8" in text and "04/11/2026" in text
    for removed in [
        "verificare la legalità",
        "Somma(",
        "fotografia locale",
        "Snapshot 20",
        "PUNTI DA VERIFICARE",
        "Punti da verificare",
    ]:
        assert removed not in text, removed


def test_pdf_warns_loudly_when_a_card_is_no_longer_legal(guide_data):
    guide = verified_guide(guide_data)
    guide["legality"] = {
        "status": "not_legal",
        "issues": ["Fatal Push è bandita in Pioneer."],
        "checked_at": "2026-11-08T09:59:27",
        "catalog_synced_at": "2026-11-07T15:55:49",
    }
    text = pdf_text(render_guide_pdf(guide, "Guida", "pioneer", []))
    assert "LISTA NON LEGALE" in text and "Fatal Push è bandita in Pioneer." in text
    assert "Lista legale in" not in text


def test_pdf_matrix_keeps_long_archetype_names_whole(guide_data):
    guide = verified_guide(guide_data)
    names = ["The Rock (Golgari Control)", "Greasefang Parhelion", "Devotion to Green"]
    guide["sideboard_guide"] = [
        dict(
            opponent_archetype=name,
            cards_in=[{"card_name": "Island", "quantity": 1, "reason": "r"}],
            cards_out=[{"card_name": "Plains", "quantity": 1, "reason": "r"}],
        )
        for name in names
    ]
    pages = PdfReader(BytesIO(render_guide_pdf(guide, "Guida", "pioneer", []))).pages
    matrix = next(p.extract_text() for p in pages if "Matrice di sideboard" in p.extract_text())
    for name in names:
        assert name in matrix, name
