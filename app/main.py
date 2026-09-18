from datetime import date
import json, math, os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from starlette.middleware.sessions import SessionMiddleware
from pwdlib import PasswordHash
from .db import Base, engine, SessionLocal
from .models import Center, Machine, DailyHistory, AppState, User, CenterMembership, AuditLog

app = FastAPI(title="LINAC Machine Carrying Capacity API", version="0.5.1")
app.add_middleware(SessionMiddleware,secret_key=os.environ.get("SESSION_SECRET","dev-only-change-me"),https_only=os.environ.get("APP_ENV")=="production",same_site="lax",max_age=28800)
password_hash=PasswordHash.recommended()

def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL","").strip().lower()
    pw=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD","")
    if email and pw:
        s=SessionLocal()
        try:
            u=s.scalar(select(User).where(User.email==email))
            if not u:
                s.add(User(email=email,password_hash=password_hash.hash(pw),is_system_admin=True))
                s.commit()
        finally: s.close()

class LoginIn(BaseModel): email:str; password:str
class CenterIn(BaseModel): name:str; country:str="Thailand"
class HistoryRowIn(BaseModel): date:date; new_patients:int=Field(ge=0); active_patients:int=Field(ge=0)
class MachineIn(BaseModel):
    center_id:int; name:str; model:str|None=None; operating_minutes:float|None=None; idle_minutes:float|None=None
    imrt_proportion:float|None=Field(None,ge=0,le=1); imrt_cycle_minutes:float|None=None; d3_cycle_minutes:float|None=None
    staff_efficacy:float|None=Field(None,ge=0,le=1); avg_course_fractions:float|None=None; working_days:int|None=None
    linac_capacity_allowance:float|None=Field(None,ge=0,le=1)
class StateIn(BaseModel): payload:dict
class ForecastIn(BaseModel): series:list[float]; horizon:int=Field(20,ge=1,le=260); seasonality:str="auto"

def current_user(request:Request,s:Session=Depends(db)):
    uid=request.session.get("uid")
    if not uid: raise HTTPException(401,"Authentication required")
    u=s.get(User,uid)
    if not u or not u.is_active:
        request.session.clear(); raise HTTPException(401,"Authentication required")
    return u

def memberships(s,u):
    return s.scalars(select(CenterMembership).where(CenterMembership.user_id==u.id)).all()

def can_center(s,u,center_id,write=False):
    if u.is_system_admin: return True
    m=s.scalar(select(CenterMembership).where(CenterMembership.user_id==u.id,CenterMembership.center_id==center_id))
    if not m: return False
    return (m.role in ("center_admin","data_entry")) if write else True

def audit(s,u,action,center_id=None,detail=None):
    s.add(AuditLog(user_id=u.id if u else None,center_id=center_id,action=action,detail=detail))

@app.get("/health")
def health(s:Session=Depends(db)):
    s.execute(text("SELECT 1")); return {"status":"ok","database":"connected","ui":"v5.1","auth":"rbac","isolation":"per-user/per-center"}

@app.post("/api/auth/login")
def login(x:LoginIn,request:Request,s:Session=Depends(db)):
    u=s.scalar(select(User).where(User.email==x.email.strip().lower()))
    if not u or not u.is_active or not password_hash.verify(x.password,u.password_hash):
        raise HTTPException(401,"Invalid email or password")
    request.session.clear(); request.session["uid"]=u.id
    audit(s,u,"login"); s.commit()
    return {"ok":True,"user":{"id":u.id,"email":u.email,"system_admin":u.is_system_admin}}

@app.post("/api/auth/logout")
def logout(request:Request,u:User=Depends(current_user),s:Session=Depends(db)):
    audit(s,u,"logout"); s.commit(); request.session.clear(); return {"ok":True}

@app.get("/api/auth/me")
def me(u:User=Depends(current_user),s:Session=Depends(db)):
    ms=memberships(s,u)
    return {"id":u.id,"email":u.email,"system_admin":u.is_system_admin,"memberships":[{"center_id":m.center_id,"role":m.role} for m in ms]}

@app.get("/api/centers")
def centers(u:User=Depends(current_user),s:Session=Depends(db)):
    if u.is_system_admin: return s.scalars(select(Center).order_by(Center.name)).all()
    ids=[m.center_id for m in memberships(s,u)]
    return s.scalars(select(Center).where(Center.id.in_(ids)).order_by(Center.name)).all() if ids else []

@app.post("/api/centers")
def create_center(x:CenterIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    c=Center(**x.model_dump()); s.add(c); s.flush()
    s.add(CenterMembership(user_id=u.id,center_id=c.id,role="center_admin"))
    audit(s,u,"center.create",c.id,x.name); s.commit(); s.refresh(c); return c

@app.get("/api/machines")
def machines(center_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    if not can_center(s,u,center_id): raise HTTPException(403,"Center access denied")
    return s.scalars(select(Machine).where(Machine.center_id==center_id).order_by(Machine.name)).all()

@app.post("/api/machines")
def create_machine(x:MachineIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not s.get(Center,x.center_id): raise HTTPException(404,"Center not found")
    if not can_center(s,u,x.center_id,True): raise HTTPException(403,"Write access denied")
    m=Machine(**x.model_dump()); s.add(m); audit(s,u,"machine.create",x.center_id,x.name); s.commit(); s.refresh(m); return m

def machine_for_user(s,u,machine_id,write=False):
    m=s.get(Machine,machine_id)
    if not m: raise HTTPException(404,"Machine not found")
    if not can_center(s,u,m.center_id,write): raise HTTPException(403,"Center access denied")
    return m

@app.get("/api/machines/{machine_id}/history")
def history(machine_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    machine_for_user(s,u,machine_id)
    return s.scalars(select(DailyHistory).where(DailyHistory.machine_id==machine_id).order_by(DailyHistory.date)).all()

@app.put("/api/machines/{machine_id}/history")
def save_history(machine_id:int,rows:list[HistoryRowIn],u:User=Depends(current_user),s:Session=Depends(db)):
    m=machine_for_user(s,u,machine_id,True)
    for x in rows:
        h=s.scalar(select(DailyHistory).where(DailyHistory.machine_id==machine_id,DailyHistory.date==x.date))
        if h: h.new_patients=x.new_patients; h.active_patients=x.active_patients
        else: s.add(DailyHistory(machine_id=machine_id,**x.model_dump()))
    audit(s,u,"history.upsert",m.center_id,f"machine={machine_id}; rows={len(rows)}"); s.commit(); return {"saved":len(rows)}

@app.get("/api/state")
def get_state(u:User=Depends(current_user),s:Session=Depends(db)):
    key=f"browser-v5:user:{u.id}"
    r=s.scalar(select(AppState).where(AppState.state_key==key))
    return {"payload":json.loads(r.payload) if r else None,"updated_at":r.updated_at if r else None}

@app.put("/api/state")
def put_state(x:StateIn,u:User=Depends(current_user),s:Session=Depends(db)):
    raw=json.dumps(x.payload,separators=(",",":"),ensure_ascii=False)
    if len(raw)>5_000_000: raise HTTPException(413,"State payload too large")
    key=f"browser-v5:user:{u.id}"
    r=s.scalar(select(AppState).where(AppState.state_key==key))
    if r: r.payload=raw
    else: s.add(AppState(state_key=key,payload=raw))
    audit(s,u,"state.save",detail=f"bytes={len(raw)}"); s.commit(); return {"saved":True,"bytes":len(raw)}

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
def forecast_api(x:ForecastIn,u:User=Depends(current_user)):
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
            errs.append(abs(y[i]-pred(train,1,kind,5)[0]))
        scores.append({"model":kind,"mae":sum(errs)/len(errs) if errs else 1e99})
    scores.sort(key=lambda z:z["mae"]); winner=scores[0]; runner=scores[1]["mae"] if len(scores)>1 else winner["mae"]
    confidence=0 if runner<=0 else max(0,min(1,(runner-winner["mae"])/runner))
    fc=pred(y,x.horizon,winner["model"],5); residual=winner["mae"]*1.25
    return {"winner":winner["model"],"validation":scores,"confidence":confidence,"forecast":fc,
            "lower":[max(0,v-residual*math.sqrt(i+1)) for i,v in enumerate(fc)],
            "upper":[v+residual*math.sqrt(i+1) for i,v in enumerate(fc)],
            "method":"rolling-origin MAE; approximate residual band"}

app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/")
def root(): return FileResponse("index.html")
