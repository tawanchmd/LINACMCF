from datetime import date
import json, math
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from .db import Base, engine, SessionLocal
from .models import Center, Machine, DailyHistory, AppState

app = FastAPI(title="LINAC Machine Carrying Capacity API", version="0.5.0")
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

class CenterIn(BaseModel):
    name:str; country:str="Thailand"
class HistoryRowIn(BaseModel):
    date:date; new_patients:int=Field(ge=0); active_patients:int=Field(ge=0)
class MachineIn(BaseModel):
    center_id:int; name:str; model:str|None=None; operating_minutes:float|None=None; idle_minutes:float|None=None
    imrt_proportion:float|None=Field(None,ge=0,le=1); imrt_cycle_minutes:float|None=None; d3_cycle_minutes:float|None=None
    staff_efficacy:float|None=Field(None,ge=0,le=1); avg_course_fractions:float|None=None; working_days:int|None=None
    linac_capacity_allowance:float|None=Field(None,ge=0,le=1)
class StateIn(BaseModel):
    payload:dict
class ForecastIn(BaseModel):
    series:list[float]; horizon:int=Field(20,ge=1,le=260); seasonality:str="auto"

@app.get("/health")
def health(s:Session=Depends(db)):
    s.execute(text("SELECT 1")); return {"status":"ok","database":"connected","ui":"v5.0","persistence":"server","forecast":"api"}
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
@app.put("/api/machines/{machine_id}/history")
def save_history(machine_id:int,rows:list[HistoryRowIn],s:Session=Depends(db)):
    if not s.get(Machine,machine_id): raise HTTPException(404,"Machine not found")
    for x in rows:
        h=s.scalar(select(DailyHistory).where(DailyHistory.machine_id==machine_id,DailyHistory.date==x.date))
        if h: h.new_patients=x.new_patients; h.active_patients=x.active_patients
        else: s.add(DailyHistory(machine_id=machine_id,**x.model_dump()))
    s.commit(); return {"saved":len(rows)}

@app.get("/api/state")
def get_state(s:Session=Depends(db)):
    r=s.scalar(select(AppState).where(AppState.state_key=="browser-v5"))
    return {"payload":json.loads(r.payload) if r else None,"updated_at":r.updated_at if r else None}
@app.put("/api/state")
def put_state(x:StateIn,s:Session=Depends(db)):
    raw=json.dumps(x.payload,separators=(",",":"),ensure_ascii=False)
    r=s.scalar(select(AppState).where(AppState.state_key=="browser-v5"))
    if r: r.payload=raw
    else: s.add(AppState(state_key="browser-v5",payload=raw))
    s.commit(); return {"saved":True,"bytes":len(raw)}

def pred(y,h,kind,season=5):
    n=len(y)
    if kind=="naive": return [y[-1]]*h
    if kind=="ma":
        k=min(3,n); v=sum(y[-k:])/k; return [v]*h
    if kind=="seasonal":
        season=max(1,min(season,n)); return [y[n-season+(j%season)] for j in range(h)]
    if kind=="holt":
        a,b=.35,.15; level=y[0]; trend=(y[1]-y[0]) if n>1 else 0
        for v in y[1:]:
            prev=level; level=a*v+(1-a)*(level+trend); trend=b*(level-prev)+(1-b)*trend
        return [max(0,level+(j+1)*trend) for j in range(h)]
    xs=list(range(n)); xm=sum(xs)/n; ym=sum(y)/n; den=sum((x-xm)**2 for x in xs) or 1
    slope=sum((x-xm)*(v-ym) for x,v in zip(xs,y))/den; intercept=ym-slope*xm
    return [max(0,intercept+slope*(n+j)) for j in range(h)]
@app.post("/api/forecast")
def forecast_api(x:ForecastIn):
    y=[float(v) for v in x.series if math.isfinite(float(v))]
    if len(y)<6: raise HTTPException(422,"At least 6 working-day observations are required")
    candidates=["naive","ma","trend","holt"]
    if x.seasonality in ("auto","weekly"): candidates.append("seasonal")
    origins=max(1,min(6,len(y)-5)); start=len(y)-origins; scores=[]
    for kind in candidates:
        errs=[]
        for i in range(start,len(y)):
            train=y[:i]
            if len(train)<3: continue
            p=pred(train,1,kind,5)[0]; errs.append(abs(y[i]-p))
        mae=sum(errs)/len(errs) if errs else 1e99
        scores.append({"model":kind,"mae":mae})
    scores.sort(key=lambda z:z["mae"]); winner=scores[0]
    runner=scores[1]["mae"] if len(scores)>1 else winner["mae"]
    confidence=0 if runner<=0 else max(0,min(1,(runner-winner["mae"])/runner))
    fc=pred(y,x.horizon,winner["model"],5)
    residual=winner["mae"]*1.25
    lo=[max(0,v-residual*math.sqrt(i+1)) for i,v in enumerate(fc)]
    hi=[v+residual*math.sqrt(i+1) for i,v in enumerate(fc)]
    return {"winner":winner["model"],"validation":scores,"confidence":confidence,"forecast":fc,"lower":lo,"upper":hi,"method":"rolling-origin MAE; approximate residual band"}

app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/")
def root(): return FileResponse("index.html")
