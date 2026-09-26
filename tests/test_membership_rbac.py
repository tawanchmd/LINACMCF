import unittest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Center, User, UserProfile, CenterMembership, Machine
from app.main import (
    CenterMemberAddIn, MembershipIn, MachineIn, HistoryRowIn,
    center_members, center_add_member, center_member_role, center_remove_member,
    create_machine, history, save_history, can_center, put_state, StateIn
)
from datetime import date

class MembershipRBACRegression(unittest.TestCase):
    def setUp(self):
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.s=sessionmaker(bind=engine)()
        self.c1=Center(name="Center A",country="Thailand"); self.c2=Center(name="Center B",country="Thailand")
        self.s.add_all([self.c1,self.c2]); self.s.flush()
        self.admin=self.user("admin@test.local","Admin")
        self.entry=self.user("entry@test.local","Entry")
        self.viewer=self.user("viewer@test.local","Viewer")
        self.other=self.user("other@test.local","Other")
        self.s.add_all([
            CenterMembership(user_id=self.admin.id,center_id=self.c1.id,role="center_admin"),
            CenterMembership(user_id=self.entry.id,center_id=self.c1.id,role="data_entry"),
            CenterMembership(user_id=self.viewer.id,center_id=self.c1.id,role="viewer"),
            CenterMembership(user_id=self.other.id,center_id=self.c2.id,role="center_admin"),
        ]); self.s.commit()
        self.machine=Machine(center_id=self.c1.id,name="LINAC A"); self.s.add(self.machine); self.s.commit()

    def tearDown(self): self.s.close()

    def user(self,email,name):
        u=User(email=email,password_hash="test",is_active=True,is_system_admin=False)
        self.s.add(u); self.s.flush(); self.s.add(UserProfile(user_id=u.id,full_name=name)); self.s.flush(); return u

    def denied(self,fn,*args):
        with self.assertRaises(HTTPException) as cm: fn(*args)
        self.assertEqual(cm.exception.status_code,403)

    def test_role_matrix_and_cross_center_isolation(self):
        self.assertTrue(can_center(self.s,self.admin,self.c1.id,"admin_write"))
        self.assertTrue(can_center(self.s,self.entry,self.c1.id,"history_write"))
        self.assertFalse(can_center(self.s,self.entry,self.c1.id,"admin_write"))
        self.assertFalse(can_center(self.s,self.viewer,self.c1.id,"history_write"))
        self.assertTrue(can_center(self.s,self.viewer,self.c1.id,"read"))
        self.assertFalse(can_center(self.s,self.admin,self.c2.id,"read"))
        self.denied(center_members,self.c1.id,self.viewer,self.s)
        self.denied(center_members,self.c2.id,self.admin,self.s)

    def test_history_permissions(self):
        row=[HistoryRowIn(date=date(2026,1,2),new_patients=2,active_patients=20)]
        self.denied(save_history,self.machine.id,row,self.viewer,self.s)
        self.assertEqual(save_history(self.machine.id,row,self.entry,self.s)["saved"],1)
        self.assertEqual(len(history(self.machine.id,self.viewer,self.s)),1)

    def test_machine_creation_admin_only(self):
        x=MachineIn(center_id=self.c1.id,name="LINAC B")
        self.denied(create_machine,x,self.entry,self.s)
        self.assertEqual(create_machine(x,self.admin,self.s).name,"LINAC B")

    def test_last_admin_protection(self):
        x=MembershipIn(user_id=self.admin.id,center_id=self.c1.id,role="viewer")
        with self.assertRaises(HTTPException) as cm: center_member_role(self.c1.id,self.admin.id,x,self.admin,self.s)
        self.assertEqual(cm.exception.status_code,409)
        with self.assertRaises(HTTPException) as cm: center_remove_member(self.c1.id,self.admin.id,self.admin,self.s)
        self.assertEqual(cm.exception.status_code,409)

    def test_add_change_remove_member(self):
        newcomer=self.user("new@test.local","New User"); self.s.commit()
        out=center_add_member(self.c1.id,CenterMemberAddIn(email=newcomer.email,role="viewer"),self.admin,self.s)
        self.assertEqual(out["role"],"viewer")
        out=center_member_role(self.c1.id,newcomer.id,MembershipIn(user_id=newcomer.id,center_id=self.c1.id,role="data_entry"),self.admin,self.s)
        self.assertEqual(out["role"],"data_entry")
        self.assertTrue(center_remove_member(self.c1.id,newcomer.id,self.admin,self.s)["ok"])

    def test_viewer_state_is_read_only(self):
        with self.assertRaises(HTTPException) as cm:
            put_state(StateIn(payload={"centers":"{}","machines":"{}","histories":{}}),self.viewer,self.s)
        self.assertEqual(cm.exception.status_code,403)
        self.assertTrue(put_state(StateIn(payload={"centers":"{}","machines":"{}","histories":{}}),self.entry,self.s)["saved"])

    def test_200_member_center_list(self):
        for i in range(197):
            u=self.user(f"scale{i:03d}@test.local",f"Scale {i:03d}")
            self.s.add(CenterMembership(user_id=u.id,center_id=self.c1.id,role=("data_entry" if i%3==0 else "viewer")))
        self.s.commit()
        rows=center_members(self.c1.id,self.admin,self.s)
        self.assertEqual(len(rows),200)
        self.assertEqual(len({r["user_id"] for r in rows}),200)

if __name__=="__main__":
    unittest.main(verbosity=2)
