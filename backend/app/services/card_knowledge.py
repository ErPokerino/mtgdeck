"""Scryfall rulings and functional Tagger tags, keyed by Oracle identity.

Both come from Scryfall bulk files: they give the AI official rulings instead of
hand-written rule patches, and let the app count interaction (removal, counters,
draw...) deterministically.
"""

import gzip
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import orjson
from sqlalchemy.orm import Session

from app.models import CardRuling, CardTag

# Tagger slugs worth tracking for deckbuilding; descendants are folded into each one.
FUNCTIONAL_TAGS = [
    "removal",
    "removal-creature",
    "removal-artifact",
    "removal-enchantment",
    "removal-planeswalker",
    "removal-exile",
    "sweeper",
    "burn",
    "counterspell",
    "draw",
    "card-advantage",
    "cantrip",
    "discard",
    "hate-graveyard",
    "ramp",
    "mana-dork",
    "tutor",
    "lifegain",
    "recursion",
    "reanimate",
    "protection",
    "bounce",
    "sacrifice-outlet",
    "combat-trick",
    "graveyard-fuel",
    "mill",
]

# Derived tags: a Tagger subtree without the branches that do not do what its name says.
# "card-advantage" folds in cantrips, loot and rummage, which leave the number of cards
# in hand unchanged: a burn deck full of cantrips would look like a control deck.
# "card-advantage-net" keeps the cards that gain cards. Impulse and consult stay: "look
# at the top N, put two in hand" (Memory Deluge) is real advantage.
CARD_NEUTRAL_TAGS = (
    "cantrip",
    "delayed-cantrip",
    "brainstorm",
    "sift",
    "loot",
    "loot-to-exile",
    "loot-to-library",
    "rummage",
    "rummage-to-library",
    "repeatable-rummage",
)
# Branches below a pruned tag that still gain a card (discard one, draw two).
CARD_NEUTRAL_KEEP = ("tormenting-voice",)
DERIVED_TAGS = {"card-advantage-net": ("card-advantage", CARD_NEUTRAL_TAGS, CARD_NEUTRAL_KEEP)}


def _jsonl(path: Path) -> Iterable[dict]:
    with gzip.open(path, "rb") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def ingest_rulings(db: Session, path: Path) -> int:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for item in _jsonl(path):
        if item.get("oracle_id") and item.get("comment"):
            grouped[item["oracle_id"]].append(
                {
                    "published_at": item.get("published_at"),
                    "source": item.get("source"),
                    "comment": item["comment"],
                }
            )
    rows = [
        {"oracle_id": oid, "rulings": sorted(r, key=lambda x: x["published_at"] or "")}
        for oid, r in grouped.items()
    ]
    db.query(CardRuling).delete()
    for i in range(0, len(rows), 2000):
        db.bulk_insert_mappings(CardRuling, rows[i : i + 2000])
    db.commit()
    return len(rows)


def expand_tags(
    tags: List[dict],
    wanted: Iterable[str],
    derived: Dict[str, Tuple[str, Sequence[str], Sequence[str]]] = {},  # noqa: B006 - read only
) -> Dict[str, Set[str]]:
    """slug -> oracle ids tagged with it or with any descendant tag.

    `derived` adds tags built from a subtree minus pruned branches:
    name -> (root slug, pruned slugs, slugs kept even below a pruned one)."""
    by_id = {t["id"]: t for t in tags}
    children: Dict[str, List[str]] = defaultdict(list)
    for t in tags:
        for parent in t.get("parent_ids") or []:
            children[parent].append(t["id"])
    by_slug = {t["slug"]: t for t in tags}

    def collect(tag_id: str, seen: Set[str], prune=(), keep=(), pruned=False) -> Set[str]:
        if tag_id in seen or tag_id not in by_id:
            return set()
        seen.add(tag_id)
        slug = by_id[tag_id]["slug"]
        if slug in keep:
            pruned = False
        elif slug in prune:
            pruned = True
        found = set() if pruned else {x["oracle_id"] for x in by_id[tag_id].get("taggings") or []}
        for child in children[tag_id]:
            found |= collect(child, seen, prune, keep, pruned)
        return found

    out = {slug: collect(by_slug[slug]["id"], set()) for slug in wanted if slug in by_slug}
    for name, (root, prune, keep) in derived.items():
        if root in by_slug:
            out[name] = collect(by_slug[root]["id"], set(), set(prune), set(keep))
    return out


def ingest_tags(db: Session, path: Path) -> int:
    expanded = expand_tags(list(_jsonl(path)), FUNCTIONAL_TAGS, DERIVED_TAGS)
    rows = [{"oracle_id": oid, "tag": slug} for slug, oids in expanded.items() for oid in oids]
    db.query(CardTag).delete()
    for i in range(0, len(rows), 5000):
        db.bulk_insert_mappings(CardTag, rows[i : i + 5000])
    db.commit()
    return len(rows)


def tags_for(db: Session, oracle_ids: Iterable[str]) -> Dict[str, List[str]]:
    ids = list(set(oracle_ids))
    result: Dict[str, List[str]] = defaultdict(list)
    if ids:
        for oid, tag in db.query(CardTag.oracle_id, CardTag.tag).filter(
            CardTag.oracle_id.in_(ids)
        ):
            result[oid].append(tag)
    return {oid: sorted(t) for oid, t in result.items()}


def rulings_for(db: Session, oracle_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(set(oracle_ids))
    if not ids:
        return {}
    return {
        r.oracle_id: r.rulings or []
        for r in db.query(CardRuling).filter(CardRuling.oracle_id.in_(ids))
    }
