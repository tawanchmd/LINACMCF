from datetime import date,datetime
from sqlalchemy import String,Integer,Float,Date,DateTime,ForeignKey,UniqueConstraint,func,Text
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base

class Center(Base):
 __tablename__="centers"; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(180),unique=True); country:Mapped[str]=mapped_column(String(80),default="Thailand"); created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
class Machine(Base):
 __tablename__="machines"; id:Mapped[int]=mapped_column(primary_key=True); center_id:Mapped[int]=mapped_column(ForeignKey("centers.id",ondelete="CASCADE"),index=True); name:Mapped[str]=mapped_column(String(180)); model:Mapped[str|None]=mapped_column(String(180)); operating_minutes:Mapped[float|None]=mapped_column(Float); idle_minutes:Mapped[float|None]=mapped_column(Float); imrt_proportion:Mapped[float|None]=mapped_column(Float); imrt_cycle_minutes:Mapped[float|None]=mapped_column(Float); d3_cycle_minutes:Mapped[float|None]=mapped_column(Float); staff_efficacy:Mapped[float|None]=mapped_column(Float); avg_course_fractions:Mapped[float|None]=mapped_column(Float); working_days:Mapped[int|None]=mapped_column(Integer); linac_capacity_allowance:Mapped[float|None]=mapped_column(Float); __table_args__=(UniqueConstraint("center_id","name"),)
class DailyHistory(Base):
 __tablename__="daily_history"; id:Mapped[int]=mapped_column(primary_key=True); machine_id:Mapped[int]=mapped_column(ForeignKey("machines.id",ondelete="CASCADE"),index=True); date:Mapped[date]=mapped_column(Date,index=True); new_patients:Mapped[int]=mapped_column(Integer); active_patients:Mapped[int]=mapped_column(Integer); __table_args__=(UniqueConstraint("machine_id","date"),)
class AppState(Base):
 __tablename__="app_state"; id:Mapped[int]=mapped_column(primary_key=True); state_key:Mapped[str]=mapped_column(String(80),unique=True,index=True); payload:Mapped[str]=mapped_column(Text); updated_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now(),onupdate=func.now())
