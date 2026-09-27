import os
from alembic import context
from sqlalchemy import engine_from_config,pool
from app.db import Base
from app import models

config=context.config
url=os.getenv("DATABASE_URL",config.get_main_option("sqlalchemy.url"))
if url.startswith("postgresql://"): url=url.replace("postgresql://","postgresql+psycopg://",1)
elif url.startswith("postgres://"): url=url.replace("postgres://","postgresql+psycopg://",1)
config.set_main_option("sqlalchemy.url",url.replace("%","%%"))
target_metadata=Base.metadata
if context.is_offline_mode():
 context.configure(url=url,target_metadata=target_metadata,literal_binds=True,compare_type=True)
 with context.begin_transaction(): context.run_migrations()
else:
 connectable=engine_from_config(config.get_section(config.config_ini_section),prefix="sqlalchemy.",poolclass=pool.NullPool)
 with connectable.connect() as connection:
  context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
  with context.begin_transaction(): context.run_migrations()
