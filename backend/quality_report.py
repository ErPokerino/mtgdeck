"""Print the quality report of a format, to compare runs before and after a prompt or model change.

Usage (from backend/):
    python quality_report.py pioneer            # readable summary
    python quality_report.py pioneer --json     # full report, e.g. to diff two dates

Uses DATABASE_URL like the app. It never calls the AI; it only creates missing tables.
"""

import json
import sys

from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401  (registers tables)
from app.services.quality import report


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("standard", "pioneer", "modern"):
        sys.exit(__doc__)
    Base.metadata.create_all(engine)  # new quality tables on an older database
    with SessionLocal() as db:
        data = report(db, sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    print(f"Formato {data['format_id']} · snapshot {data['snapshot']['id']} ({data['snapshot']['period']})\n")
    print("Esecuzioni AI")
    for r in data["runs"]:
        print(
            f"  {r['skill']:<16} {r['prompt_version']:<8} {r['model_id']:<22} "
            f"{r['runs']:>3} run, {r['failed']} fallite, {r['with_warnings']} con avvisi, "
            f"{r['avg_duration_s']} s, {r['avg_attempts']} tentativi"
        )
    print("\nRiferimento (consenso) e mazzi generati")
    for d in data["reference"] + data["generated_decks"]:
        print(
            f"  {d['name'][:40]:<40} sovrapposizione {d['consensus_overlap_pct']:>5}% "
            f"deficit {d['total_deficit']} interazione {d['interaction_main']} "
            f"delta non motivati {d.get('unmotivated_deltas', '-')}"
        )
    print("\nGuide")
    for g in data["guides"]:
        print(
            f"  #{g['guide_id']:<4} {g['deck_name'][:32]:<32} matchup {g['matchups_covered']}/{g['matchups_required']} "
            f"parole {g['avg_words_main_matchups']:>4} carte avv. {g['avg_opponent_cards']} "
            f"play/draw {g['play_draw_differentiated']} errori {g['validator_errors']} "
            f"avvisi {g['open_issues']} {g['review_status']}"
        )


if __name__ == "__main__":
    main()
