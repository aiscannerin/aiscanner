import uuid
from datetime import datetime, timezone

from app.extensions import db


class TradingExperience:
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    ALL = [BEGINNER, INTERMEDIATE, ADVANCED]


class Gender:
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    ALL = [MALE, FEMALE, OTHER, PREFER_NOT_TO_SAY]


class User(db.Model):
    __tablename__ = "users"

    # Named unique indexes only — do NOT also set unique=True on the columns.
    # Duplicate unique constraints (column-level + index-level) cause redundant
    # PostgreSQL constraints and confuse Alembic autogenerate.
    __table_args__ = (
        db.Index("ix_users_email", "email", unique=True),
        db.Index("ix_users_username", "username", unique=True),
    )

    id = db.Column(
        db.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    full_name = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(50), nullable=False)   # unique enforced by ix_users_username
    email = db.Column(db.String(255), nullable=False)      # unique enforced by ix_users_email
    phone = db.Column(db.String(20), nullable=True)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    trading_experience = db.Column(
        db.String(20),
        nullable=True,
        default=TradingExperience.BEGINNER,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    role_id = db.Column(
        db.UUID(as_uuid=True),
        db.ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    # lazy="select" (default) is used throughout — lazy="dynamic" is deprecated
    # in SQLAlchemy 2.x. Service layer must query via db.session.execute() directly.
    role = db.relationship("Role", back_populates="users")
    subscriptions = db.relationship(
        "Subscription",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    payments = db.relationship(
        "Payment",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens = db.relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    otp_verifications = db.relationship(
        "OtpVerification",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    scan_jobs = db.relationship(
        "ScanJob",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User {self.email}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "full_name": self.full_name,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "dob": self.dob.isoformat() if self.dob else None,
            "gender": self.gender,
            "address": self.address,
            "trading_experience": self.trading_experience,
            "email_verified": self.email_verified,
            "is_active": self.is_active,
            "role": self.role.to_dict() if self.role else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
