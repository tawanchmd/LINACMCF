"""v5.8 Phase 4 audit and operations regression tests."""
import os,tempfile,unittest

class AuditOperationsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  from fastapi.testclient import TestClient
  from app.main import app
  from app import db as dbmod
  from sqlalchemy import create_engine
  p=os.path.join(cls.tmp.name,"ops.sqlite")
  eng=create_engine("sqlite:///"+p.replace("\\","/"),connect_args={"check_same_thread":False})
  dbmod.engine=eng;dbmod.SessionLocal.configure(bind=eng)
  import app.main as mainmod
  mainmod.engine=eng
  cls.client=TestClient(app);cls.client.__enter__()
  a=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}).json()
  cls.center=cls.client.post("/api/centers",json={"name":"Audit Center","country":"Thailand"}).json()

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app import db as dbmod
  dbmod.engine.dispose();cls.tmp.cleanup()

 def test_01_lifespan_initializes_schema(self):
  r=self.client.get("/health")
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()["status"],"ok")

 def test_02_system_admin_can_read_audit_log(self):
  r=self.client.get("/api/admin/audit-logs?limit=100")
  self.assertEqual(r.status_code,200,r.text)
  rows=r.json();actions=[x["action"] for x in rows]
  self.assertIn("system.bootstrap",actions)
  self.assertIn("center.create",actions)

 def test_03_audit_limit_is_bounded(self):
  r=self.client.get("/api/admin/audit-logs?limit=99999")
  self.assertEqual(r.status_code,200,r.text)
  self.assertLessEqual(len(r.json()),500)

 def test_04_non_system_admin_cannot_read_audit_log(self):
  member=self.client.post("/api/admin/users",json={"email":"viewer@test.local","password":"ViewerPassword123!"}).json()
  self.client.post("/api/admin/memberships",json={"user_id":member["id"],"center_id":self.center["id"],"role":"viewer"})
  self.client.post("/api/auth/logout")
  self.client.post("/api/auth/login",json={"email":"viewer@test.local","password":"ViewerPassword123!"})
  r=self.client.get("/api/admin/audit-logs")
  self.assertEqual(r.status_code,403,r.text)

if __name__=="__main__": unittest.main()
