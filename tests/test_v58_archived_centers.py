"""v5.8 Phase 2 archived-center isolation regression tests."""
import os,tempfile,unittest

class ArchivedCenterIsolationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  from fastapi.testclient import TestClient
  from app.main import app
  from app import db as dbmod
  from sqlalchemy import create_engine
  p=os.path.join(cls.tmp.name,"archive.sqlite")
  eng=create_engine("sqlite:///"+p.replace("\\","/"),connect_args={"check_same_thread":False})
  dbmod.engine=eng;dbmod.SessionLocal.configure(bind=eng)
  import app.main as mainmod
  mainmod.engine=eng
  cls.client=TestClient(app);cls.client.__enter__()
  a=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}).json()
  cls.center=cls.client.post("/api/centers",json={"name":"Archive Isolation Center","country":"Thailand"}).json()
  m=cls.client.post("/api/machines",json={"center_id":cls.center["id"],"name":"LINAC A"}).json()
  cls.machine_id=m["id"]
  cls.client.post(f"/api/admin/centers/{cls.center['id']}/archive")

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app import db as dbmod
  dbmod.engine.dispose();cls.tmp.cleanup()

 def test_01_archived_center_machine_list_is_blocked(self):
  r=self.client.get("/api/machines",params={"center_id":self.center["id"]})
  self.assertEqual(r.status_code,403,r.text)

 def test_02_archived_center_machine_create_is_blocked(self):
  r=self.client.post("/api/machines",json={"center_id":self.center["id"],"name":"LINAC B"})
  self.assertEqual(r.status_code,403,r.text)

 def test_03_archived_center_history_read_and_write_are_blocked(self):
  self.assertEqual(self.client.get(f"/api/machines/{self.machine_id}/history").status_code,403)
  r=self.client.put(f"/api/machines/{self.machine_id}/history",json=[{"date":"2026-09-27","new_patients":1,"active_patients":2}])
  self.assertEqual(r.status_code,403,r.text)

 def test_04_archived_center_hidden_from_onboarding(self):
  r=self.client.get("/api/onboarding/centers");self.assertEqual(r.status_code,200,r.text)
  self.assertNotIn(self.center["id"],[x["id"] for x in r.json()])

 def test_05_archived_center_report_is_blocked_for_center_user(self):
  member=self.client.post("/api/admin/users",json={"email":"centeruser@test.local","password":"CenterUserPassword123!"}).json()
  # Restore only long enough to assign membership, then archive again.
  self.client.post(f"/api/admin/centers/{self.center['id']}/restore")
  self.client.post("/api/admin/memberships",json={"user_id":member["id"],"center_id":self.center["id"],"role":"viewer"})
  self.client.post(f"/api/admin/centers/{self.center['id']}/archive")
  self.client.post("/api/auth/logout")
  self.client.post("/api/auth/login",json={"email":"centeruser@test.local","password":"CenterUserPassword123!"})
  r=self.client.get("/api/report/center-snapshot")
  self.assertEqual(r.status_code,403,r.text)

if __name__=="__main__": unittest.main()
