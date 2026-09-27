"""v5.7 Phase 3 administration safety regression tests."""
import os,tempfile,unittest,subprocess,sys

class AdminSafetyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if "app.db" in sys.modules:
   r=subprocess.run([sys.executable,"-m","unittest",__name__,"-v"],env=os.environ.copy())
   if r.returncode: raise RuntimeError("isolated admin safety tests failed")
   raise unittest.SkipTest("completed in isolated subprocess")
  cls.tmp=tempfile.TemporaryDirectory(); p=os.path.join(cls.tmp.name,"safety.sqlite")
  os.environ["DATABASE_URL"]="sqlite:///"+p.replace("\\","/");os.environ["SESSION_SECRET"]="v57-safety"
  from fastapi.testclient import TestClient
  from app.main import app
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

 def test_04_health_reports_v57(self):
  r=self.client.get("/health");self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["ui"],"v5.7")

if __name__=="__main__": unittest.main()
