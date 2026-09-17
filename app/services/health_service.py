from sqlalchemy import text
from sqlalchemy.orm import Session


def check_database_connection(db: Session) -> tuple[bool, str]:
    try:
        db.execute(text("SELECT 1"))
        return True, "Database connection successful"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
