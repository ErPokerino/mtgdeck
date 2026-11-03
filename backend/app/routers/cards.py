import re
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, not_, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Card, MetaCardStat, MetaSnapshot
from app.schemas import CardMetaInfo, CardOut, CardSearchResponse
from app.services.scryfall_sync import normalize_card_name, sort_colors_wubrg

router = APIRouter(prefix="/api/cards", tags=["Cards"])


def get_meta_stats_map(
    db: Session, format_id: str, oracle_ids: List[str], card_names: List[str]
) -> Dict[str, CardMetaInfo]:
    """Recupera le statistiche di presenza nel meta per un elenco di carte nel formato selezionato."""
    if not oracle_ids and not card_names:
        return {}
    latest_snap = (
        db.query(MetaSnapshot)
        .filter(MetaSnapshot.format_id == format_id.lower())
        .order_by(MetaSnapshot.fetched_at.desc())
        .first()
    )
    if not latest_snap:
        return {}

    stats = (
        db.query(MetaCardStat)
        .filter(
            MetaCardStat.snapshot_id == latest_snap.id,
            or_(
                MetaCardStat.oracle_id.in_(oracle_ids),
                MetaCardStat.card_name.in_(card_names),
            ),
        )
        .all()
    )
    out: Dict[str, CardMetaInfo] = {}
    for st in stats:
        info = CardMetaInfo(
            overall_presence_pct=st.overall_presence_pct,
            main_presence_pct=st.main_presence_pct,
            main_avg_copies=st.main_avg_copies,
            side_presence_pct=st.side_presence_pct,
            side_avg_copies=st.side_avg_copies,
            top_archetypes=st.top_archetypes or [],
        )
        if st.oracle_id:
            out[st.oracle_id] = info
        out[st.card_name.lower()] = info
    return out


def _build_fts5_match_expr(raw_query: str, column: Optional[str] = None) -> str:
    tokens = re.findall(r"[A-Za-z0-9']+", raw_query)
    if not tokens:
        return ""
    parts = []
    for tok in tokens:
        clean = tok.replace("'", "")
        if not clean:
            continue
        if column:
            parts.append(f'{column}:"{clean}"*')
        else:
            parts.append(f'"{clean}"*')
    return " AND ".join(parts)


@router.get("/search", response_model=CardSearchResponse)
def search_cards(
    format_id: str = Query("standard", description="standard | pioneer | modern | all"),
    include_banned: bool = Query(
        False, description="Includi carte bandite nel formato"
    ),
    q: Optional[str] = Query(None, description="Testo nel nome della carta"),
    oracle_q: Optional[str] = Query(
        None, description="Testo nelle regole Oracle della carta"
    ),
    set_code: Optional[str] = Query(None, description="Codice set (es. dsk, blb, mh3)"),
    colors: Optional[str] = Query(
        None, description="Colori separati da virgola: W,U,B,R,G,C"
    ),
    color_mode: str = Query(
        "include", description="include | exact | at_most | identity"
    ),
    cmc_min: Optional[float] = Query(None),
    cmc_max: Optional[float] = Query(None),
    cmc_exact: Optional[float] = Query(None),
    power_min: Optional[float] = Query(None),
    power_max: Optional[float] = Query(None),
    power_exact: Optional[str] = Query(None),
    toughness_min: Optional[float] = Query(None),
    toughness_max: Optional[float] = Query(None),
    toughness_exact: Optional[str] = Query(None),
    rarity: Optional[str] = Query(None, description="common,uncommon,rare,mythic"),
    card_type: Optional[str] = Query(
        None, description="Tipo o sottotipo (es. Creature, Instant, Goblin)"
    ),
    sort_by: str = Query(
        "cmc_asc",
        description="cmc_asc | cmc_desc | name_asc | rarity_desc | released_desc",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=120),
    db: Session = Depends(get_db),
):
    query = db.query(Card)
    fmt = format_id.lower()

    # 1. Filtro Formato & Legalità
    if fmt in ("standard", "pioneer", "modern"):
        leg_col = getattr(Card, f"legality_{fmt}")
        if include_banned:
            query = query.filter(leg_col.in_(["legal", "banned"]))
        else:
            query = query.filter(leg_col == "legal")

    # 2. Ricerca Testo nel Nome e/o Testo Regole Oracle
    if q and q.strip():
        norm_q = normalize_card_name(q)
        for token in norm_q.split():
            query = query.filter(Card.normalized_name.contains(token))

    if oracle_q and oracle_q.strip():
        for term in oracle_q.strip().split():
            query = query.filter(Card.oracle_text.ilike(f"%{term}%"))

    # 3. Filtro Set
    if set_code and set_code.strip():
        codes = [c.strip().lower() for c in set_code.split(",") if c.strip()]
        if codes:
            query = query.filter(Card.set_code.in_(codes))

    # 4. Filtro Colori
    if colors and colors.strip():
        raw_cols = [c.strip().upper() for c in colors.split(",") if c.strip()]
        if "C" in raw_cols and len(raw_cols) == 1:
            # Incolore
            query = query.filter(Card.color_key == "")
        else:
            selected_wubrg = sort_colors_wubrg(
                [c for c in raw_cols if c in ("W", "U", "B", "R", "G")]
            )
            if selected_wubrg:
                target_key = "".join(selected_wubrg)
                all_wubrg = {"W", "U", "B", "R", "G"}
                excluded_cols = all_wubrg - set(selected_wubrg)

                if color_mode == "exact":
                    query = query.filter(Card.color_key == target_key)
                elif color_mode == "at_most":
                    # Può contenere solo un sottoinsieme dei colori selezionati (esclusi gli altri)
                    for exc in excluded_cols:
                        query = query.filter(not_(Card.color_key.contains(exc)))
                elif color_mode == "identity":
                    for exc in excluded_cols:
                        query = query.filter(
                            not_(Card.color_identity_key.contains(exc))
                        )
                else:
                    # "include": deve includere tutti i colori selezionati
                    for inc in selected_wubrg:
                        query = query.filter(Card.color_key.contains(inc))

    # 5. Filtro Costo di Mana (CMC / Mana Value)
    if cmc_exact is not None:
        query = query.filter(Card.cmc == cmc_exact)
    else:
        if cmc_min is not None:
            query = query.filter(Card.cmc >= cmc_min)
        if cmc_max is not None:
            query = query.filter(Card.cmc <= cmc_max)

    # 6. Filtro Forza (Power)
    if power_exact is not None and power_exact.strip() != "":
        query = query.filter(Card.power == power_exact.strip())
    else:
        if power_min is not None:
            query = query.filter(Card.power_num >= power_min)
        if power_max is not None:
            query = query.filter(Card.power_num <= power_max)

    # 7. Filtro Costituzione (Toughness)
    if toughness_exact is not None and toughness_exact.strip() != "":
        query = query.filter(Card.toughness == toughness_exact.strip())
    else:
        if toughness_min is not None:
            query = query.filter(Card.toughness_num >= toughness_min)
        if toughness_max is not None:
            query = query.filter(Card.toughness_num <= toughness_max)

    # 8. Filtro Rarità
    if rarity and rarity.strip():
        rarities = [r.strip().lower() for r in rarity.split(",") if r.strip()]
        if rarities:
            query = query.filter(Card.rarity.in_(rarities))

    # 9. Filtro Tipo / Sottotipo
    if card_type and card_type.strip():
        for token in card_type.strip().split():
            query = query.filter(Card.type_line.ilike(f"%{token}%"))

    total = query.count()

    # 10. Ordinamento
    if sort_by == "meta_desc" and fmt in ("standard", "pioneer", "modern"):
        latest_snap = (
            db.query(MetaSnapshot)
            .filter(MetaSnapshot.format_id == fmt)
            .order_by(MetaSnapshot.fetched_at.desc())
            .first()
        )
        if latest_snap:
            query = query.outerjoin(
                MetaCardStat,
                and_(
                    MetaCardStat.oracle_id == Card.oracle_id,
                    MetaCardStat.snapshot_id == latest_snap.id,
                ),
            ).order_by(
                func.coalesce(MetaCardStat.overall_presence_pct, 0.0).desc(),
                Card.cmc.asc(),
                Card.name.asc(),
            )
        else:
            query = query.order_by(Card.cmc.asc(), Card.name.asc())
    elif sort_by == "rarity_desc":
        rarity_rank = case(
            (Card.rarity == "mythic", 4),
            (Card.rarity == "rare", 3),
            (Card.rarity == "uncommon", 2),
            else_=1,
        )
        query = query.order_by(rarity_rank.desc(), Card.cmc.asc(), Card.name.asc())
    elif sort_by == "cmc_desc":
        query = query.order_by(Card.cmc.desc(), Card.name.asc())
    elif sort_by == "name_asc":
        query = query.order_by(Card.name.asc())
    elif sort_by == "released_desc":
        query = query.order_by(Card.released_at.desc(), Card.name.asc())
    else:
        query = query.order_by(Card.cmc.asc(), Card.name.asc())

    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    meta_map = get_meta_stats_map(
        db,
        fmt if fmt in ("standard", "pioneer", "modern") else "standard",
        [c.oracle_id for c in results],
        [c.name for c in results],
    )

    cards_out: List[CardOut] = []
    for c in results:
        c_out = CardOut.model_validate(c)
        c_out.meta_info = (
            meta_map.get(c.oracle_id)
            or meta_map.get(c.name.lower())
            or meta_map.get(c.name.split(" // ")[0].lower())
        )
        cards_out.append(c_out)

    return CardSearchResponse(
        total=total,
        page=page,
        page_size=page_size,
        cards=cards_out,
    )


@router.get("/{oracle_id}", response_model=CardOut)
def get_card_detail(
    oracle_id: str,
    format_id: str = Query("standard"),
    db: Session = Depends(get_db),
):
    card = db.query(Card).filter(Card.oracle_id == oracle_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Carta non trovata")

    meta_map = get_meta_stats_map(db, format_id, [card.oracle_id], [card.name])
    c_out = CardOut.model_validate(card)
    c_out.meta_info = (
        meta_map.get(card.oracle_id)
        or meta_map.get(card.name.lower())
        or meta_map.get(card.name.split(" // ")[0].lower())
        or CardMetaInfo()
    )
    from app.services.card_knowledge import rulings_for, tags_for

    c_out.rulings = rulings_for(db, [card.oracle_id]).get(card.oracle_id, [])
    c_out.functional_tags = tags_for(db, [card.oracle_id]).get(card.oracle_id, [])
    return c_out


@router.get("/{oracle_id}/tokens", response_model=List[CardOut])
def get_related_tokens(oracle_id: str, db: Session = Depends(get_db)):
    from app.services.card_tokens import related_tokens
    import httpx

    card = db.get(Card, oracle_id)
    if not card:
        raise HTTPException(404, "Carta non trovata")
    try:
        return related_tokens(card.scryfall_id)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            503,
            "Pedine Scryfall non disponibili. Riprova o crea una pedina personalizzata.",
        ) from exc
