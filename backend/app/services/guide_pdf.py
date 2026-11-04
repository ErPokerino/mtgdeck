"""Illustrated, paginated tournament primer. Model text is always escaped."""

import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents
from app.services.guide_images import image_key

INK = colors.HexColor("#173b45")
MUTED = colors.HexColor("#607479")
PALE = colors.HexColor("#f1f5f4")
LINE = colors.HexColor("#d6e1de")
GOLD = colors.HexColor("#ba9650")
WIDTH = 170 * mm


def _register_fonts() -> tuple:
    """A Unicode TrueType font when the system has one (DejaVu Sans: Windows, most Linux
    distributions, `fonts-dejavu-core` in the Docker image), otherwise Helvetica. The
    base-14 Helvetica only covers WinAnsi: arrows and comparison signs would vanish."""
    dirs = [
        os.environ.get("PDF_FONT_DIR", ""),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/dejavu",
        "/usr/share/fonts/TTF",
        "/Library/Fonts",
    ]
    for folder in filter(None, dirs):
        regular = Path(folder) / "DejaVuSans.ttf"
        bold = Path(folder) / "DejaVuSans-Bold.ttf"
        if regular.is_file() and bold.is_file():
            try:
                pdfmetrics.registerFont(TTFont("GuideSans", str(regular)))
                pdfmetrics.registerFont(TTFont("GuideSans-Bold", str(bold)))
                pdfmetrics.registerFontFamily(
                    "GuideSans",
                    normal="GuideSans",
                    bold="GuideSans-Bold",
                    italic="GuideSans",
                    boldItalic="GuideSans-Bold",
                )
                return "GuideSans", "GuideSans-Bold"
            except Exception:  # noqa: BLE001 - a broken font file falls back to Helvetica
                continue
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = _register_fonts()
UNICODE_FONT = FONT != "Helvetica"
# Without a Unicode font, signs outside WinAnsi are spelled out instead of disappearing.
ASCII_FALLBACK = {"→": "->", "←": "<-", "≥": ">=", "≤": "<=", "≠": "!=", "✓": "v", "★": "*", "−": "-"}


def pdf_text(value) -> str:
    text = str(value or "")
    if not UNICODE_FONT:
        for char in "‐‑‒−":
            text = text.replace(char, "-")
        for char, plain in ASCII_FALLBACK.items():
            text = text.replace(char, plain)
    return text


class CardPicture(Flowable):
    """A stable card-sized slot, including an honest labelled fallback offline."""

    def __init__(self, reader, width, name):
        super().__init__()
        self.width, self.height = width, width * 680 / 488
        self.reader, self.name = reader, name
        self.hAlign = "CENTER"

    def draw(self):
        canvas = self.canv
        if self.reader is not None:
            canvas.drawImage(
                self.reader,
                0,
                0,
                self.width,
                self.height,
                mask="auto",
                preserveAspectRatio=True,
            )
            return
        canvas.setFillColor(PALE)
        canvas.setStrokeColor(LINE)
        canvas.roundRect(0, 0, self.width, self.height, 2 * mm, fill=1, stroke=1)
        style = ParagraphStyle(
            "MissingCard",
            fontName=FONT_BOLD,
            fontSize=7,
            leading=9,
            alignment=TA_CENTER,
            textColor=INK,
        )
        label = Paragraph(escape(pdf_text(self.name)), style)
        _, height = label.wrap(self.width - 4 * mm, self.height)
        label.drawOn(canvas, 2 * mm, max(5 * mm, (self.height - height) / 2))
        canvas.setFillColor(MUTED)
        canvas.setFont(FONT, 5.5)
        canvas.drawCentredString(self.width / 2, 3 * mm, "Immagine non disponibile")


def render_guide_pdf(guide, name, fmt, decklist, card_images=None):
    card_images = card_images or {}
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    for label, options in {
        "BodyPro": dict(
            fontName=FONT, fontSize=10, leading=14.5, spaceAfter=7, textColor=INK
        ),
        "TitlePro": dict(
            fontName=FONT_BOLD,
            fontSize=30,
            leading=35,
            spaceAfter=16,
            textColor=INK,
        ),
        "SmallPro": dict(
            fontName=FONT, fontSize=8, leading=11, spaceAfter=6, textColor=MUTED
        ),
        "TablePro": dict(
            fontName=FONT,
            fontSize=8.5,
            leading=11.5,
            spaceAfter=2,
            textColor=INK,
        ),
        "DeckLine": dict(
            fontName=FONT, fontSize=9, leading=13, spaceAfter=3, textColor=INK
        ),
        "CardTitle": dict(
            fontName=FONT_BOLD,
            fontSize=12,
            leading=16,
            spaceAfter=6,
            textColor=INK,
            keepWithNext=True,
        ),
        "CardCaption": dict(
            fontName=FONT, fontSize=7.5, leading=9.5, spaceAfter=0, textColor=INK
        ),
        "StatLabel": dict(
            fontName=FONT_BOLD,
            fontSize=8,
            leading=11,
            spaceAfter=7,
            textColor=MUTED,
        ),
        "StatValue": dict(
            fontName=FONT_BOLD,
            fontSize=25,
            leading=30,
            spaceAfter=4,
            textColor=INK,
        ),
    }.items():
        styles.add(ParagraphStyle(name=label, **options))
    styles["BodyPro"].allowWidows = 0
    styles["BodyPro"].allowOrphans = 0
    for heading in ("Heading1", "Heading2"):
        styles[heading].fontName = FONT_BOLD
    styles["Heading1"].textColor = INK
    styles["Heading1"].fontSize = 21
    styles["Heading1"].leading = 27
    styles["Heading1"].spaceBefore = 0
    styles["Heading1"].spaceAfter = 13
    styles["Heading2"].textColor = INK
    styles["Heading2"].fontSize = 12
    styles["Heading2"].leading = 16
    styles["Heading2"].spaceBefore = 13
    styles["Heading2"].spaceAfter = 7

    def p(value, style="BodyPro"):
        return Paragraph(escape(pdf_text(value)).replace("\n", "<br/>"), styles[style])

    readers = {}

    def picture(card_name, width, back=False):
        key = image_key(card_name) + ("::back" if back else "")
        raw = card_images.get(key)
        if raw and key not in readers:
            try:
                readers[key] = ImageReader(BytesIO(raw))
            except (OSError, ValueError):
                readers[key] = None
        return CardPicture(
            readers.get(key),
            width,
            card_name.split(" // ")[-1] if back else card_name.split(" // ")[0],
        )

    story = []

    def section(title, text):
        if text:
            content = [p(title, "Heading2"), p(text)]
            if len(str(text)) <= 650:
                story.append(KeepTogether(content))
            else:
                story.extend(content)

    def chapter(title, break_before=True):
        story.extend(
            [PageBreak() if break_before else Spacer(1, 7 * mm), p(title, "Heading1")]
        )

    def bullets(items):
        for item in items or []:
            story.append(p("- " + str(item)))

    def data_table(headers, rows, widths):
        table = Table(
            [[p(h, "SmallPro") for h in headers]]
            + [[p(v, "TablePro") for v in row] for row in rows],
            colWidths=widths,
            repeatRows=1,
            hAlign="LEFT",
            splitInRow=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
                ]
            )
        )
        story.append(table)

    counts = {
        board: sum(c["quantity"] for c in decklist if c["board"] == board)
        for board in ("main", "side", "companion")
    }
    generated = guide.get("generated_at")
    try:
        stamp = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime(
            "%d/%m/%Y %H:%M UTC"
        )
    except (AttributeError, ValueError):
        stamp = "Versione archiviata"
    estimate = guide.get("meta_estimate") or {}
    wr = estimate.get("weighted_winrate_pct")
    story.extend(
        [
            p("AETHERDECK / COMPETITIVE PRIMER", "SmallPro"),
            Spacer(1, 6 * mm),
            p(name, "TitlePro"),
            p(
                f"{fmt.upper()} | {counts['main']} main / {counts['side']} side | {stamp}",
                "SmallPro",
            ),
            Spacer(1, 8 * mm),
        ]
    )
    if guide.get("tier_assessment"):
        score = [
            p("POSIZIONE NEL CAMPO ATTESO", "StatLabel"),
            p(guide["tier_assessment"], "SmallPro"),
        ]
    else:  # archived versions
        score = [
            p("VALUTAZIONE (VERSIONE STORICA)", "StatLabel"),
            p(f"{guide.get('pro_score', '-')}/10", "StatValue"),
        ]
    weighted = [
        p("STIMA DEL MODELLO Bo3, NON DATI DI PARTITE", "StatLabel"),
        p(f"{wr:.1f}%" if wr is not None else "Non disponibile", "StatValue"),
        p(f"Copertura {estimate.get('coverage_pct', 0)}% del meta", "SmallPro"),
    ]
    stats = Table(
        [[score, weighted]],
        colWidths=[64 * mm, 106 * mm],
        hAlign="LEFT",
        style=[
            ("BACKGROUND", (0, 0), (-1, -1), PALE),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("LINEBEFORE", (1, 0), (1, 0), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ],
    )
    story.extend(
        [
            stats,
            Spacer(1, 6 * mm),
            p(
                estimate.get("note", "Le stime AI non sono risultati di partite."),
                "SmallPro",
            ),
        ]
    )
    if estimate.get("rows"):
        story.append(p("Il campo atteso", "Heading2"))
        data_table(
            ["Archetipo", "Quota meta", "WR teorico Bo3"],
            [
                [r["archetype"], f"{r['share_pct']}%", f"{r['winrate_pct']}%"]
                for r in estimate["rows"]
            ],
            [90 * mm, 35 * mm, 45 * mm],
        )
    if estimate.get("source"):
        story.append(
            p(
                f"Fonte: {estimate['source']} | Snapshot {estimate.get('snapshot_id', '-')}",
                "SmallPro",
            )
        )
    if guide.get("rules_warnings"):
        story.append(
            p(
                "VERSIONE STORICA CON RILIEVI DI REGOLE: consultare le note di revisione prima dell’uso.",
                "SmallPro",
            )
        )
    review = guide.get("quality_review") or {}
    if review.get("status") == "warnings":
        story.append(
            p(
                "PUBBLICATA CON PUNTI DA VERIFICARE: vedi il capitolo Piano di gioco.",
                "SmallPro",
            )
        )
    required = {image_key(c["card_name"]) for c in decklist}
    required.update(
        image_key(c.get("card_name", "")) for c in guide.get("card_roles", [])
    )
    required.update(
        image_key(n)
        for ex in guide.get("mulligan_examples", [])
        for n in ex.get("hand_cards", [])
    )
    missing = required.difference(card_images)
    if missing:
        story.append(
            p(
                f"{len(missing)} immagini non disponibili in questo export. I riquadri mantengono nome e quantità; scarica di nuovo il PDF quando la connessione è disponibile.",
                "SmallPro",
            )
        )

    source_notes = [p("FONTI E CONTESTO", "StatLabel")]
    if guide.get("evidence"):
        source_notes.append(p(guide["evidence"], "SmallPro"))
    source_notes.append(
        p(f"Modello: {guide.get('model_id', 'non documentato')}", "SmallPro")
    )
    source_notes.append(p("Immagini delle carte: Scryfall.", "SmallPro"))
    source_notes.append(
        p(
            estimate.get(
                "formula", "Stima ponderata non disponibile per questa versione."
            ),
            "SmallPro",
        )
    )
    if estimate.get("missing_archetypes"):
        source_notes.append(
            p(
                "Matchup senza stima: " + ", ".join(estimate["missing_archetypes"]),
                "SmallPro",
            )
        )
    story.extend([Spacer(1, 4 * mm), KeepTogether(source_notes)])

    story.extend(
        [
            PageBreak(),
            p("Dentro la guida", "Heading1"),
            p(
                "Lista illustrata, mani di esempio, scelte tecniche e piani per ogni avversario.",
                "SmallPro",
            ),
            Spacer(1, 7 * mm),
        ]
    )
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "Contents",
            fontName=FONT,
            fontSize=10.5,
            leading=16,
            leftIndent=0,
            spaceBefore=8,
            textColor=INK,
        )
    ]
    story.append(toc)

    chapter("Lista di riferimento")
    columns = []
    for boards in (("main",), ("side", "companion")):
        column = []
        for board in boards:
            rows = [c for c in decklist if c["board"] == board]
            if rows:
                label = {
                    "main": "Mainboard",
                    "side": "Sideboard",
                    "companion": "Companion",
                }[board]
                column.append(p(f"{label} ({counts[board]})", "CardTitle"))
                column.extend(
                    p(f"{c['quantity']}x {c['card_name']}", "DeckLine") for c in rows
                )
        columns.append(column)
    text_list = Table(
        [columns],
        colWidths=[100 * mm, 70 * mm],
        hAlign="LEFT",
        splitInRow=1,
        style=[
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ],
    )
    story.append(text_list)

    def card_caption(entry):
        front = entry["card_name"].split(" // ")[0]
        return Paragraph(
            f"<b>{int(entry['quantity'])}x</b> {escape(pdf_text(front))}", styles["CardCaption"]
        )

    def tile(entry, label, caption_height):
        return Table(
            [[picture(entry["card_name"], 28 * mm)], [label]],
            colWidths=[32 * mm],
            rowHeights=[41 * mm, caption_height],
            style=[
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("TOPPADDING", (0, 0), (-1, 0), 1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1 * mm),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 1 * mm),
            ],
        )

    if decklist:
        story.append(PageBreak())
    for board, label in (
        ("main", "Mainboard"),
        ("side", "Sideboard"),
        ("companion", "Companion"),
    ):
        entries = [c for c in decklist if c["board"] == board]
        if not entries:
            continue
        heading = [
            p(f"{label} / vista carte", "CardTitle"),
            p(
                f"{counts[board]} carte - quantità indicate su ogni figurina",
                "SmallPro",
            ),
        ]
        rows = [[heading, "", "", "", ""]]
        for start in range(0, len(entries), 5):
            chunk = entries[start : start + 5]
            labels = [card_caption(c) for c in chunk]
            caption_height = max(
                9 * mm,
                max(label.wrap(30 * mm, 100 * mm)[1] for label in labels) + 1 * mm,
            )
            cells = [
                tile(c, caption, caption_height) for c, caption in zip(chunk, labels, strict=True)
            ]
            rows.append(cells + [""] * (5 - len(cells)))
        story.append(
            Table(
                rows,
                colWidths=[34 * mm] * 5,
                repeatRows=1,
                hAlign="LEFT",
                style=[
                    ("SPAN", (0, 0), (-1, 0)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 1.5 * mm),
                ],
            )
        )

    chapter("Piano di gioco")
    if review.get("status") == "warnings":
        section(
            "Punti da verificare (revisione non conclusa)",
            "\n".join(review.get("open_issues") or []),
        )
    if guide.get("rules_warnings"):
        section(
            "Note di revisione della versione storica",
            "\n".join(guide["rules_warnings"]),
        )
    for title, field in [
        ("Tesi competitiva", "executive_summary"),
        ("Posizione nel campo atteso", "tier_assessment"),
        ("Valutazione della versione storica", "pro_score_rationale"),
        ("Posizionamento", "meta_positioning"),
        ("Soglie del formato", "format_context_and_magic_numbers"),
        ("Manabase e probabilità", "manabase_and_probability_analysis"),
        ("Turni 1-3", "early_game_plan"),
        ("Turni 4-6", "mid_game_plan"),
        ("Finale", "late_game_plan"),
    ]:
        section(title, guide.get(field))

    chapter("Mulligan ed esempi", break_before=False)
    if guide.get("mulligan_heuristics"):
        story.append(p(guide["mulligan_heuristics"]))
    for index, ex in enumerate(guide.get("mulligan_examples", []), 1):
        hand = ex.get("hand_cards", [])
        row = Table(
            [[picture(n, 22 * mm) for n in hand]],
            colWidths=[WIDTH / max(1, len(hand))] * len(hand),
            hAlign="LEFT",
            style=[
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ],
        )
        story.append(
            KeepTogether(
                [
                    p(f"Mano {index} / {ex.get('verdict', '')}", "Heading2"),
                    p(ex.get("context"), "SmallPro"),
                    row,
                    p(" / ".join(hand), "SmallPro"),
                    p(ex.get("analysis")),
                    Spacer(1, 3 * mm),
                ]
            )
        )

    chapter("Scelte carta per carta")
    story.append(
        p(
            "Copie, ruolo e decisioni di sequenziamento. Le carte a doppia faccia sono mostrate da entrambi i lati quando disponibili.",
            "SmallPro",
        )
    )
    for card in guide.get("card_roles", []):
        card_name = card.get("card_name", "")
        has_back = bool(card_images.get(image_key(card_name) + "::back"))
        if has_back:
            art = Table(
                [
                    [
                        picture(card_name, 32 * mm),
                        picture(card_name, 32 * mm, back=True),
                    ],
                    [p("FRONTE", "SmallPro"), p("RETRO", "SmallPro")],
                ],
                colWidths=[35 * mm] * 2,
                style=[
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            )
            widths = [74 * mm, 96 * mm]
        else:
            art = picture(card_name, 34 * mm)
            widths = [41 * mm, 129 * mm]
        text = [
            p(f"{card.get('quantity')}x {card_name}", "CardTitle"),
            p(card.get("role_category"), "SmallPro"),
            p(card.get("explanation")),
        ]
        if card.get("alternatives_considered"):
            text.append(p("Alternative: " + card["alternatives_considered"], "SmallPro"))
        block = Table(
            [[art, text]],
            colWidths=widths,
            hAlign="LEFT",
            splitInRow=1,
            style=[
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ],
        )
        story.append(block)

    chapter("Sinergie e linee")
    for synergy in guide.get("synergies", []):
        section(
            " + ".join(synergy.get("cards_involved", [])), synergy.get("description")
        )
    section("Punti di forza", "\n".join(guide.get("strengths", [])))
    section("Vulnerabilità", "\n".join(guide.get("weaknesses", [])))
    section("Tips e micro-interazioni", "\n\n".join(guide.get("tips_and_tricks", [])))
    for item in guide.get("excluded_cards_and_donts", []):
        section("Esclusa: " + item.get("card_name", ""), item.get("why_excluded"))
    if guide.get("flex_slots"):
        section(
            "Flex slot e quando cambiarli",
            "\n".join(f"{f.get('card_name')}: {f.get('trigger')}" for f in guide["flex_slots"]),
        )

    plans = guide.get("sideboard_guide", [])
    matrix = {}
    for index, plan in enumerate(plans):
        for field, sign in (("cards_in", 1), ("cards_out", -1)):
            for item in plan.get(field, []):
                row = matrix.setdefault(item["card_name"], {})
                row[index] = row.get(index, 0) + sign * item["quantity"]
    if matrix and plans:
        chapter("Matrice di sideboard")
        story.append(
            p("Piano base: copie in entrata (+) e in uscita (-) per matchup.", "SmallPro")
        )
        column = max(12 * mm, (WIDTH - 48 * mm) / len(plans))
        data_table(
            ["Carta"] + [plan.get("opponent_archetype", "") for plan in plans],
            [
                [name]
                + [
                    (f"+{v}" if v > 0 else str(v)) if (v := row.get(i, 0)) else "."
                    for i in range(len(plans))
                ]
                for name, row in sorted(
                    matrix.items(), key=lambda kv: (min(kv[1].values()), kv[0])
                )
            ],
            [48 * mm] + [column] * len(plans),
        )

    for plan in guide.get("sideboard_guide", []):
        chapter("Matchup / " + plan.get("opponent_archetype", ""))
        confidence = plan.get("confidence")
        story.append(
            p(
                f"{plan.get('matchup_difficulty', '')} - stima del modello Bo3 {plan.get('expected_winrate_pct')}%"
                + (f" - confidenza {confidence}" if confidence else ""),
                "SmallPro",
            )
        )
        for title, field in [
            ("Motivo della stima", "estimate_rationale"),
            ("Ruolo pre-side", "role_pre_side"),
            ("Ruolo post-side", "role_post_side"),
            ("Game 1", "gameplan_pre_side"),
            ("Game 2/3", "gameplan_post_side"),
            ("On the play", "on_the_play_notes"),
            ("On the draw", "on_the_draw_notes"),
            ("Mulligan target", "mulligan_target"),
        ]:
            section(title, plan.get(field))
        if plan.get("opponent_key_cards"):
            story.append(p("Carte avversarie da rispettare", "Heading2"))
            data_table(
                ["Carta", "Perché conta", "Nostra risposta"],
                [
                    [k.get("card_name"), k.get("why_it_matters"), k.get("our_answer")]
                    for k in plan["opponent_key_cards"]
                ],
                [42 * mm, 64 * mm, 64 * mm],
            )
        if plan.get("expected_opponent_sideboard"):
            section(
                "Loro sideboard prevista", ", ".join(plan["expected_opponent_sideboard"])
            )
        for label, inf, outf, side in [
            ("Piano base", "cards_in", "cards_out", None),
            ("On the play", "on_the_play_in", "on_the_play_out", "play"),
            ("On the draw", "on_the_draw_in", "on_the_draw_out", "draw"),
        ]:
            if side and plan.get(f"on_the_{side}_uses_base"):
                story.append(p(f"{label}: sidata identica al piano base.", "SmallPro"))
                continue
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
                data_table(
                    ["", "Copie", "Carta", "Motivo"],
                    rows,
                    [12 * mm, 15 * mm, 55 * mm, 88 * mm],
                )
        bullets(plan.get("pro_tips"))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(20 * mm, 17 * mm, 190 * mm, 17 * mm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            20 * mm,
            12 * mm,
            "AETHERDECK / Stime teoriche - verificare la legalità prima del torneo",
        )
        canvas.drawRightString(190 * mm, 12 * mm, str(doc.page))
        if doc.page > 1:
            canvas.setFont(FONT_BOLD, 7)
            canvas.setFillColor(INK)
            canvas.drawString(20 * mm, 284 * mm, "AETHERDECK / " + fmt.upper())
            canvas.setFont(FONT, 7)
            canvas.drawRightString(
                190 * mm, 284 * mm, pdf_text(getattr(doc, "_current_section", ""))
            )
            canvas.setStrokeColor(GOLD)
            canvas.line(20 * mm, 281 * mm, 190 * mm, 281 * mm)
        canvas.restoreState()

    class PrimerDoc(SimpleDocTemplate):
        def beforeDocument(self):
            self._heading_count = 0
            self._current_section = ""

        def afterPage(self):
            footer(self.canv, self)

        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and flowable.style.name == "Heading1":
                title = flowable.getPlainText()
                self._current_section = title
                self._heading_count += 1
                anchor = f"section-{self._heading_count}"
                self.canv.bookmarkPage(anchor)
                self.canv.addOutlineEntry(title, anchor, level=0)
                if title != "Dentro la guida":
                    self.notify("TOCEntry", (0, escape(title), self.page, anchor))

    doc = PrimerDoc(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=23 * mm,
        bottomMargin=24 * mm,
        title=name + " - Competitive Primer",
        author="Aetherdeck",
    )
    doc.multiBuild(story)
    return buffer.getvalue()
