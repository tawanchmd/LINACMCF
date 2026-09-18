from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from .db import Base, engine, SessionLocal
from .models import Center, Machine, DailyHistory

app = FastAPI(title="LINAC Machine Carrying Capacity API", version="0.3.0")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)

def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

class CenterIn(BaseModel):
    name: str
    country: str = "Thailand"

class HistoryRowIn(BaseModel):
    date: date
    new_patients: int = Field(ge=0)
    active_patients: int = Field(ge=0)

class MachineIn(BaseModel):
    center_id: int
    name: str
    model: str | None = None
    operating_minutes: float | None = None
    idle_minutes: float | None = None
    imrt_proportion: float | None = Field(None, ge=0, le=1)
    imrt_cycle_minutes: float | None = None
    d3_cycle_minutes: float | None = None
    staff_efficacy: float | None = Field(None, ge=0, le=1)
    avg_course_fractions: float | None = None
    working_days: int | None = None
    linac_capacity_allowance: float | None = Field(None, ge=0, le=1)

@app.get("/health")
def health(s: Session = Depends(db)):
    s.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected", "ui": "v5-ready"}

@app.get("/api/centers")
def centers(s: Session = Depends(db)):
    return s.scalars(select(Center).order_by(Center.name)).all()

@app.post("/api/centers")
def create_center(x: CenterIn, s: Session = Depends(db)):
    c = Center(**x.model_dump())
    s.add(c); s.commit(); s.refresh(c)
    return c

@app.get("/api/machines")
def machines(center_id: int, s: Session = Depends(db)):
    return s.scalars(select(Machine).where(Machine.center_id == center_id).order_by(Machine.name)).all()

@app.post("/api/machines")
def create_machine(x: MachineIn, s: Session = Depends(db)):
    if not s.get(Center, x.center_id):
        raise HTTPException(404, "Center not found")
    m = Machine(**x.model_dump())
    s.add(m); s.commit(); s.refresh(m)
    return m

@app.get("/api/machines/{machine_id}/history")
def history(machine_id: int, s: Session = Depends(db)):
    return s.scalars(select(DailyHistory).where(DailyHistory.machine_id == machine_id).order_by(DailyHistory.date)).all()

@app.put("/api/machines/{machine_id}/history")
def save_history(machine_id: int, rows: list[HistoryRowIn], s: Session = Depends(db)):
    if not s.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    for x in rows:
        h = s.scalar(select(DailyHistory).where(DailyHistory.machine_id == machine_id, DailyHistory.date == x.date))
        if h:
            h.new_patients = x.new_patients
            h.active_patients = x.active_patients
        else:
            s.add(DailyHistory(machine_id=machine_id, **x.model_dump()))
    s.commit()
    return {"saved": len(rows)}

# Mounted last so API and health routes take precedence.
app.mount("/", StaticFiles(directory=".", html=True), name="frontend")
