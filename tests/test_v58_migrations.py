"""v5.8 Phase 3 migration-framework safety tests."""
import os,tempfile,unittest
from pathlib import Path

class MigrationFrameworkTests(unittest.TestCase):
 def test_01_baseline_revision_is_schema_neutral(self):
  p=Path("migrations/versions/20260927_01_v58_baseline.py")
  text=p.read_text(encoding="utf-8")
  self.assertIn('revision="20260927_01"',text)
  self.assertIn("def upgrade(): pass",text)
  self.assertNotIn("drop_table",text.lower())
  self.assertNotIn("drop_column",text.lower())

 def test_02_alembic_uses_database_url(self):
  text=Path("migrations/env.py").read_text(encoding="utf-8")
  self.assertIn('os.getenv("DATABASE_URL"',text)
  self.assertIn("target_metadata=Base.metadata",text)

 def test_03_upgrade_head_creates_only_version_marker_on_existing_schema(self):
  from alembic.config import Config
  from alembic import command
  from sqlalchemy import create_engine,inspect
  from app.db import Base
  from app import models
  with tempfile.TemporaryDirectory() as td:
   url="sqlite:///"+os.path.join(td,"migration.sqlite").replace("\\","/")
   eng=create_engine(url)
   Base.metadata.create_all(eng)
   before=set(inspect(eng).get_table_names())
   old=os.environ.get("DATABASE_URL");os.environ["DATABASE_URL"]=url
   try:
    cfg=Config("alembic.ini");command.upgrade(cfg,"head")
   finally:
    if old is None: os.environ.pop("DATABASE_URL",None)
    else: os.environ["DATABASE_URL"]=old
   after=set(inspect(eng).get_table_names())
   self.assertEqual(after,before|{"alembic_version"})
   with eng.connect() as conn:
    from sqlalchemy import text
    self.assertEqual(conn.execute(text("select version_num from alembic_version")).scalar(),"20260927_01")

if __name__=="__main__": unittest.main()
