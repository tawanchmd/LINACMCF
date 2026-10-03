"""v5.9.1 CenterState -> canonical Machine/DailyHistory reconciliation tests."""
import json
import os
import tempfile
import unittest
from datetime import date


class V591ReconciliationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()

        from sqlalchemy import create_engine
        from app import db as dbmod
        import app.main as mainmod
        from app.models import Base, Center

        p=os.path.join(cls.tmp.name,"v591.sqlite")
        eng=create_engine(
            "sqlite:///"+p.replace("\\","/"),
            connect_args={"check_same_thread":False}
        )

        dbmod.engine=eng
        dbmod.SessionLocal.configure(bind=eng)
        mainmod.engine=eng
        Base.metadata.create_all(eng)

        cls.SessionLocal=dbmod.SessionLocal
        cls.reconcile=staticmethod(mainmod.reconcile_center_state_to_canonical)

        s=cls.SessionLocal()

        a=Center(name="Center A",country="Thailand")
        b=Center(name="Center B",country="Thailand")
        s.add_all([a,b])
        s.commit()
        s.refresh(a)
        s.refresh(b)

        cls.a_id=a.id
        cls.b_id=b.id
        s.close()

    @classmethod
    def tearDownClass(cls):
        from app import db as dbmod
        dbmod.engine.dispose()
        cls.tmp.cleanup()

    def setUp(self):
        from app.models import CenterState,Machine,DailyHistory

        s=self.SessionLocal()
        s.query(DailyHistory).delete()
        s.query(Machine).delete()
        s.query(CenterState).delete()
        s.commit()

        payload_a={
            "centers":{
                "center a":{
                    "center":"Center A",
                    "serverCenterId":self.a_id
                }
            },
            "machines":{
                "center a|infinity":{
                    "centerKey":"center a",
                    "center":"Center A",
                    "machine":"Infinity",
                    "machineInputs":{
                        "op":720,
                        "idle":60,
                        "allow":0.9847,
                        "imrt":0.4,
                        "imrtTime":16.5,
                        "crtTime":11.2,
                        "eff":1,
                        "avgFrac":15,
                        "workingDays":261
                    }
                }
            },
            "histories":{
                "histDaily|center a|infinity":json.dumps({
                    "2025-01-01":{
                        "newPatients":1,
                        "activePatients":0
                    },
                    "2025-02-03":{
                        "newPatients":6,
                        "activePatients":27
                    },
                    "2025-03-31":{
                        "newPatients":4,
                        "activePatients":28
                    }
                })
            },
            "version":"v5.9-center"
        }

        payload_b={
            "centers":{
                "center b":{
                    "center":"Center B",
                    "serverCenterId":self.b_id
                }
            },
            "machines":{
                "center b|vitalbeam":{
                    "centerKey":"center b",
                    "center":"Center B",
                    "machine":"Vitalbeam",
                    "machineInputs":{
                        "op":700,
                        "idle":50,
                        "allow":0.99,
                        "imrt":0.35,
                        "imrtTime":14,
                        "crtTime":8,
                        "eff":0.95,
                        "avgFrac":20,
                        "workingDays":250
                    }
                }
            },
            "histories":{},
            "version":"v5.9-center"
        }

        s.add(CenterState(
            center_id=self.a_id,
            payload=json.dumps(payload_a)
        ))
        s.add(CenterState(
            center_id=self.b_id,
            payload=json.dumps(payload_b)
        ))
        s.commit()
        s.close()

    def test_01_creates_canonical_machine(self):
        from app.models import Machine

        s=self.SessionLocal()
        result=self.reconcile(s,self.a_id)

        machines=s.query(Machine).all()

        self.assertEqual(result["machines"],1)
        self.assertEqual(len(machines),1)

        m=machines[0]
        self.assertEqual(m.center_id,self.a_id)
        self.assertEqual(m.name,"Infinity")
        self.assertEqual(m.operating_minutes,720)
        self.assertEqual(m.idle_minutes,60)
        self.assertEqual(m.imrt_proportion,0.4)
        self.assertEqual(m.imrt_cycle_minutes,16.5)
        self.assertEqual(m.d3_cycle_minutes,11.2)
        self.assertEqual(m.staff_efficacy,1)
        self.assertEqual(m.avg_course_fractions,15)
        self.assertEqual(m.working_days,261)
        self.assertAlmostEqual(m.linac_capacity_allowance,0.9847)

        s.close()

    def test_02_migrates_history(self):
        from app.models import Machine,DailyHistory

        s=self.SessionLocal()
        result=self.reconcile(s,self.a_id)

        m=s.query(Machine).filter_by(
            center_id=self.a_id,
            name="Infinity"
        ).one()

        rows=s.query(DailyHistory).filter_by(
            machine_id=m.id
        ).order_by(DailyHistory.date).all()

        self.assertEqual(result["history_rows"],3)
        self.assertEqual(len(rows),3)

        middle=next(r for r in rows if r.date==date(2025,2,3))
        self.assertEqual(middle.new_patients,6)
        self.assertEqual(middle.active_patients,27)

        s.close()

    def test_03_is_idempotent(self):
        from app.models import Machine,DailyHistory

        s=self.SessionLocal()

        self.reconcile(s,self.a_id)
        self.reconcile(s,self.a_id)

        self.assertEqual(
            s.query(Machine).filter_by(center_id=self.a_id).count(),
            1
        )
        self.assertEqual(
            s.query(DailyHistory).count(),
            3
        )

        s.close()

    def test_04_centers_remain_isolated(self):
        from app.models import Machine,DailyHistory

        s=self.SessionLocal()

        self.reconcile(s,self.a_id)
        self.reconcile(s,self.b_id)

        a=s.query(Machine).filter_by(center_id=self.a_id).all()
        b=s.query(Machine).filter_by(center_id=self.b_id).all()

        self.assertEqual([m.name for m in a],["Infinity"])
        self.assertEqual([m.name for m in b],["Vitalbeam"])

        self.assertEqual(
            s.query(DailyHistory)
             .filter(DailyHistory.machine_id==a[0].id)
             .count(),
            3
        )
        self.assertEqual(
            s.query(DailyHistory)
             .filter(DailyHistory.machine_id==b[0].id)
             .count(),
            0
        )

        s.close()

    def test_05_preview_is_read_only(self):
        from app.models import Machine,DailyHistory
        from app.main import preview_center_state_reconciliation

        s=self.SessionLocal()

        preview=preview_center_state_reconciliation(s,self.a_id)

        self.assertEqual(preview["center_id"],self.a_id)
        self.assertEqual(preview["machines_to_create"],["Infinity"])
        self.assertEqual(preview["machines_to_update"],[])
        self.assertEqual(preview["history_rows_to_create"],3)
        self.assertEqual(preview["history_rows_to_update"],0)

        # Preview must not modify canonical tables.
        self.assertEqual(s.query(Machine).count(),0)
        self.assertEqual(s.query(DailyHistory).count(),0)

        s.close()

    def test_06_preview_after_reconcile_reports_existing_rows(self):
        from app.models import Machine,DailyHistory
        from app.main import preview_center_state_reconciliation

        s=self.SessionLocal()

        self.reconcile(s,self.a_id)

        machine_count_before=s.query(Machine).count()
        history_count_before=s.query(DailyHistory).count()

        preview=preview_center_state_reconciliation(s,self.a_id)

        self.assertEqual(preview["machines_to_create"],[])
        self.assertEqual(preview["machines_to_update"],["Infinity"])
        self.assertEqual(preview["history_rows_to_create"],0)
        self.assertEqual(preview["history_rows_to_update"],3)

        # Preview itself must still be read-only.
        self.assertEqual(s.query(Machine).count(),machine_count_before)
        self.assertEqual(s.query(DailyHistory).count(),history_count_before)

        s.close()

    def test_07_rejects_cross_center_contaminated_machine(self):
        import json

        from app.models import CenterState, Machine, DailyHistory
        from app.main import (
            preview_center_state_reconciliation,
            reconcile_center_state_to_canonical,
        )

        s = self.SessionLocal()

        state = s.query(CenterState).filter(
            CenterState.center_id == self.a_id
        ).one()

        payload = json.loads(state.payload)

        # Inject a machine belonging to Center B into Center A's state.
        payload["machines"]["b|vitalbeam"] = {
            "center": "B",
            "centerKey": "b",
            "machine": "Vitalbeam",
            "machineInputs": {
                "op": 720,
                "idle": 60,
                "imrt": 0.35,
                "imrtTime": 14,
                "crtTime": 8,
                "eff": 1,
                "avgFrac": 15,
                "workingDays": 261,
                "allow": 0.9885,
            },
        }

        payload["histories"]["histDaily|b|vitalbeam"] = json.dumps({
            "2025-04-01": {
                "newPatients": 9,
                "activePatients": 30,
            }
        })

        state.payload = json.dumps(payload)
        s.commit()

        preview = preview_center_state_reconciliation(s, self.a_id)

        # Center A may contain Infinity, but must never accept
        # contaminated Center B machine/history.
        self.assertNotIn("Vitalbeam", preview["machines_to_create"])
        self.assertNotIn("Vitalbeam", preview["machines_to_update"])

        reconcile_center_state_to_canonical(s, self.a_id)

        contaminated = s.query(Machine).filter(
            Machine.center_id == self.a_id,
            Machine.name == "Vitalbeam",
        ).all()

        self.assertEqual(contaminated, [])

        # Only Center A's original three history rows should exist.
        self.assertEqual(s.query(DailyHistory).count(), 3)

        s.close()

if __name__=="__main__":
    unittest.main()