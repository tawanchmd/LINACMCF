"""v5.7 Phase 3 administration safety regression tests."""
import os,tempfile,unittest

class AdminSafetyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  from fastapi.testclient import TestClient
  from app.main import app
  from app import db as dbmod
  from sqlalchemy import create_engine
  p=os.path.join(cls.tmp.name,"safety.sqlite")
  test_engine=create_engine("sqlite:///"+p.replace("\\","/"),connect_args={"check_same_thread":False})
  dbmod.engine=test_engine; dbmod.SessionLocal.configure(bind=test_engine)
  import app.main as mainmod
  mainmod.engine=test_engine
  cls.client=TestClient(app);cls.client.__enter__()
  a=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}).json();cls.admin=a["user"]["id"]
  cls.c1=cls.client.post("/api/centers",json={"name":"Safety Center","country":"Thailand"}).json()["id"]
  cls.c2=cls.client.post("/api/centers",json={"name":"Archive Center","country":"Thailand"}).json()["id"]
  cls.member=cls.client.post("/api/admin/users",json={"email":"member@test.local","password":"MemberPassword123!"}).json()["id"]

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app.db import engine
  engine.dispose();cls.tmp.cleanup()

 def test_01_cannot_deactivate_last_active_center_admin(self):
  r=self.client.patch(f"/api/admin/users/{self.admin}/status",json={"is_active":False})
  self.assertEqual(r.status_code,409,r.text)

 def test_02_archived_center_rejects_membership_changes(self):
  self.assertEqual(self.client.post(f"/api/admin/centers/{self.c2}/archive").status_code,200)
  r=self.client.post("/api/admin/memberships",json={"user_id":self.member,"center_id":self.c2,"role":"viewer"})
  self.assertEqual(r.status_code,409,r.text)

 def test_03_inactive_user_rejects_membership_changes(self):
  r=self.client.patch(f"/api/admin/users/{self.member}/status",json={"is_active":False});self.assertEqual(r.status_code,200,r.text)
  r=self.client.post("/api/admin/memberships",json={"user_id":self.member,"center_id":self.c1,"role":"viewer"});self.assertEqual(r.status_code,409,r.text)
  self.assertEqual(self.client.patch(f"/api/admin/users/{self.member}/status",json={"is_active":True}).status_code,200)

 def test_04_center_intelligence_groups_members_by_center(self):
  u1=self.client.post(
   "/api/admin/users",
   json={"email":"centeradmin@test.local","password":"CenterAdminPassword123!"}
  ).json()["id"]

  u2=self.client.post(
   "/api/admin/users",
   json={"email":"dataentry@test.local","password":"DataEntryPassword123!"}
  ).json()["id"]

  r=self.client.post(
   "/api/admin/memberships",
   json={"user_id":u1,"center_id":self.c1,"role":"center_admin"}
  )
  self.assertEqual(r.status_code,200,r.text)

  r=self.client.post(
   "/api/admin/memberships",
   json={"user_id":u2,"center_id":self.c1,"role":"data_entry"}
  )
  self.assertEqual(r.status_code,200,r.text)

  r=self.client.get("/api/admin/center-intelligence")
  self.assertEqual(r.status_code,200,r.text)

  rows=[
   x for x in r.json()["rows"]
   if x["center_name"]=="Safety Center"
  ]

  self.assertEqual(len(rows),1)

  members=rows[0]["members"]
  self.assertGreaterEqual(len(members),2)

  by_email={x["email"]:x["role"] for x in members}

  self.assertEqual(by_email["centeradmin@test.local"],"center_admin")
  self.assertEqual(by_email["dataentry@test.local"],"data_entry")
 def test_05_health_endpoint_remains_healthy(self):
  r=self.client.get("/health");self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()["status"],"ok");self.assertEqual(r.json()["database"],"connected")

if __name__=="__main__": unittest.main()
