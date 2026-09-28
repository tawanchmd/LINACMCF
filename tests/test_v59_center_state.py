"""v5.9 Phase 2 center-scoped state isolation tests."""
import os,tempfile,unittest

class CenterScopedStateTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  from fastapi.testclient import TestClient
  from app.main import app
  from app import db as dbmod
  from sqlalchemy import create_engine
  p=os.path.join(cls.tmp.name,"center-state.sqlite")
  eng=create_engine("sqlite:///"+p.replace("\\","/"),connect_args={"check_same_thread":False})
  dbmod.engine=eng;dbmod.SessionLocal.configure(bind=eng)
  import app.main as mainmod
  mainmod.engine=eng
  cls.client=TestClient(app);cls.client.__enter__()
  cls.admin=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}).json()
  cls.a=cls.client.post("/api/centers",json={"name":"Center A","country":"Thailand"}).json()
  cls.b=cls.client.post("/api/centers",json={"name":"Center B","country":"Thailand"}).json()
  cls.writer=cls.client.post("/api/admin/users",json={"email":"writer@test.local","password":"WriterPassword123!"}).json()
  cls.client.post("/api/admin/memberships",json={"user_id":cls.writer["id"],"center_id":cls.a["id"],"role":"data_entry"})
  cls.client.post("/api/admin/memberships",json={"user_id":cls.writer["id"],"center_id":cls.b["id"],"role":"viewer"})
  cls.client.post("/api/auth/logout")
  cls.client.post("/api/auth/login",json={"email":"writer@test.local","password":"WriterPassword123!"})

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app import db as dbmod
  dbmod.engine.dispose();cls.tmp.cleanup()

 def test_01_writer_can_write_own_writable_center(self):
  r=self.client.put(f"/api/centers/{self.a['id']}/state",json={"payload":{"population":{"population":123}}})
  self.assertEqual(r.status_code,200,r.text)
  g=self.client.get(f"/api/centers/{self.a['id']}/state")
  self.assertEqual(g.status_code,200,g.text)
  self.assertEqual(g.json()["payload"]["population"]["population"],123)

 def test_02_viewer_membership_cannot_write_even_if_other_center_is_writable(self):
  r=self.client.put(f"/api/centers/{self.b['id']}/state",json={"payload":{"forbidden":True}})
  self.assertEqual(r.status_code,403,r.text)

 def test_03_viewer_can_read_its_center(self):
  r=self.client.get(f"/api/centers/{self.b['id']}/state")
  self.assertEqual(r.status_code,200,r.text)
  self.assertIsNone(r.json()["payload"])

 def test_04_nonmember_center_is_denied(self):
  self.client.post("/api/auth/logout")
  self.client.post("/api/auth/login",json={"email":"admin@test.local","password":"AdminPassword123!"})
  c=self.client.post("/api/centers",json={"name":"Center C","country":"Thailand"}).json()
  self.client.post("/api/auth/logout")
  self.client.post("/api/auth/login",json={"email":"writer@test.local","password":"WriterPassword123!"})
  self.assertEqual(self.client.get(f"/api/centers/{c['id']}/state").status_code,403)
  self.assertEqual(self.client.put(f"/api/centers/{c['id']}/state",json={"payload":{}}).status_code,403)

 def test_05_center_payloads_are_independent(self):
  a=self.client.get(f"/api/centers/{self.a['id']}/state").json()["payload"]
  b=self.client.get(f"/api/centers/{self.b['id']}/state").json()["payload"]
  self.assertNotEqual(a,b)

if __name__=="__main__": unittest.main()
