"""Cost/chargeback, uptime/SLA, and monitoring-alert endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit, insights
from orchestrator.db import get_db
from orchestrator.models import Alert, utcnow
from orchestrator.schemas import AlertOut
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/cost/summary")
def cost(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    return insights.cost_summary(db)


@router.get("/sla/summary")
def sla(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db),
        _: str = Depends(require_panel_token)):
    return insights.sla_summary(db, days)


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    open_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    q = select(Alert).order_by(Alert.created_at.desc()).limit(500)
    if open_only:
        q = q.where(Alert.acknowledged_at.is_(None))
    return db.execute(q).scalars().all()


@router.post("/alerts/evaluate")
def evaluate(db: Session = Depends(get_db), actor: str = Depends(require_operator)):
    new = insights.evaluate_alerts(db)
    return {"new_alerts": len(new)}


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def ack(alert_id: str, db: Session = Depends(get_db), actor: str = Depends(require_operator)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    if not alert.acknowledged_at:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = actor
        audit.record(db, actor, "alert.acknowledged", alert.tenant_id, kind=alert.kind)
        db.commit()
    return alert
