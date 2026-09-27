"""v5.7 Phase 2 System Admin user / role safety tests."""
import os,tempfile,unittest,subprocess,sys

class AdminUserRoleTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  # app.db binds DATABASE_URL at import time. When this module is run after
  # another DB-isolated test module in the same unittest process, run this
  # suite in a fresh interpreter so it gets its own engine cleanly.
  if "app.db" in sys.modules:
   r=subprocess.run([sys.executable,"-m","unittest",__name__,"-v"],env=os.environ.copy())
   if r.returncode: raise RuntimeError("isolated admin user tests failed")
   raise unittest.SkipTest("completed in isolated subprocess")
  cls.tmp=tempfile.TemporaryDirectory(); cls.db_path=os.path.join(cls.tmp.name,"v57users.sqlite")
  os.environ["DATABASE_URL"]="sqlite:///"+cls.db_path.replace("\\","/"); os.environ["SESSION_SECRET"]="v57-users-test"
  from fastapi.testclient import TestClient
  from app.main import app
  cls.client=TestClient(app); cls.client.__enter__()
  r=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}); assert r.status_code==200,r.text
  cls.admin_id=r.json()["user"]["id"]
  r=cls.client.post("/api/centers",json={"name":"Role Safety Center","country":"Thailand"}); assert r.status_code==200,r.text
  cls.center_id=r.json()["id"]
  r=cls.client.post("/api/admin/users",json={"email":"member@test.local","password":"MemberPassword123!"}); assert r.status_code==200,r.text
  cls.member_id=r.json()["id"]

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app.db import engine
  engine.dispose(); cls.tmp.cleanup()

 def test_01_users_include_memberships(self):
  r=self.client.get("/api/admin/users"); self.assertEqual(r.status_code,200,r.text)
  admin=next(x for x in r.json() if x["id"]==self.admin_id)
  self.assertTrue(any(m["center_id"]==self.center_id and m["role"]=="center_admin" for m in admin["memberships"]))

 def test_02_last_admin_cannot_be_demoted(self):
  r=self.client.post("/api/admin/memberships",json={"user_id":self.admin_id,"center_id":self.center_id,"role":"viewer"})
  self.assertEqual(r.status_code,409,r.text)

 def test_03_add_second_admin_then_change_roles(self):
  r=self.client.post("/api/admin/memberships",json={"user_id":self.member_id,"center_id":self.center_id,"role":"center_admin"});self.assertEqual(r.status_code,200,r.text)
  r=self.client.post("/api/admin/memberships",json={"user_id":self.admin_id,"center_id":self.center_id,"role":"viewer"});self.assertEqual(r.status_code,200,r.text)
  r=self.client.post("/api/admin/memberships",json={"user_id":self.admin_id,"center_id":self.center_id,"role":"center_admin"});self.assertEqual(r.status_code,200,r.text)

 def test_04_last_admin_membership_cannot_be_removed(self):
  r=self.client.delete(f"/api/admin/memberships/{self.center_id}/{self.member_id}");self.assertEqual(r.status_code,200,r.text)
  r=self.client.delete(f"/api/admin/memberships/{self.center_id}/{self.admin_id}");self.assertEqual(r.status_code,409,r.text)

 def test_05_user_deactivate_restore_and_self_protection(self):
  r=self.client.patch(f"/api/admin/users/{self.member_id}/status",json={"is_active":False});self.assertEqual(r.status_code,200,r.text)
  r=self.client.patch(f"/api/admin/users/{self.member_id}/status",json={"is_active":True});self.assertEqual(r.status_code,200,r.text)
  r=self.client.patch(f"/api/admin/users/{self.admin_id}/status",json={"is_active":False});self.assertEqual(r.status_code,409,r.text)

if __name__=="__main__": unittest.main()
