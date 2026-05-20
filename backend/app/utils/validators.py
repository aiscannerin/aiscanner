import re
from datetime import datetime

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,50}$")
_PHONE_IN_RE = re.compile(r"^(?:\+91)?[6-9]\d{9}$")

VALID_GENDERS = {"male", "female", "other", "prefer_not_to_say"}
VALID_TRADING_EXPERIENCE = {"beginner", "intermediate", "advanced"}


def validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip())) if email else False


def validate_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username.strip())) if username else False


def validate_phone(phone: str) -> bool:
    """Indian mobile: optional +91 prefix, then 10 digits starting with 6-9."""
    return bool(_PHONE_IN_RE.match(phone.strip().replace(" ", "").replace("-", ""))) if phone else False


def validate_dob(dob: str) -> bool:
    """Must be a valid YYYY-MM-DD date and not in the future."""
    if not dob:
        return False
    try:
        datetime.strptime(dob.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_gender(gender: str) -> bool:
    return gender.strip().lower() in VALID_GENDERS if gender else False


def validate_trading_experience(experience: str) -> bool:
    return experience.strip().lower() in VALID_TRADING_EXPERIENCE if experience else False


def validate_password(password: str) -> list[str]:
    """Returns a list of error strings. Empty list means password is valid."""
    if not password:
        return ["Password is required."]
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[0-9]", password):
        errors.append("Password must contain at least one number.")
    return errors
