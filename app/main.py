from fastapi import FastAPI,Depends,HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import Base,engine,SessionLocal
from .models import Center,Machine,DailyHistory

app=FastAPI(title="LINAC Machine Carrying Capacity API",version="0.2.0")
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
def db():
 s=SessionLocal()
 try: yield s
 finally: s.close()
class CenterIn(BaseModel): name:str; country:str="Thailand"
class MachineIn(BaseModel):
 center_id:int; name:str; model:str|None=None; operating_minutes:float|None=None; idle_minutes:float|None=None; imrt_proportion:float|None=Field(None,ge=0,le=1); imrt_cycle_minutes:float|None=None; d3_cycle_minutes:float|None=None; staff_efficacy:float|None=Field(None,ge=0,le=1); avg_course_fractions:float|None=None; working_days:int|None=None; linac_capacity_allowance:float|None=Field(None,ge=0,le=1)
@app.get("/health")
def health(): return {"status":"ok","database":"configured","ui":"v5-ready"}
@app.get("/api/centers")
def centers(s:Session=Depends(db)): return s.scalars(select(Center).order_by(Center.name)).all()
@app.post("/api/centers")
def create_center(x:CenterIn,s:Session=Depends(db)):
 c=Center(**x.model_dump()); s.add(c); s.commit(); s.refresh(c); return c
@app.get("/api/machines")
def machines(center_id:int,s:Session=Depends(db)): return s.scalars(select(Machine).where(Machine.center_id==center_id).order_by(Machine.name)).all()
@app.post("/api/machines")
def create_machine(x:MachineIn,s:Session=Depends(db)):
 if not s.get(Center,x.center_id): raise HTTPException(404,"Center not found")
 m=Machine(**x.model_dump()); s.add(m); s.commit(); s.refresh(m); return m
@app.get("/api/machines/{machine_id}/history")
def history(machine_id:int,s:Session=Depends(db)): return s.scalars(select(DailyHistory).where(DailyHistory.machine_id==machine_id).order_by(DailyHistory.date)).all()

# Frontend is mounted last so /api/* and /health remain available.
app.mount("/",StaticFiles(directory=".",html=True),name="frontend")
