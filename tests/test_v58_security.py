"""v5.8 Phase 1 authentication and System Admin safety regression tests."""
import os,subprocess,sys,tempfile,textwrap,unittest

class ProductionSecretTests(unittest.TestCase):
 def test_01_production_requires_explicit_session_secret(self):
  env=os.environ.copy()
  env["APP_ENV"]="production";env.pop("SESSION_SECRET",None)
  p=subprocess.run([sys.executable,"-c","import app.main"],env=env,capture_output=True,text=True)
  self.assertNotEqual(p.returncode,0)
  self.assertIn("SESSION_SECRET is required",p.stderr+p.stdout)

 def test_02_production_accepts_explicit_session_secret(self):
  env=os.environ.copy();env["APP_ENV"]="production";env["SESSION_SECRET"]="test-explicit-production-secret"
  with tempfile.TemporaryDirectory() as td:
   env["DATABASE_URL"]="sqlite:///"+os.path.join(td,"secret.sqlite").replace("\\","/")
   p=subprocess.run([sys.executable,"-c","import app.main"],env=env,capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr+p.stdout)

class SystemAdminSafetyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  from fastapi.testclient import TestClient
  from app.main import app
  from app import db as dbmod
  from sqlalchemy import create_engine
  p=os.path.join(cls.tmp.name,"v58.sqlite")
  test_engine=create_engine("sqlite:///"+p.replace("\\","/"),connect_args={"check_same_thread":False})
  dbmod.engine=test_engine;dbmod.SessionLocal.configure(bind=test_engine)
  import app.main as mainmod
  mainmod.engine=test_engine
  cls.client=TestClient(app);cls.client.__enter__()
  a=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"}).json()
  cls.admin=a["user"]["id"]

 @classmethod
 def tearDownClass(cls):
  cls.client.__exit__(None,None,None)
  from app import db as dbmod
  dbmod.engine.dispose();cls.tmp.cleanup()

 def test_03_last_active_system_admin_cannot_be_deactivated(self):
  r=self.client.patch(f"/api/admin/users/{self.admin}/status",json={"is_active":False})
  self.assertEqual(r.status_code,409,r.text)

 def test_04_health_reports_v58(self):
  r=self.client.get("/health")
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()["ui"],"v5.8")

if __name__=="__main__": unittest.main()
