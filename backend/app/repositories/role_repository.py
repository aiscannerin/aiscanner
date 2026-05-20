from app.extensions import db
from app.models.role import Role


def get_by_name(name: str) -> Role | None:
    return db.session.execute(
        db.select(Role).where(Role.name == name)
    ).scalar_one_or_none()
