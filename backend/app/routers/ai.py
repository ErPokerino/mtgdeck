from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AIRun, GuideJob, utcnow
from app.services import guide_jobs
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


@router.post("/guide-jobs")
def start_guide_job(
    payload: AIDeckGuideRequest,
    resume_id: int | None = None,
    legacy_run_id: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        return guide_jobs.create_job(db, payload, resume_id, legacy_run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/guide-jobs")
def guide_job_list(format_id: str, db: Session = Depends(get_db)):
    jobs = (
        db.query(GuideJob)
        .filter_by(format_id=format_id)
        .order_by(GuideJob.id.desc())
        .limit(10)
        .all()
    )
    active = (
        db.query(GuideJob)
        .filter(
            GuideJob.format_id == format_id, GuideJob.status.in_(["running", "queued"])
        )
        .all()
    )
    jobs = sorted(
        {j.id: j for j in [*jobs, *active]}.values(), key=lambda j: j.id, reverse=True
    )
    return {
        "jobs": [guide_jobs.public_job(j) for j in jobs],
        "legacy_drafts": guide_jobs.legacy_drafts(db, format_id),
    }


@router.get("/guide-jobs/{job_id}")
def get_guide_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GuideJob, job_id)
    if not job:
        raise HTTPException(404, "Analisi non trovata")
    return guide_jobs.public_job(job)


@router.post("/guide-jobs/{job_id}/cancel")
def cancel_guide_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GuideJob, job_id)
    if not job:
        raise HTTPException(404, "Analisi non trovata")
    if job.status in ("queued", "running"):
        db.query(GuideJob).filter(
            GuideJob.id == job_id, GuideJob.status.in_(["queued", "running"])
        ).update(
            {"status": "cancelled", "phase": "cancelled", "finished_at": utcnow()},
            synchronize_session=False,
        )
        db.commit()
        db.refresh(job)
    return guide_jobs.public_job(job)


@router.post("/guide-jobs/{job_id}/resume")
def resume_guide_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GuideJob, job_id)
    if not job:
        raise HTTPException(404, "Analisi non trovata")
    return start_guide_job(
        AIDeckGuideRequest.model_validate(job.request_json), resume_id=job_id, db=db
    )


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
