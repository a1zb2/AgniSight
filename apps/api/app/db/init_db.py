from sqlalchemy import text

from app.db.database import Base, engine
from app.models import ThermalObservation


def init_database() -> None:
    with engine.begin() as connection:
        connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS postgis")
        )

    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_database()
    print("Database initialized successfully.")