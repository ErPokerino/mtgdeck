"""Run the fixed generation set in config/eval-set.json and compare with the last run.

Usage (from backend/):
    python eval_generation.py                  # every case, default model
    python eval_generation.py --only pioneer-rakdos-kroxa-control
    python eval_generation.py --model gemini-4-argon
    python eval_generation.py --list           # cases, without calling the AI

Each case calls the real AI (generation, critic, possibly a revision): it costs tokens and
takes minutes. Decks are not saved in the library; the AI runs are recorded as usual.
Results go to output/eval/<date>-<prompt version>.json. Uses DATABASE_URL like the app.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from app import models  # noqa: F401  (registers tables)
from app.database import Base, SessionLocal, engine
from app.models import AIRun, MetaArchetype
from app.services import deck_engine
from app.services.quality import consensus_index, deck_metrics
from app.skills.deck_generation import resolve_entries, run_deck_generation_skill
from app.skills.schemas import AIDeckGenerationRequest

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "config" / "eval-set.json"
OUT_DIR = ROOT / "output" / "eval"


def base_archetype_id(db, fmt: str, name: str) -> int:
    snap = deck_engine.latest_snapshot(db, fmt)
    if not snap:
        raise ValueError(f"nessun metagame per {fmt}")
    q = db.query(MetaArchetype).filter(MetaArchetype.snapshot_id == snap.id)
    arch = (
        q.order_by(MetaArchetype.meta_share_pct.desc()).first()
        if name == "top"
        else q.filter(MetaArchetype.name == name).first()
    )
    if not arch:
        raise ValueError(f"archetipo {name!r} non presente nel metagame {fmt}")
    return arch.id


def run_case(db, case: dict, model: str | None) -> dict:
    fmt = case["format_id"]
    req = AIDeckGenerationRequest(
        format_id=fmt,
        archetype=case.get("archetype"),
        colors=case.get("colors", []),
        build_around_cards=case.get("build_around_cards", []),
        prompt=case.get("prompt", ""),
        base_archetype_id=base_archetype_id(db, fmt, case["base_archetype"]) if case.get("base_archetype") else None,
        model_id=model,
        save_deck=False,
    )
    started = time.time()
    result = run_deck_generation_skill(db, req)
    out = result["ai_result"]
    entries = resolve_entries(db, out)
    metrics = deck_metrics(db, entries, consensus_index(db, deck_engine.latest_snapshot(db, fmt)))
    run = db.query(AIRun).filter_by(skill_name="deck_generation").order_by(AIRun.id.desc()).first()
    critic = result["critic"]
    structure = result["analysis"].get("structure", {})
    return {
        "id": case["id"],
        "ok": True,
        "deck_name": out.deck_name,
        "prompt_version": result["meta"]["prompt_version"],
        "model_id": result["meta"]["model_id"],
        "duration_s": round(time.time() - started),
        "ai_calls": result["meta"]["ai_calls"],
        "tokens": (run.usage_json or {}) if run else {},
        "structure": structure.get("values"),
        "built_like": [f"{n['archetype']} ({n['category']})" for n in structure.get("nearest", [])],
        "critic_verdict": critic.verdict if critic else None,
        "critic_high_issues": sum(1 for i in critic.issues if i.severity == "alta") if critic else None,
        "revision_applied": result["revision"]["applied"],
        "warnings": result["warnings"],
        "metrics": metrics,
        "main": {s.card_name: s.quantity for s in out.mainboard},
        "side": {s.card_name: s.quantity for s in out.sideboard},
    }


def summary_line(r: dict) -> str:
    if not r.get("ok"):
        return f"{r['id']:<32} ERRORE: {r['error']}"
    m = r["metrics"]
    s = r["structure"] or {}
    return (
        f"{r['id']:<32} {r['duration_s']:>4}s  avvisi {len(r['warnings'])}  "
        f"critico {r['critic_verdict']} (alte {r['critic_high_issues']})  "
        f"deficit {m['total_deficit']}  interazione {m['interaction_main']}  "
        f"creature {s.get('creatures', '-')}  costruita come {', '.join(r['built_like'][:2]) or '-'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", help="esegui solo questo caso (ripetibile)")
    parser.add_argument("--model", help="modello da usare al posto di quello predefinito")
    parser.add_argument("--list", action="store_true", help="mostra i casi senza eseguirli")
    args = parser.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if args.only:
        unknown = set(args.only) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Casi sconosciuti: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.only]
    if args.list:
        for c in cases:
            print(f"{c['id']:<32} {c.get('note', '')}")
        return

    Base.metadata.create_all(engine)
    previous = sorted(OUT_DIR.glob("*.json"))
    results = []
    with SessionLocal() as db:
        for case in cases:
            print(f"-> {case['id']} ...", flush=True)
            try:
                results.append(run_case(db, case, args.model))
            except Exception as exc:  # noqa: BLE001 - one failed case must not hide the others
                db.rollback()
                results.append({"id": case["id"], "ok": False, "error": str(exc)})
            print("   " + summary_line(results[-1]), flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    version = next((r["prompt_version"] for r in results if r.get("ok")), "n-d")
    path = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M}-{version}.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nRisultati: {path}")

    if previous:
        before = {r["id"]: r for r in json.loads(previous[-1].read_text(encoding="utf-8"))}
        print(f"Confronto con {previous[-1].name}:")
        for r in results:
            old = before.get(r["id"])
            if old:
                print("  prima: " + summary_line(old))
                print("  ora:   " + summary_line(r))


if __name__ == "__main__":
    main()
