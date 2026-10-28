from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.deps import NowDep, SessionDep, SettingsDep
from app.services.analytics import funnel_summary
from app.services.csv_export import build_csv

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/funnel")
def get_funnel(session: SessionDep, settings: SettingsDep, now: NowDep) -> dict:
    return funnel_summary(session, now=now, sla_hours=settings.feedback_sla_hours)


@router.get("/export.csv")
def export_csv(
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    dataset: Literal["candidates", "pipeline", "interviews", "funnel"] = Query("candidates"),
) -> Response:
    body = build_csv(session, dataset, now=now, sla_hours=settings.feedback_sla_hours)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="talentflow-{dataset}.csv"'},
    )
