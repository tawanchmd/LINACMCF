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
from .models import Center, Machine, DailyHistory, AppState, User, CenterMembership, AuditLog, UserProfile, AccessRequest

app = FastAPI(title="LINAC Machine Carrying Capacity API", version="0.5.1")
app.add_middleware(SessionMiddleware,secret_key=os.environ.get("SESSION_SECRET") or __import__("hashlib").sha256((os.environ.get("DATABASE_URL","linacmcf-local")+"|session").encode()).hexdigest(),https_only=os.environ.get("APP_ENV")=="production",same_site="lax",max_age=28800)
password_hash=PasswordHash.recommended()

def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)

class LoginIn(BaseModel): email:str; password:str
class SignupIn(BaseModel): full_name:str=Field(min_length=2,max_length=180); email:str; password:str=Field(min_length=12,max_length=128)
class AccessRequestIn(BaseModel): request_type:str; center_id:int|None=None; center_name:str|None=Field(None,max_length=180); country:str="Thailand"
class SetupIn(BaseModel): email:str; password:str=Field(min_length=12,max_length=128)
class UserCreateIn(BaseModel): email:str; password:str=Field(min_length=12,max_length=128)
class MembershipIn(BaseModel): user_id:int; center_id:int; role:str
class PasswordChangeIn(BaseModel): current_password:str; new_password:str=Field(min_length=12,max_length=128)
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

def center_role(s,u,center_id):
    if u.is_system_admin: return "system_admin"
    m=s.scalar(select(CenterMembership).where(CenterMembership.user_id==u.id,CenterMembership.center_id==center_id))
    return m.role if m else None

def can_center(s,u,center_id,action="read"):
    role=center_role(s,u,center_id)
    if role=="system_admin": return True
    if action=="read": return role in ("center_admin","data_entry","viewer")
    if action=="history_write": return role in ("center_admin","data_entry")
    if action=="admin_write": return role=="center_admin"
    return False

def audit(s,u,action,center_id=None,detail=None):
    s.add(AuditLog(user_id=u.id if u else None,center_id=center_id,action=action,detail=detail))

@app.get("/health")
def health(s:Session=Depends(db)):
    s.execute(text("SELECT 1")); return {"status":"ok","database":"connected","ui":"v5.1","auth":"rbac","isolation":"per-user/per-center"}

@app.get("/api/auth/setup-status")
def setup_status(s:Session=Depends(db)):
    return {"setup_required":s.scalar(select(User.id).limit(1)) is None}

@app.post("/api/auth/setup")
def setup_admin(x:SetupIn,request:Request,s:Session=Depends(db)):
    if s.scalar(select(User.id).limit(1)) is not None: raise HTTPException(409,"Setup already completed")
    email=x.email.strip().lower()
    if "@" not in email: raise HTTPException(422,"Valid email required")
    u=User(email=email,password_hash=password_hash.hash(x.password),is_system_admin=True)
    s.add(u); s.flush(); audit(s,u,"system.bootstrap"); s.commit(); request.session["uid"]=u.id
    return {"ok":True,"user":{"id":u.id,"email":u.email,"system_admin":True}}

@app.post("/api/auth/signup")
def signup(x:SignupIn,request:Request,s:Session=Depends(db)):
    email=x.email.strip().lower(); full_name=x.full_name.strip()
    if "@" not in email: raise HTTPException(422,"Valid email required")
    if len(full_name)<2: raise HTTPException(422,"Full name required")
    if s.scalar(select(User).where(User.email==email)): raise HTTPException(409,"Email already exists")
    u=User(email=email,password_hash=password_hash.hash(x.password),is_system_admin=False,is_active=True)
    s.add(u); s.flush(); s.add(UserProfile(user_id=u.id,full_name=full_name))
    audit(s,u,"user.signup",detail=f"full_name={full_name}"); s.commit()
    request.session.clear(); request.session["uid"]=u.id
    return {"ok":True,"user":{"id":u.id,"email":u.email,"system_admin":False,"onboarding_required":True}}

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
    p=s.scalar(select(UserProfile).where(UserProfile.user_id==u.id))
    req=s.scalar(select(AccessRequest).where(AccessRequest.user_id==u.id,AccessRequest.status=="pending").order_by(AccessRequest.created_at.desc()))
    return {"id":u.id,"email":u.email,"full_name":p.full_name if p else None,"system_admin":u.is_system_admin,
            "memberships":[{"center_id":m.center_id,"center_name":(s.get(Center,m.center_id).name if s.get(Center,m.center_id) else None),"role":m.role} for m in ms],
            "onboarding_required":(not u.is_system_admin and len(ms)==0),
            "access_request":{"id":req.id,"type":req.request_type,"status":req.status,"center_id":req.center_id,"center_name":req.requested_center_name} if req else None}

@app.post("/api/auth/change-password")
def change_password(x:PasswordChangeIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not password_hash.verify(x.current_password,u.password_hash): raise HTTPException(401,"Current password is incorrect")
    u.password_hash=password_hash.hash(x.new_password); audit(s,u,"password.change"); s.commit()
    return {"ok":True}

@app.get("/api/admin/users")
def admin_users(u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    return [{"id":x.id,"email":x.email,"is_active":x.is_active,"is_system_admin":x.is_system_admin} for x in s.scalars(select(User).order_by(User.email)).all()]

@app.post("/api/admin/users")
def admin_create_user(x:UserCreateIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    email=x.email.strip().lower()
    if "@" not in email: raise HTTPException(422,"Valid email required")
    if s.scalar(select(User).where(User.email==email)): raise HTTPException(409,"Email already exists")
    nu=User(email=email,password_hash=password_hash.hash(x.password))
    s.add(nu); s.flush(); audit(s,u,"user.create",detail=f"user_id={nu.id}"); s.commit()
    return {"id":nu.id,"email":nu.email}

@app.post("/api/admin/memberships")
def admin_membership(x:MembershipIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    if x.role not in ("center_admin","data_entry","viewer"): raise HTTPException(422,"Invalid role")
    if not s.get(User,x.user_id) or not s.get(Center,x.center_id): raise HTTPException(404,"User or center not found")
    m=s.scalar(select(CenterMembership).where(CenterMembership.user_id==x.user_id,CenterMembership.center_id==x.center_id))
    if m: m.role=x.role
    else: s.add(CenterMembership(user_id=x.user_id,center_id=x.center_id,role=x.role))
    audit(s,u,"membership.upsert",x.center_id,f"user_id={x.user_id}; role={x.role}"); s.commit()
    return {"ok":True}

@app.get("/api/centers/{center_id}/members")
def center_members(center_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    if not can_center(s,u,center_id,"admin_write"): raise HTTPException(403,"Center Admin access required")
    rows=s.scalars(select(CenterMembership).where(CenterMembership.center_id==center_id)).all()
    out=[]
    for m in rows:
        mu=s.get(User,m.user_id)
        if not mu: continue
        p=s.scalar(select(UserProfile).where(UserProfile.user_id==mu.id))
        out.append({"user_id":mu.id,"email":mu.email,"full_name":p.full_name if p else None,"role":m.role,"is_active":mu.is_active})
    return sorted(out,key=lambda x:((x["full_name"] or x["email"]).lower(),x["email"]))

@app.put("/api/centers/{center_id}/members/{user_id}/role")
def center_member_role(center_id:int,user_id:int,x:MembershipIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if not can_center(s,u,center_id,"admin_write"): raise HTTPException(403,"Center Admin access required")
    if x.center_id!=center_id or x.user_id!=user_id: raise HTTPException(422,"Membership target mismatch")
    if x.role not in ("center_admin","data_entry","viewer"): raise HTTPException(422,"Invalid role")
    m=s.scalar(select(CenterMembership).where(CenterMembership.user_id==user_id,CenterMembership.center_id==center_id))
    if not m: raise HTTPException(404,"Center membership not found")
    if m.role=="center_admin" and x.role!="center_admin":
        admins=s.scalars(select(CenterMembership).where(CenterMembership.center_id==center_id,CenterMembership.role=="center_admin")).all()
        if len(admins)<=1: raise HTTPException(409,"A center must keep at least one Center Admin")
    m.role=x.role
    audit(s,u,"membership.role_change",center_id,f"user_id={user_id}; role={x.role}"); s.commit()
    return {"ok":True,"user_id":user_id,"center_id":center_id,"role":x.role}

@app.get("/api/onboarding/centers")
def onboarding_centers(u:User=Depends(current_user),s:Session=Depends(db)):
    return [{"id":c.id,"name":c.name,"country":c.country} for c in s.scalars(select(Center).order_by(Center.name)).all()]

@app.post("/api/onboarding/request")
def onboarding_request(x:AccessRequestIn,u:User=Depends(current_user),s:Session=Depends(db)):
    if u.is_system_admin or memberships(s,u): raise HTTPException(409,"Account already has center access")
    if s.scalar(select(AccessRequest).where(AccessRequest.user_id==u.id,AccessRequest.status=="pending")):
        raise HTTPException(409,"A request is already pending")
    if x.request_type not in ("new_center","join_center"): raise HTTPException(422,"Invalid request type")
    center_id=None; center_name=None
    if x.request_type=="join_center":
        if not x.center_id or not s.get(Center,x.center_id): raise HTTPException(404,"Center not found")
        center_id=x.center_id
    else:
        center_name=(x.center_name or "").strip()
        if len(center_name)<2: raise HTTPException(422,"Center name required")
    r=AccessRequest(user_id=u.id,request_type=x.request_type,center_id=center_id,requested_center_name=center_name,requested_country=x.country,status="pending")
    s.add(r); s.flush(); audit(s,u,"access.request",center_id,f"type={x.request_type}; request_id={r.id}; center_name={center_name or ''}"); s.commit()
    return {"ok":True,"request_id":r.id,"status":"pending"}

@app.get("/api/admin/access-requests")
def admin_access_requests(u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    rows=s.scalars(select(AccessRequest).where(AccessRequest.status=="pending").order_by(AccessRequest.created_at)).all()
    out=[]
    for r in rows:
        ru=s.get(User,r.user_id); p=s.scalar(select(UserProfile).where(UserProfile.user_id==r.user_id))
        out.append({"id":r.id,"user_id":r.user_id,"full_name":p.full_name if p else None,"email":ru.email if ru else None,
                    "type":r.request_type,"center_id":r.center_id,"center_name":r.requested_center_name,"country":r.requested_country,"status":r.status})
    return out

@app.post("/api/admin/access-requests/{request_id}/approve")
def admin_approve_access(request_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    r=s.get(AccessRequest,request_id)
    if not r or r.status!="pending": raise HTTPException(404,"Pending request not found")
    if r.request_type=="new_center":
        name=(r.requested_center_name or "").strip()
        if s.scalar(select(Center).where(Center.name==name)): raise HTTPException(409,"Center name already exists")
        center=Center(name=name,country=r.requested_country or "Thailand"); s.add(center); s.flush(); center_id=center.id
    else:
        center_id=r.center_id
        if not center_id or not s.get(Center,center_id): raise HTTPException(404,"Center not found")
    s.add(CenterMembership(user_id=r.user_id,center_id=center_id,role="center_admin" if r.request_type=="new_center" else "viewer"))
    r.status="approved"; audit(s,u,"access.approve",center_id,f"request_id={r.id}; user_id={r.user_id}"); s.commit()
    return {"ok":True,"center_id":center_id,"role":"center_admin" if r.request_type=="new_center" else "viewer"}

@app.post("/api/admin/access-requests/{request_id}/reject")
def admin_reject_access(request_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    r=s.get(AccessRequest,request_id)
    if not r or r.status!="pending": raise HTTPException(404,"Pending request not found")
    r.status="rejected"; audit(s,u,"access.reject",r.center_id,f"request_id={r.id}; user_id={r.user_id}"); s.commit()
    return {"ok":True,"status":"rejected"}

@app.get("/health/security")
def security_health(s:Session=Depends(db)):
    setup_locked=s.scalar(select(User.id).limit(1)) is not None
    return {"status":"ok","setup_locked":setup_locked,"unauthenticated_api":"enforced","roles":["center_admin","data_entry","viewer"],"cross_center_guard":"server-side membership check","state_scope":"per-user"}

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
    if not can_center(s,u,x.center_id,"admin_write"): raise HTTPException(403,"Center Admin access required")
    m=Machine(**x.model_dump()); s.add(m); audit(s,u,"machine.create",x.center_id,x.name); s.commit(); s.refresh(m); return m

def machine_for_user(s,u,machine_id,action="read"):
    m=s.get(Machine,machine_id)
    if not m: raise HTTPException(404,"Machine not found")
    if not can_center(s,u,m.center_id,action): raise HTTPException(403,"Center access denied")
    return m

@app.get("/api/machines/{machine_id}/history")
def history(machine_id:int,u:User=Depends(current_user),s:Session=Depends(db)):
    machine_for_user(s,u,machine_id)
    return s.scalars(select(DailyHistory).where(DailyHistory.machine_id==machine_id).order_by(DailyHistory.date)).all()

@app.put("/api/machines/{machine_id}/history")
def save_history(machine_id:int,rows:list[HistoryRowIn],u:User=Depends(current_user),s:Session=Depends(db)):
    m=machine_for_user(s,u,machine_id,"history_write")
    for x in rows:
        h=s.scalar(select(DailyHistory).where(DailyHistory.machine_id==machine_id,DailyHistory.date==x.date))
        if h: h.new_patients=x.new_patients; h.active_patients=x.active_patients
        else: s.add(DailyHistory(machine_id=machine_id,**x.model_dump()))
    audit(s,u,"history.upsert",m.center_id,f"machine={machine_id}; rows={len(rows)}"); s.commit(); return {"saved":len(rows)}


def _state_obj(r):
    try: return json.loads(r.payload or "{}")
    except Exception: return {}

def _json_obj(v):
    if isinstance(v,dict): return v
    if not v: return {}
    try: return json.loads(v)
    except Exception: return {}

def _national_rollup_rows(s:Session):
    """Shared read model assembled from each authenticated user's persisted center workspace.
    Center records are de-duplicated by serverCenterId when available, otherwise normalized name.
    Raw daily histories are used only to derive aggregate utilization; they are never returned here.
    """
    merged={}
    states=s.scalars(select(AppState).where(AppState.state_key.like("browser-v5:user:%"))).all()
    for st in states:
        payload=_state_obj(st)
        cs=_json_obj(payload.get("centers")); ms=_json_obj(payload.get("machines"))
        histories=payload.get("histories") or {}
        for ck,center in cs.items():
            if not isinstance(center,dict): continue
            sid=center.get("serverCenterId")
            key=("id:"+str(sid)) if sid else ("name:"+str(center.get("center") or ck).strip().lower())
            row=merged.setdefault(key,{"center_id":sid,"center_name":center.get("center") or ck,
                "population":center.get("population") or {},"service_area":center.get("serviceArea") or {},
                "machines":{},"history_totals":[],"updated_at":str(st.updated_at or "")})
            # Prefer center metadata from the newest persisted workspace only.
            # Multiple users can carry snapshots of the same center; an older snapshot
            # must never overwrite a newer service area/allocation.
            incoming_updated=str(st.updated_at or "")
            if incoming_updated>=row.get("updated_at",""):
                if center.get("population"): row["population"]=center.get("population")
                if center.get("serviceArea"): row["service_area"]=center.get("serviceArea")
                row["updated_at"]=incoming_updated
            for mk,m in ms.items():
                if not isinstance(m,dict): continue
                mck=str(m.get("centerKey") or "").strip().lower()
                if mck!=str(ck).strip().lower() and str(m.get("center") or "").strip().lower()!=str(center.get("center") or "").strip().lower(): continue
                mname=str(m.get("machine") or mk)
                row["machines"][mname]={"name":mname,"machineInputs":m.get("machineInputs") or {},"computed":m.get("computed") or {}}
                hv=histories.get("histDaily|"+mk)
                h=_json_obj(hv)
                for _,v in h.items():
                    if isinstance(v,dict):
                        try: row["history_totals"].append(float(v.get("newPatients") or 0)+float(v.get("activePatients") or 0))
                        except Exception: pass
    out=[]
    for row in merged.values():
        machines=list(row["machines"].values())
        cap=sum(float((m.get("computed") or {}).get("annualCases") or 0) for m in machines)
        daily=sum(float((m.get("computed") or {}).get("daily") or (m.get("computed") or {}).get("dailyCap") or 0) for m in machines)
        hist=row.pop("history_totals",[])
        recent=hist[-20:] if hist else []
        current=(sum(recent)/len(recent)/daily*100) if recent and daily>0 else None
        row["machines"]=machines; row["machine_count"]=len(machines); row["modeled_capacity"]=cap
        row["current_utilization_pct"]=current
        if current is None: row["capacity_interpretation"]="Insufficient recent workload data"
        elif current>=90: row["capacity_interpretation"]="High utilization — limited modeled operating buffer"
        elif current>=70: row["capacity_interpretation"]="Moderate-to-high utilization"
        else: row["capacity_interpretation"]="Utilization below modeled daily capacity"
        out.append(row)
    return sorted(out,key=lambda x:x["center_name"].lower())

@app.get("/api/national/rollup")
def national_rollup(u:User=Depends(current_user),s:Session=Depends(db)):
    # National aggregate is intentionally visible to authenticated center users.
    # It contains center/service-area/capacity summaries, not raw patient-level history.
    rows=_national_rollup_rows(s)
    return {"centers":rows,"center_count":len(rows),"machine_count":sum(x["machine_count"] for x in rows),
            "modeled_capacity":sum(x["modeled_capacity"] for x in rows)}

@app.get("/api/admin/center-intelligence")
def admin_center_intelligence(u:User=Depends(current_user),s:Session=Depends(db)):
    if not u.is_system_admin: raise HTTPException(403,"System admin required")
    rows=_national_rollup_rows(s)
    by_id={x.get("center_id"):x for x in rows if x.get("center_id") is not None}
    users=[]
    for m in s.scalars(select(CenterMembership)).all():
        usr=s.get(User,m.user_id); ctr=s.get(Center,m.center_id)
        if not usr or not ctr: continue
        prof=s.scalar(select(UserProfile).where(UserProfile.user_id==usr.id))
        agg=by_id.get(m.center_id,{})
        users.append({"name":prof.full_name if prof else usr.email,"email":usr.email,"center_name":ctr.name,
            "center_role":m.role,"area_of_responsibility":(agg.get("service_area") or {}).get("provinces",[]),
            "machine_names":[x.get("name") for x in agg.get("machines",[])],"machine_count":agg.get("machine_count",0),
            "modeled_capacity":agg.get("modeled_capacity",0),"current_utilization_pct":agg.get("current_utilization_pct"),
            "capacity_interpretation":agg.get("capacity_interpretation","Insufficient data")})
    return {"rows":users}

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


def _report_snapshot_for_user(s,u):
    """Read-only adapter for Center Report. Never mutates AppState/core workspace."""
    ms=memberships(s,u)
    if u.is_system_admin:
        raise HTTPException(403,"Center Report is for center-scoped users")
    if not ms: raise HTTPException(403,"No center membership")
    m=ms[0]; ctr=s.get(Center,m.center_id)
    key=f"browser-v5:user:{u.id}"
    row=s.scalar(select(AppState).where(AppState.state_key==key))
    payload=json.loads(row.payload) if row and row.payload else {}
    return {"generated_for":{"user_id":u.id,"email":u.email,"role":m.role},
            "center":{"id":ctr.id,"name":ctr.name,"country":ctr.country},
            "snapshot_updated_at":row.updated_at.isoformat() if row and row.updated_at else None,
            "payload":payload}

@app.get("/api/report/center-snapshot")
def center_report_snapshot(u:User=Depends(current_user),s:Session=Depends(db)):
    return _report_snapshot_for_user(s,u)

@app.get("/center-report")
def center_report_page():
    return FileResponse("static/center-report.html")

app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/")
def root(): return FileResponse("index.html")
