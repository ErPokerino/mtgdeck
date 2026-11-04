"""Durable deck generation and matchup analysis.

Both take minutes: running them in a worker lets the page report the real phase,
survive a reload and be cancelled, as guide jobs already do.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.database import SessionLocal
from app.models import AIJob, utcnow
from app.services.ai_provider import get_skill_model_and_config
from app.services.guide_jobs import _is_provider_failure
from app.skills.schemas import AIDeckGenerationRequest, AIMatchupSpotRequest

KINDS = {
    "deck_generation": AIDeckGenerationRequest,
    "matchup_spot": AIMatchupSpotRequest,
}
MAX_ACTIVE = 2
CANCELLED = "Generazione annullata."

_executor = ThreadPoolExecutor(max_workers=MAX_ACTIVE, thread_name_prefix="ai-job")
_lock = threading.Lock()
_workers = set()
log = logging.getLogger("uvicorn.error")


def _stamp(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def job_label(kind, request):
    if kind == "matchup_spot":
        return f"{request.get('deck_a_name')} contro {request.get('deck_b_name')}"
    colors = "".join(request.get("colors") or []) or "colori liberi"
    start = "consenso del meta" if request.get("base_archetype_id") else "brew"
    return f"{request.get('archetype') or 'mazzo'} · {colors} · {start}"


def public_job(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "format_id": job.format_id,
        "label": job_label(job.kind, job.request_json),
        "model_id": job.request_json.get("model_id"),
        "status": job.status,
        "phase": job.phase,
        "error": job.error,
        "created_at": _stamp(job.created_at),
        "updated_at": _stamp(job.updated_at),
        "result": job.result_json if job.status == "completed" else None,
    }


def recover_interrupted_jobs(db):
    for job in db.query(AIJob).filter(AIJob.status.in_(["running", "queued"])):
        job.status, job.phase = "failed", "failed"
        job.error = "Il backend è stato riavviato durante l'analisi: avviala di nuovo."
        job.finished_at = utcnow()
    db.commit()


def create_job(db, kind, req):
    if kind not in KINDS:
        raise ValueError("Tipo di analisi non supportato.")
    skill = "deck_generation" if kind == "deck_generation" else "matchup_spot"
    req = req.model_copy(
        update={"model_id": get_skill_model_and_config(db, skill, req.model_id)["model_id"]}
    )
    payload = req.model_dump()
    with _lock:
        for job in db.query(AIJob).filter(AIJob.status.in_(["queued", "running"])):
            if job.kind == kind and job.request_json == payload:
                return public_job(job)  # a double click joins the running job
        if len(_workers) >= MAX_ACTIVE:
            raise ValueError(
                "Sono già in corso due analisi. Attendi il completamento o annullane una."
            )
        job = AIJob(kind=kind, format_id=req.format_id, request_json=payload)
        db.add(job)
        db.commit()
        result = public_job(job)
        _workers.add(job.id)
        _executor.submit(_work, job.id)
        return result


def cancel_job(db, job):
    if job.status in ("queued", "running"):
        db.query(AIJob).filter(
            AIJob.id == job.id, AIJob.status.in_(["queued", "running"])
        ).update(
            {"status": "cancelled", "phase": "cancelled", "finished_at": utcnow()},
            synchronize_session=False,
        )
        db.commit()
        db.refresh(job)
    return public_job(job)


def _user_error(exc):
    if isinstance(exc, ValidationError):
        return "Il provider ha restituito una risposta incompleta. Riprova."
    if isinstance(exc, ValueError):
        return str(exc)
    if _is_provider_failure(exc):
        return "Il provider non ha completato la risposta nel tempo disponibile. Riprova."
    return f"Errore interno ({type(exc).__name__}): dettagli nei log del backend."


def _work(job_id):
    from app.skills.deck_generation import run_deck_generation_skill
    from app.skills.runner import run_matchup_spot_skill

    runners = {
        "deck_generation": run_deck_generation_skill,
        "matchup_spot": run_matchup_spot_skill,
    }
    try:
        with SessionLocal() as db:
            job = db.get(AIJob, job_id)
            if job.status == "cancelled":
                return
            kind = job.kind
            req = KINDS[kind].model_validate(job.request_json)
            job.status = "running"
            db.commit()

        def progress(phase):
            with SessionLocal() as status_db:
                current = status_db.get(AIJob, job_id)
                if current.status == "cancelled":
                    raise ValueError(CANCELLED)
                current.phase = phase
                status_db.commit()

        with SessionLocal() as db:
            result = runners[kind](db, req, progress=progress)
        with SessionLocal() as db:
            job = db.get(AIJob, job_id)
            if job.status != "cancelled":
                job.status, job.phase = "completed", "completed"
                job.result_json = jsonable_encoder(result)
                job.finished_at = utcnow()
                db.commit()
    except Exception as exc:
        if not isinstance(exc, ValueError) or isinstance(exc, ValidationError):
            log.exception("ai job %s failed", job_id)
        with SessionLocal() as db:
            job = db.get(AIJob, job_id)
            if job.status != "cancelled":
                job.status, job.phase = "failed", "failed"
                job.error = _user_error(exc)
                job.finished_at = utcnow()
                db.commit()
    finally:
        with _lock:
            _workers.discard(job_id)
