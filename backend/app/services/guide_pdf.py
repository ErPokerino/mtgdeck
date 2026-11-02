"""Paginated, printable tournament primer. All model text is escaped."""

from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    Image,
)


def render_guide_pdf(guide, name, fmt, decklist, card_images=None):
    card_images = card_images or {}
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="BodyPro", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=7
        )
    )
    styles.add(
        ParagraphStyle(
            name="TitlePro",
            fontName="Helvetica-Bold",
            fontSize=28,
            leading=33,
            textColor=colors.HexColor("#173b45"),
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TablePro", fontName="Helvetica", fontSize=9, leading=12, spaceAfter=2
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallPro",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#52616b"),
            spaceAfter=6,
        )
    )
    styles["Heading1"].textColor = colors.HexColor("#173b45")
    styles["Heading1"].spaceBefore = 15

    def p(value, style="BodyPro"):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), styles[style])

    story = [
        p("AETHERDECK / COMPETITIVE PRIMER", "SmallPro"),
        p(name, "TitlePro"),
        p(
            f"{fmt.upper()} | {guide.get('generated_at', 'Versione archiviata')} | {guide.get('model_id', 'Modello non documentato')}",
            "SmallPro",
        ),
    ]

    def section(title, text):
        if text:
            story.extend([p(title, "Heading1"), p(text)])

    def bullets(items):
        for item in items or []:
            story.append(p("- " + str(item)))

    def table(headers, rows, widths, together=False):
        data = [[p(h, "SmallPro") for h in headers]] + [
            [p(v, "TablePro") for v in row] for row in rows
        ]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eeef")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5d8")),
                ]
            )
        )
        story.append(KeepTogether([t]) if together else t)

    if guide.get("rules_warnings"):
        section(
            "Attenzione - possibili errori di regole",
            "\n".join(guide["rules_warnings"]),
        )
    section("Tesi competitiva", guide.get("executive_summary"))
    section(
        f"Valutazione globale: {guide.get('pro_score', '-')}/10",
        guide.get("pro_score_rationale"),
    )
    estimate = guide.get("meta_estimate") or {}
    wr = estimate.get("weighted_winrate_pct")
    section(
        "Winrate teorico ponderato sul meta",
        (f"{wr}%" if wr is not None else "Non disponibile")
        + f" | Copertura: {estimate.get('coverage_pct', 0)}%",
    )
    story.append(
        p(
            estimate.get("formula", "Stima non disponibile per questa versione."),
            "SmallPro",
        )
    )
    story.append(
        p(
            estimate.get("note", "Le stime AI non sono risultati di partite."),
            "SmallPro",
        )
    )
    if estimate.get("rows"):
        table(
            ["Archetipo", "Quota meta", "WR teorico Bo3"],
            [
                [r["archetype"], f"{r['share_pct']}%", f"{r['winrate_pct']}%"]
                for r in estimate["rows"]
            ],
            [90 * mm, 35 * mm, 45 * mm],
        )
    section("Fonti e data dei dati", guide.get("evidence"))
    if estimate.get("missing_archetypes"):
        story.append(
            p(
                "Matchup senza stima: " + ", ".join(estimate["missing_archetypes"]),
                "SmallPro",
            )
        )
    story.append(PageBreak())
    story.append(p("Indice navigabile", "Heading2"))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            name="Contents", fontSize=9, leading=12, leftIndent=10, spaceBefore=1
        )
    ]
    story.extend([toc, PageBreak()])
    story.append(p("Lista di riferimento", "Heading1"))
    for board, label in (
        ("main", "Mainboard"),
        ("side", "Sideboard"),
        ("companion", "Companion"),
    ):
        rows = [
            [c["quantity"], c["card_name"]] for c in decklist if c["board"] == board
        ]
        if rows:
            story.append(p(f"{label} ({sum(int(r[0]) for r in rows)})", "Heading2"))
            table(["Copie", "Carta"], rows, [18 * mm, 152 * mm])
    for title, field in [
        ("Posizionamento", "meta_positioning"),
        ("Soglie del formato", "format_context_and_magic_numbers"),
        ("Manabase e probabilità", "manabase_and_probability_analysis"),
        ("Turni 1-3", "early_game_plan"),
        ("Turni 4-6", "mid_game_plan"),
        ("Finale", "late_game_plan"),
        ("Mulligan", "mulligan_heuristics"),
    ]:
        section(title, guide.get(field))
    for ex_index, ex in enumerate(guide.get("mulligan_examples", [])):
        story.append(p(f"{ex.get('verdict')} - {ex.get('context')}", "Heading2"))
        hand = ex.get("hand_cards", [])
        pictures = []
        for card_name in hand:
            raw = card_images.get(card_name.casefold().split(" // ")[0])
            pictures.append(
                Image(BytesIO(raw), width=22 * mm, height=30.7 * mm)
                if raw
                else p(card_name, "SmallPro")
            )
        if (
            ex_index == 0
            and pictures
            and all(card_images.get(n.casefold().split(" // ")[0]) for n in hand)
        ):
            story.append(
                Table(
                    [pictures],
                    colWidths=[24 * mm] * len(pictures),
                    hAlign="LEFT",
                    style=[
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 1),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                    ],
                )
            )
        story.extend(
            [
                p(", ".join(ex.get("hand_cards", []))),
                p(ex.get("analysis")),
            ]
        )
    story.append(p("Scelte carta per carta", "Heading1"))
    for index, card in enumerate(guide.get("card_roles", [])):
        raw = (
            card_images.get(str(card.get("card_name", "")).casefold().split(" // ")[0])
            if index < 3
            else None
        )
        if raw:
            story.append(
                KeepTogether(
                    [
                        Table(
                            [
                                [
                                    Image(
                                        BytesIO(raw), width=35 * mm, height=48.9 * mm
                                    ),
                                    p(
                                        f"{card.get('quantity')}x {card.get('card_name')} / {card.get('role_category')}",
                                        "Heading2",
                                    ),
                                ]
                            ],
                            colWidths=[39 * mm, 131 * mm],
                            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
                        ),
                        p(card.get("explanation")),
                    ]
                )
            )
            continue
        story.extend(
            [
                p(
                    f"{card.get('quantity')}x {card.get('card_name')} / {card.get('role_category')}",
                    "Heading2",
                ),
                p(card.get("explanation")),
            ]
        )
    story.append(p("Sinergie e linee", "Heading1"))
    for synergy in guide.get("synergies", []):
        story.extend(
            [
                p(" + ".join(synergy.get("cards_involved", [])), "Heading2"),
                p(synergy.get("description")),
            ]
        )
    section("Punti di forza", "\n".join(guide.get("strengths", [])))
    section("Vulnerabilità", "\n".join(guide.get("weaknesses", [])))
    section("Tips e micro-interazioni", "\n".join(guide.get("tips_and_tricks", [])))
    for item in guide.get("excluded_cards_and_donts", []):
        section("Esclusa: " + item.get("card_name", ""), item.get("why_excluded"))
    for plan in guide.get("sideboard_guide", []):
        story.append(PageBreak())
        story.append(p("Matchup / " + plan.get("opponent_archetype", ""), "Heading1"))
        story.append(
            p(
                f"WR teorico Bo3: {plan.get('expected_winrate_pct')}% - {plan.get('matchup_difficulty', '')}",
                "SmallPro",
            )
        )
        for title, field in [
            ("Motivo della stima", "estimate_rationale"),
            ("Game 1", "gameplan_pre_side"),
            ("Game 2/3", "gameplan_post_side"),
            ("On the play", "on_the_play_notes"),
            ("On the draw", "on_the_draw_notes"),
            ("Mulligan target", "mulligan_target"),
        ]:
            section(title, plan.get(field))
        swap_start = len(story)
        for label, inf, outf in (
            ("Piano base", "cards_in", "cards_out"),
            ("On the play", "on_the_play_in", "on_the_play_out"),
            ("On the draw", "on_the_draw_in", "on_the_draw_out"),
        ):
            rows = [
                ["IN", i["quantity"], i["card_name"], i.get("reason", "")]
                for i in plan.get(inf, [])
            ]
            rows += [
                ["OUT", i["quantity"], i["card_name"], i.get("reason", "")]
                for i in plan.get(outf, [])
            ]
            if rows:
                story.append(p(label, "Heading2"))
                table(
                    ["", "Copie", "Carta", "Motivo"],
                    rows,
                    [12 * mm, 15 * mm, 55 * mm, 88 * mm],
                    together=True,
                )
        bullets(plan.get("pro_tips"))
        if len(story) > swap_start:
            story[swap_start:] = [KeepTogether(story[swap_start:])]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5d8"))
        canvas.line(20 * mm, 17 * mm, 190 * mm, 17 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52616b"))
        canvas.drawString(
            20 * mm,
            12 * mm,
            "AETHERDECK | Stime teoriche - verificare la legalita prima del torneo",
        )
        canvas.drawRightString(190 * mm, 12 * mm, str(doc.page))
        canvas.restoreState()

    class PrimerDoc(SimpleDocTemplate):
        def beforeDocument(self):
            self._heading_count = 0

        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and flowable.style.name == "Heading1":
                title = flowable.getPlainText()
                self._heading_count += 1
                anchor = f"section-{self._heading_count}"
                self.canv.bookmarkPage(anchor)
                self.canv.addOutlineEntry(title, anchor, level=0)
                chapters = {
                    "Lista di riferimento",
                    "Posizionamento",
                    "Mulligan",
                    "Scelte carta per carta",
                    "Sinergie e linee",
                    "Tips e micro-interazioni",
                }
                if title in chapters or title.startswith("Matchup / "):
                    self.notify("TOCEntry", (0, escape(title), self.page, anchor))

    doc = PrimerDoc(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=24 * mm,
        title=name + " - Competitive Primer",
        author="Aetherdeck",
    )
    doc.multiBuild(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
