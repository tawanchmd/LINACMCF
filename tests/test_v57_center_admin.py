"""Phase 1 regression tests for safe System Admin center lifecycle management.

Run:
    python -m unittest tests.test_v57_center_admin -v
"""
import os,tempfile,unittest

class CenterAdminPhase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        from fastapi.testclient import TestClient
        from app.main import app
        from app import db as dbmod
        from sqlalchemy import create_engine
        cls.db_path=os.path.join(cls.tmp.name,"v57.sqlite")
        test_engine=create_engine("sqlite:///"+cls.db_path.replace("\\","/"),connect_args={"check_same_thread":False})
        dbmod.engine=test_engine; dbmod.SessionLocal.configure(bind=test_engine)
        import app.main as mainmod
        mainmod.engine=test_engine
        cls.client=TestClient(app)
        cls.ctx=cls.client.__enter__()
        r=cls.client.post("/api/auth/setup",json={"email":"admin@test.local","password":"AdminPassword123!"})
        assert r.status_code==200, r.text

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None,None,None)
        from app.db import engine
        engine.dispose()
        cls.tmp.cleanup()

    def test_01_migration_is_idempotent_and_existing_centers_default_active(self):
        from app.main import migrate_schema
        migrate_schema(); migrate_schema()
        r=self.client.post("/api/centers",json={"name":"Lifecycle Center","country":"Thailand"})
        self.assertEqual(r.status_code,200,r.text)
        centers=self.client.get("/api/admin/centers").json()
        row=next(x for x in centers if x["name"]=="Lifecycle Center")
        self.assertTrue(row["is_active"])

    def test_02_edit_archive_restore(self):
        rows=self.client.get("/api/admin/centers").json()
        cid=next(x["id"] for x in rows if x["name"]=="Lifecycle Center")
        r=self.client.patch(f"/api/admin/centers/{cid}",json={"name":"Lifecycle Center Renamed","country":"Thailand"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["name"],"Lifecycle Center Renamed")
        r=self.client.post(f"/api/admin/centers/{cid}/archive")
        self.assertEqual(r.status_code,200,r.text); self.assertFalse(r.json()["is_active"])
        r=self.client.post(f"/api/admin/centers/{cid}/restore")
        self.assertEqual(r.status_code,200,r.text); self.assertTrue(r.json()["is_active"])

    def test_03_delete_nonempty_center_is_blocked(self):
        rows=self.client.get("/api/admin/centers").json()
        cid=next(x["id"] for x in rows if x["name"]=="Lifecycle Center Renamed")
        r=self.client.delete(f"/api/admin/centers/{cid}")
        self.assertEqual(r.status_code,409,r.text)
        self.assertIn("Archive it instead",r.json()["detail"])

    def test_04_empty_center_can_be_deleted(self):
        r=self.client.post("/api/centers",json={"name":"Empty Disposable Center","country":"Thailand"})
        self.assertEqual(r.status_code,200,r.text); cid=r.json()["id"]
        # create_center assigns the System Admin as a member, so remove that membership
        # directly only to construct the exact empty-center condition this endpoint requires.
        from app.db import SessionLocal
        from app.models import CenterMembership
        from sqlalchemy import select
        with SessionLocal() as s:
            m=s.scalar(select(CenterMembership).where(CenterMembership.center_id==cid))
            s.delete(m); s.commit()
        r=self.client.delete(f"/api/admin/centers/{cid}")
        self.assertEqual(r.status_code,200,r.text)

if __name__=="__main__":
    unittest.main()
