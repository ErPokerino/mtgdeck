from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AIRun
from app.skills.runner import (
    run_deck_generation_skill,
    run_deck_guide_skill,
    run_matchup_spot_skill,
)
from app.skills.schemas import (
    AIDeckGenerationRequest,
    AIDeckGuideRequest,
    AIMatchupSpotRequest,
)

router = APIRouter(prefix="/api/ai", tags=["AI Skills"])


@router.post("/generate-deck")
def api_generate_deck(
    payload: AIDeckGenerationRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_deck_generation_skill(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/deck-guide")
def api_deck_guide(
    payload: AIDeckGuideRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_deck_guide_skill(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/matchup-spot")
def api_matchup_spot(
    payload: AIMatchupSpotRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_matchup_spot_skill(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs")
def list_ai_runs(
    limit: int = 20, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    runs = db.query(AIRun).order_by(AIRun.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "skill_name": r.skill_name,
            "prompt_version": r.prompt_version,
            "model_id": r.model_id,
            "provider": r.provider,
            "format_id": r.format_id,
            "deck_id": r.deck_id,
            "validation_attempts": r.validation_attempts,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at,
            "status": (r.input_summary or {}).get("status", "completed"),
            "phase": (r.input_summary or {}).get("phase"),
        }
        for r in runs
    ]
