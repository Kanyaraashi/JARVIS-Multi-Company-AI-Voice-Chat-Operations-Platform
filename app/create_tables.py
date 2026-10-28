from app import models  # noqa: F401  (loads the table definitions)
from app.db import Base, engine

Base.metadata.create_all(engine)
print("Tables created:", ", ".join(Base.metadata.tables.keys()))