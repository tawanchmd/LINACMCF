# LINACMCF database operations

Production PostgreSQL must never be reset, dropped, recreated, or automatically stamped during application startup. A persistent volume is not a backup.

## Before a production migration
1. Confirm deployment commit and environment.
2. Create and verify a PostgreSQL backup using the hosting platform backup mechanism or pg_dump.
3. Record the current Alembic revision.
4. Review migration SQL and test against a disposable or staging copy.
5. Run regression tests and database smoke checks.
6. Only then apply the migration to production.

## v5.8 baseline adoption
Revision 20260927_01 is intentionally schema-neutral because existing LINACMCF databases already contain the modeled schema. First verify expected tables and centers.is_active, and create a backup. Then run:

    alembic stamp 20260927_01

Stamping records migration state only; it does not create or delete application tables or rows.

## Restore drill
Restore a backup into a separate PostgreSQL database, never over the live database. Verify row counts for users, centers, center_memberships, machines, daily_history, app_state, audit_log, user_profiles, and access_requests. Start LINACMCF against the restored copy and run the normal smoke workflow.

## Transition
During v5.8 the legacy idempotent startup migration remains for backward compatibility. Alembic is introduced without changing production startup behavior. Removing the legacy startup migration is a later explicit step after production has been safely baselined.
