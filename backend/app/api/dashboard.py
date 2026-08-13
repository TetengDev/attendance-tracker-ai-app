from datetime import datetime, UTC
from fastapi import APIRouter
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import SessionDep, StrictSchema, AdminUserDep, require_org_admin
from backend.app.models.people import Person
from backend.app.models.devices import Device
from backend.app.models.attendance import AttendanceEvent

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

class ActivityItem(StrictSchema):
    id: int
    person_name: str | None
    direction: str
    outcome: str
    time: datetime

class DashboardMetrics(StrictSchema):
    active_people: int
    scans_today: int
    active_kiosks: int
    recent_activity: list[ActivityItem]

@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    session: SessionDep,
    admin_user: AdminUserDep,
) -> DashboardMetrics:
    require_org_admin(admin_user)

    # 1. Active People
    active_people_query = select(func.count(Person.id)).where(Person.is_active == True)
    active_people_res = await session.execute(active_people_query)
    active_people = active_people_res.scalar_one_or_none() or 0

    # 2. Active Kiosks (all registered devices)
    active_kiosks_query = select(func.count(Device.id))
    active_kiosks_res = await session.execute(active_kiosks_query)
    active_kiosks = active_kiosks_res.scalar_one_or_none() or 0

    # 3. Scans Today
    now = datetime.now(UTC)
    today = now.date()
    scans_today_query = select(func.count(AttendanceEvent.id)).where(AttendanceEvent.business_date == today)
    scans_today_res = await session.execute(scans_today_query)
    scans_today = scans_today_res.scalar_one_or_none() or 0

    # 4. Recent Activity
    recent_query = (
        select(AttendanceEvent, Person.display_name)
        .outerjoin(Person, AttendanceEvent.person_id == Person.id)
        .order_by(desc(AttendanceEvent.occurred_at))
        .limit(10)
    )
    recent_res = await session.execute(recent_query)
    
    recent_activity = []
    for event, person_name in recent_res.all():
        recent_activity.append(ActivityItem(
            id=event.id,
            person_name=person_name or "Unknown",
            direction=event.direction,
            outcome=event.outcome,
            time=event.occurred_at
        ))

    return DashboardMetrics(
        active_people=active_people,
        scans_today=scans_today,
        active_kiosks=active_kiosks,
        recent_activity=recent_activity
    )
