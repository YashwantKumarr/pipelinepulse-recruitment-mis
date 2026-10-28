"""Assessment orchestration. Stores results for recruiter review. Never changes a pipeline stage."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Assessment, Candidate, JobRequisition
from app.services.ai_provider import AISummary, AssessmentProvider, ProviderError
from app.services.audit import record_audit
from app.services.fitment import ASSESSMENT_VERSION, FitmentResult, compute_fitment, fold
from app.timeutils import to_naive_utc


def deterministic_summary(fit: FitmentResult) -> str:
    total = len(fit.criteria)
    if total == 0:
        return "The job has no requirements, so no fitment comparison was made."
    if fit.fitment_percent is None:
        return f"No criteria could be scored; {len(fit.needs_review)} need recruiter review."
    return (
        f"Matched {len(fit.matched)} of {len(fit.matched) + len(fit.missing)} scorable criteria "
        f"({fit.fitment_percent}%). {len(fit.missing)} not evidenced in the resume text and "
        f"{len(fit.needs_review)} need recruiter review. Not evidenced does not prove absence of a skill."
    )


def _disagreements(fit: FitmentResult, ai: AISummary) -> list[dict]:
    ours = {fold(c.criterion): c.status for c in fit.criteria}
    found = []
    for item in ai.criteria:
        key = fold(item.criterion)
        if key in ours and ours[key] != item.verdict:
            found.append(
                {"criterion": item.criterion, "deterministic_status": ours[key], "ai_verdict": item.verdict}
            )
    return found


def run_assessment(
    session: Session,
    *,
    candidate: Candidate,
    job: JobRequisition,
    now: datetime,
    provider: AssessmentProvider | None = None,
) -> Assessment:
    requirements = list(job.requirements or [])
    resume_text = candidate.resume_text or ""
    fit = compute_fitment(requirements, resume_text)

    summary = deterministic_summary(fit)
    summary_source = "rules"
    provider_name = "rules"
    model = None
    ai_status = "disabled"
    disagreements: list[dict] = []

    if provider is not None:
        model = provider.model
        try:
            ai = provider.generate(requirements, resume_text)
        except ProviderError as exc:
            ai_status = f"fallback:{exc.code}"
        else:
            ai_status = "used"
            provider_name = provider.name
            summary = f"[AI-assisted] {ai.summary}"
            summary_source = "ai"
            disagreements = _disagreements(fit, ai)
        finally:
            provider.close()

    assessment = Assessment(
        candidate_id=candidate.id,
        job_id=job.id,
        assessment_version=ASSESSMENT_VERSION,
        provider=provider_name,
        model=model,
        ai_status=ai_status,
        summary_source=summary_source,
        summary=summary,
        fitment_percent=fit.fitment_percent,
        criteria=[
            {"criterion": c.criterion, "status": c.status, "evidence": c.evidence, "note": c.note}
            for c in fit.criteria
        ],
        ai_disagreements=disagreements,
        review_status="pending_review",
        created_at=to_naive_utc(now),
    )
    session.add(assessment)
    session.flush()
    record_audit(
        session,
        entity_type="assessment",
        entity_id=assessment.id,
        action="assessment.created",
        now=now,
        detail={
            "candidate_id": candidate.id,
            "job_id": job.id,
            "version": ASSESSMENT_VERSION,
            "ai_status": ai_status,
        },
    )
    return assessment
