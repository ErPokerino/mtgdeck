from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AIJob, AIRun, GuideJob, utcnow
from app.services import ai_jobs, assistant_agent, guide_jobs
from app.skills.deck_generation import run_deck_generation_skill
from app.skills.runner import (
    run_deck_guide_skill,
    run_deck_improvement_skill,
    run_matchup_spot_skill,
)
from app.skills.schemas import (
    AIDeckGenerationRequest,
    AIDeckGuideRequest,
    AIDeckImprovementRequest,
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
        raise HTTPException(400, str(exc)) from exc


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


@router.post("/jobs/deck-generation")
def start_deck_generation_job(
    payload: AIDeckGenerationRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return ai_jobs.create_job(db, "deck_generation", payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/jobs/matchup-spot")
def start_matchup_job(
    payload: AIMatchupSpotRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return ai_jobs.create_job(db, "matchup_spot", payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/jobs/deck-improvement")
def start_deck_improvement_job(
    payload: AIDeckImprovementRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return ai_jobs.create_job(db, "deck_improvement", payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/jobs")
def list_ai_jobs(format_id: str, kind: str, db: Session = Depends(get_db)):
    """Active jobs plus the latest finished one: enough to resume after a reload."""
    jobs = (
        db.query(AIJob)
        .filter(AIJob.format_id == format_id, AIJob.kind == kind)
        .order_by(AIJob.id.desc())
        .limit(5)
        .all()
    )
    return {"jobs": [ai_jobs.public_job(j) for j in jobs]}


@router.get("/jobs/{job_id}")
def get_ai_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(AIJob, job_id)
    if not job:
        raise HTTPException(404, "Analisi non trovata")
    return ai_jobs.public_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_ai_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(AIJob, job_id)
    if not job:
        raise HTTPException(404, "Analisi non trovata")
    return ai_jobs.cancel_job(db, job)


@router.post("/generate-deck")
def api_generate_deck(
    payload: AIDeckGenerationRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_deck_generation_skill(db, payload)
    except Exception as exc:  # noqa: BLE001 - synchronous endpoint: any failure is the user's 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/deck-guide")
def api_deck_guide(
    payload: AIDeckGuideRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_deck_guide_skill(db, payload)
    except Exception as exc:  # noqa: BLE001 - synchronous endpoint: any failure is the user's 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/matchup-spot")
def api_matchup_spot(
    payload: AIMatchupSpotRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_matchup_spot_skill(db, payload)
    except Exception as exc:  # noqa: BLE001 - synchronous endpoint: any failure is the user's 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/improve-deck")
def api_improve_deck(
    payload: AIDeckImprovementRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return run_deck_improvement_skill(db, payload)
    except Exception as exc:  # noqa: BLE001 - synchronous endpoint: any failure is the user's 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/chat")
def api_agent_chat(
    payload: assistant_agent.AgentChatRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        return assistant_agent.run_assistant_agent(db, payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agent/tools")
def api_agent_tools() -> Dict[str, Any]:
    return {
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in assistant_agent.AGENT_TOOL_DECLARATIONS
        ]
    }


@router.websocket("/agent/live")
async def ws_agent_live(
    websocket: WebSocket,
    format_id: str = "pioneer",
    active_deck_id: Optional[int] = None,
    active_deck_name: Optional[str] = None,
    active_tab: Optional[str] = None,
    db: Session = Depends(get_db),
) -> None:
    await assistant_agent.run_live_voice_session(
        websocket=websocket,
        db=db,
        format_id=format_id,
        active_deck_id=active_deck_id,
        active_deck_name=active_deck_name,
        active_tab=active_tab,
    )


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
