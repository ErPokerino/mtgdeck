import json
from types import SimpleNamespace

from test_phase2_generation import SIDE, card, cards, meta  # noqa: F401  (fixtures)

from app.models import Card, CardRuling, CardTag
from app.services import assistant_agent, deck_engine
from app.services.guide_pipeline import review_guide
from app.skills import deck_generation, runner
from app.skills.schemas import (
    AICandidateCardOption,
    AIDeckGuideOutput,
    AIDeckImprovementOutput,
    AIDeckSwapSuggestion,
    AIDeckWeaknessItem,
    GuideJSONPatch,
    GuideReviewOutput,
)


def test_oracle_text_preserves_ability_paragraph_boundaries_and_entry_land_labels(
    db, cards
):
    verge = card(
        db,
        "Dual Verge",
        type_line="Land",
        oracle_text="{T}: Add {U}.\n{T}: Add {B}. Activate only if you control an Island or a Swamp.",
        produced_mana=["U", "B"],
    )
    fast = card(
        db,
        "Fast Shore",
        type_line="Land",
        oracle_text="This land enters tapped unless you control two or fewer other lands.\n{T}: Add {U} or {B}.",
        produced_mana=["U", "B"],
    )
    db.commit()

    formatted = deck_generation.oracle_text(verge)
    assert " ¶ " in formatted
    assert formatted == (
        "{T}: Add {U}. ¶ {T}: Add {B}. Activate only if you control an Island or a Swamp."
    )

    entries = [(verge, "main", 4), (fast, "main", 4), (cards["Mountain"], "main", 12)]
    analysis = deck_engine.analyze_list(db, entries)
    tapped = analysis["tapped_lands"]
    assert tapped["untapped"] == 16
    assert "4 Dual Verge" in tapped["untapped_cards"]
    assert tapped["conditional"] == 4
    assert tapped["conditional_cards"] == ["4 Fast Shore"]

    txt = deck_generation.analysis_text(analysis)
    assert "4 Dual Verge" in txt
    assert "4 Fast Shore" in txt


def test_one_for_one_cycling_and_selection_do_not_inflate_net_card_advantage(db):
    censor = card(
        db,
        "Force Spike Cycling",
        mana_cost="{1}{U}",
        colors=["U"],
        type_line="Instant",
        oracle_text="Counter target spell unless its controller pays {1}.\nCycling {U}",
    )
    sleight = card(
        db,
        "Top Two Selection",
        mana_cost="{U}",
        colors=["U"],
        type_line="Sorcery",
        oracle_text="Look at the top two cards of your library. Put one of them into your hand and the other on the bottom of your library.",
    )
    cruise = card(
        db,
        "Deep Draw Three",
        mana_cost="{7}{U}",
        colors=["U"],
        type_line="Sorcery",
        oracle_text="Delve\nDraw three cards.",
    )
    for c in (censor, sleight, cruise):
        db.add(CardTag(oracle_id=c.oracle_id, tag="card-advantage-net"))
    db.add(CardTag(oracle_id=censor.oracle_id, tag="counterspell"))
    db.commit()

    entries = [
        (censor, "main", 4),
        (sleight, "main", 4),
        (cruise, "main", 3),
    ]
    analysis = deck_engine.analyze_list(db, entries)
    ca = analysis["interaction_main"].get("vantaggio carte")
    assert ca is not None
    assert ca["copies"] == 3
    assert ca["cards"] == ["3 Deep Draw Three"]
    assert analysis["interaction_main"]["counter"]["copies"] == 4


def test_review_guide_accepts_short_mana_ability_quotes_with_word_boundaries(
    db, guide_data
):
    from copy import deepcopy

    guide = deepcopy(guide_data)
    guide["manabase_and_probability_analysis"] = "La terra non produce mana al turno 1."
    reviews = [
        GuideReviewOutput(
            patches=[
                GuideJSONPatch(
                    path="/manabase_and_probability_analysis",
                    original_json=json.dumps("non produce mana al turno 1"),
                    replacement_json=json.dumps("produce sempre {U} al turno 1"),
                    reason="La prima abilità non ha restrizioni",
                    source_quote="{T}: Add {U}.",
                )
            ]
        ),
        GuideReviewOutput(),
    ]

    class Provider:
        def generate_structured(self, **kwargs):
            if kwargs["response_model"] is AIDeckGuideOutput:
                return AIDeckGuideOutput(**guide)
            return reviews.pop(0)

    plains = db.get(Card, "Plains")
    oracle_source = (
        "4x Dual Verge (Land) [Land] — {T}: Add {U}. ¶ {T}: Add {B}. Activate only if you control an Island or a Swamp."
    )
    result = review_guide(
        Provider(),
        "m",
        "sys",
        "user",
        oracle_source,
        [(plains, "main", 60)],
        [],
        {},
        lambda _: None,
    )
    assert "produce sempre {U} al turno 1" in result.manabase_and_probability_analysis


def test_deck_improvement_repairs_invalid_swaps_and_computes_before_after_metrics(
    client, db, cards, meta, monkeypatch
):
    deck_res = client.post(
        "/api/decks",
        json={
            "name": "Red Burn Draft",
            "format_id": "modern",
            "archetype": "aggro",
            "colors": ["R"],
            "cards": [
                {"oracle_id": "Bolt", "card_name": "Bolt", "board": "main", "quantity": 4},
                {"oracle_id": "Blaze", "card_name": "Blaze", "board": "main", "quantity": 4},
                {"oracle_id": "Slow Land", "card_name": "Slow Land", "board": "main", "quantity": 4},
                {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 48},
                {"oracle_id": "Smash", "card_name": "Smash", "board": "side", "quantity": 4},
                {"oracle_id": "Flame", "card_name": "Flame", "board": "side", "quantity": 4},
                {"oracle_id": "Spark", "card_name": "Spark", "board": "side", "quantity": 4},
                {"oracle_id": "Shock", "card_name": "Shock", "board": "side", "quantity": 3},
            ],
        },
    )
    assert deck_res.status_code == 200
    deck_id = deck_res.json()["id"]

    bad_out = AIDeckImprovementOutput(
        deck_name="Red Burn Ottimizzato",
        archetype="aggro",
        verdict="migliorabile",
        overall_assessment="Troppi drop lenti e terre tappate.",
        manabase_diagnosis="4 Slow Land rallentano il clock.",
        curve_and_interaction_diagnosis="Sostituire Blaze con Shock.",
        meta_positioning_diagnosis="Buono contro Stompy.",
        strengths_to_preserve=["4 Bolt"],
        weaknesses=[
            AIDeckWeaknessItem(
                severity="alta",
                area="manabase",
                title="Terre tappate",
                finding="4 Slow Land entrano sempre tappate.",
                affected_matchups=["Mono Red"],
                recommendation="Sostituire con Shock Land stappabili.",
            )
        ],
        suggested_swaps=[
            AIDeckSwapSuggestion(
                board="main",
                priority="alta",
                card_out="Missing Card",
                card_in="Shock Land",
                quantity=4,
                role="Manabase",
                reason_out="Entra tappata",
                reason_in="Entra stappata",
            )
        ],
        candidate_cards=[
            AICandidateCardOption(
                card_name="Flame",
                board="main",
                suggested_copies=2,
                replaces_candidates=["Blaze"],
                role="Burn",
                why_consider="Riduce la curva",
                when_to_prefer="Meta veloce",
            )
        ],
    )
    good_out = bad_out.model_copy(
        update={
            "suggested_swaps": [
                AIDeckSwapSuggestion(
                    board="main",
                    priority="alta",
                    card_out="Slow Land",
                    card_in="Shock Land",
                    quantity=4,
                    role="Manabase",
                    reason_out="Entra sempre tappata",
                    reason_in="Entra stappata pagando 2 vite",
                    matchups_improved=["Mono Red"],
                )
            ]
        }
    )

    prompts = []

    class FakeImprovementProvider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            prompts.append(kwargs["user_prompt"])
            return bad_out if len(prompts) == 1 else good_out

    monkeypatch.setattr(
        runner, "get_active_ai_provider", lambda _: FakeImprovementProvider()
    )
    res = client.post(
        "/api/ai/improve-deck",
        json={
            "deck_id": deck_id,
            "format_id": "modern",
            "deck_name": "Red Burn Draft",
            "user_prompt": "Velocizza la manabase",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(prompts) == 2
    assert "CORREGGI QUESTI ERRORI DETERMINISTICI" in prompts[1]
    assert data["warnings"] == []
    assert data["improvement"]["suggested_swaps"][0]["card_out"] == "Slow Land"
    assert data["improvement"]["suggested_swaps"][0]["card_in"] == "Shock Land"
    assert data["comparison"]["before_analysis"]["tapped_lands"]["tapped"] == 4
    assert data["comparison"]["after_analysis"]["tapped_lands"]["tapped"] == 0
    assert data["comparison"]["after_analysis"]["tapped_lands"]["conditional"] == 4


def test_assistant_agent_executes_tools_in_multi_hop_loop(
    client, db, cards, meta, monkeypatch
):
    db.add(
        CardRuling(
            oracle_id="Bolt",
            rulings=[{"published_at": "2024-01-01", "comment": "Bolt deals 3 damage to any target."}],
        )
    )
    db.commit()
    deck_res = client.post(
        "/api/decks",
        json={
            "name": "Test Agent Burn",
            "format_id": "modern",
            "archetype": "aggro",
            "colors": ["R"],
            "cards": [
                {"oracle_id": "Bolt", "card_name": "Bolt", "board": "main", "quantity": 4},
                {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 56},
            ],
        },
    )
    deck_id = deck_res.json()["id"]

    interactions_received = []

    def fake_create(**kwargs):
        interactions_received.append(kwargs)
        if len(interactions_received) == 1:
            return SimpleNamespace(
                id="inter-hop-1",
                output_text="",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        id="call-1",
                        name="get_deck_details",
                        arguments={"deck_id": deck_id},
                    ),
                    SimpleNamespace(
                        type="function_call",
                        id="call-2",
                        name="search_cards_and_rulings",
                        arguments={"query": "Bolt", "format_id": "modern"},
                    ),
                    SimpleNamespace(
                        type="function_call",
                        id="call-3",
                        name="get_metagame_overview",
                        arguments={"format_id": "modern"},
                    ),
                    SimpleNamespace(
                        type="function_call",
                        id="call-4",
                        name="get_app_help",
                        arguments={"topic": "ai_studio"},
                    ),
                ],
                usage=SimpleNamespace(
                    total_input_tokens=500,
                    total_output_tokens=100,
                    total_thought_tokens=50,
                    total_cached_tokens=0,
                ),
            )
        return SimpleNamespace(
            id="inter-hop-2",
            output_text="Il tuo mazzo **Test Agent Burn** gioca 4x [[Bolt]] e 56x [[Mountain]] nel metagame Modern.",
            steps=[
                SimpleNamespace(
                    type="model_output",
                    content=[
                        SimpleNamespace(
                            type="text",
                            text="Il tuo mazzo **Test Agent Burn** gioca 4x [[Bolt]] e 56x [[Mountain]] nel metagame Modern.",
                        )
                    ],
                )
            ],
            usage=SimpleNamespace(
                total_input_tokens=800,
                total_output_tokens=120,
                total_thought_tokens=30,
                total_cached_tokens=0,
            ),
        )

    class FakeAgentProvider:
        provider_name = "fake"
        usage = {"calls": 0, "input": 0, "output": 0, "thought": 0, "cached": 0}

        def get_client(self):
            return SimpleNamespace(interactions=SimpleNamespace(create=fake_create))

        def resolve_provider_model_id(self, logical_model_id):
            return logical_model_id

        def _record_usage(self, _interaction):
            self.usage["calls"] += 1

    monkeypatch.setattr(
        assistant_agent, "get_active_ai_provider", lambda _: FakeAgentProvider()
    )

    resp = client.post(
        "/api/ai/agent/chat",
        json={
            "message": "Analizza il mio mazzo, i ruling di Bolt, il meta Modern e come funziona AI Studio",
            "format_id": "modern",
            "active_tab": "ai_studio",
            "active_deck_id": deck_id,
            "active_deck_name": "Test Agent Burn",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["interaction_id"] == "inter-hop-2"
    assert "[[Bolt]]" in payload["reply"]
    assert [t["tool_name"] for t in payload["tool_calls"]] == [
        "get_deck_details",
        "search_cards_and_rulings",
        "get_metagame_overview",
        "get_app_help",
    ]
    assert all(t["status"] == "completed" for t in payload["tool_calls"])

    # Verify hop 2 sent function_result steps with previous_interaction_id
    hop2 = interactions_received[1]
    assert hop2["previous_interaction_id"] == "inter-hop-1"
    assert len(hop2["input"]) == 4
    assert hop2["input"][0]["type"] == "function_result"
    assert hop2["input"][0]["call_id"] == "call-1"
    assert "Test Agent Burn" in hop2["input"][0]["result"]
    assert "Bolt deals 3 damage" in hop2["input"][1]["result"]


def test_dereference_json_schema_preserves_title_property_in_deck_improvement():
    from app.services.ai_provider import dereference_json_schema

    schema = dereference_json_schema(AIDeckImprovementOutput.model_json_schema())
    weakness_item_schema = schema["properties"]["weaknesses"]["items"]
    assert "title" in weakness_item_schema["required"]
    assert "title" in weakness_item_schema["properties"]
    assert weakness_item_schema["properties"]["title"]["type"] == "string"
    # Top-level schema metadata title must still be stripped
    assert "title" not in schema
    assert "title" not in weakness_item_schema


def test_list_user_decks_respects_deck_archive_and_system_index(client, db, cards):
    from app.models import DeckArchive

    d1 = client.post(
        "/api/decks",
        json={
            "name": "Active Pioneer Deck",
            "format_id": "pioneer",
            "archetype": "tempo",
            "colors": ["U", "B"],
            "cards": [
                {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 60}
            ],
        },
    ).json()
    d2 = client.post(
        "/api/decks",
        json={
            "name": "Archived Modern Deck",
            "format_id": "modern",
            "archetype": "aggro",
            "colors": ["R"],
            "cards": [
                {"oracle_id": "Mountain", "card_name": "Mountain", "board": "main", "quantity": 60}
            ],
        },
    ).json()
    db.add(DeckArchive(deck_id=d2["id"]))
    db.commit()

    active_res, label = assistant_agent.execute_agent_tool(
        db, "list_user_decks", {"include_archived": False}
    )
    assert "error" not in active_res
    active_ids = [d["id"] for d in active_res["decks"]]
    assert d1["id"] in active_ids
    assert d2["id"] not in active_ids

    all_res, _ = assistant_agent.execute_agent_tool(
        db, "list_user_decks", {"include_archived": True}
    )
    all_ids = [d["id"] for d in all_res["decks"]]
    assert d1["id"] in all_ids
    assert d2["id"] in all_ids

    sys_inst = assistant_agent._build_agent_system_instruction(
        db,
        assistant_agent.AgentChatRequest(
            message="Hai accesso ai miei mazzi?",
            format_id="pioneer",
            active_deck_id=d1["id"],
            active_deck_name="Active Pioneer Deck",
        ),
    )
    assert f"deck_id={d1['id']}: \"Active Pioneer Deck\"" in sys_inst
    assert "Archived Modern Deck" not in sys_inst


def test_live_voice_websocket_connects_with_gemini_3_8_live(client, db, cards, monkeypatch):
    captured = {}

    class FakeLiveSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send_realtime_input(self, **kwargs):
            captured["realtime_input"] = kwargs

        async def send_tool_response(self, **kwargs):
            captured["tool_response"] = kwargs

        async def receive(self):
            yield SimpleNamespace(
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(
                            id="live-tc-1",
                            name="list_user_decks",
                            args={"include_archived": False},
                        )
                    ]
                ),
                server_content=None,
            )
            yield SimpleNamespace(
                tool_call=None,
                server_content=SimpleNamespace(
                    model_turn=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                inline_data=SimpleNamespace(data=b"\x00\x01\x02\x03")
                            )
                        ]
                    ),
                    input_transcription=SimpleNamespace(text="Hai i miei mazzi?"),
                    output_transcription=SimpleNamespace(text="Sì, vedo i tuoi mazzi salvati."),
                    interrupted=False,
                    turn_complete=True,
                ),
            )

    class FakeAioLive:
        def connect(self, *, model, config):
            captured["model"] = model
            captured["config"] = config
            return FakeLiveSession()

    class FakeLiveProvider:
        provider_name = "fake"

        def get_client(self):
            return SimpleNamespace(aio=SimpleNamespace(live=FakeAioLive()))

    monkeypatch.setattr(
        assistant_agent, "get_active_ai_provider", lambda _: FakeLiveProvider()
    )

    with client.websocket_connect("/api/ai/agent/live?format_id=pioneer") as ws:
        status_msg = ws.receive_json()
        assert status_msg["type"] == "status"
        assert status_msg["status"] == "listening"
        assert status_msg["model_id"] == "gemini-3.8-live"

        ws.send_json({"type": "text", "text": "Hai i miei mazzi?"})
        events = []
        for _ in range(10):
            ev = ws.receive_json()
            events.append(ev)
            if ev.get("type") == "turn_complete":
                break
        ws.send_json({"type": "stop"})

    assert captured["model"] == "gemini-3.8-live"
    ev_types = [e["type"] for e in events]
    assert "tool_call" in ev_types
    assert "audio" in ev_types
    assert "output_transcript" in ev_types
    assert "turn_complete" in ev_types
