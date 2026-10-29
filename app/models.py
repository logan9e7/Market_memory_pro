"""Validated HTTP request contracts shared by API routers."""
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=256)


class RegistrationCredentials(Credentials):
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        if value is None:
            return value
        value = value.strip().lower()
        # Deliberately conservative ASCII email syntax for reliable delivery.
        # Reject controls, whitespace, ambiguous Unicode and header injection.
        if not re.fullmatch(r"[a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+", value):
            raise ValueError("Enter a valid email address")
        return value

    password: str = Field(min_length=12, max_length=256)

    @field_validator("password")
    @classmethod
    def validate_strength(cls, value):
        if not all((any(c.islower() for c in value), any(c.isupper() for c in value),
                    any(c.isdigit() for c in value), any(not c.isalnum() for c in value))):
            raise ValueError("Use uppercase, lowercase, number and symbol")
        return value


class EmailVerificationToken(BaseModel):
    token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ResendVerification(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return RegistrationCredentials.normalize_email(value)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, value):
        if not all((any(c.islower() for c in value), any(c.isupper() for c in value),
                    any(c.isdigit() for c in value), any(not c.isalnum() for c in value))):
            raise ValueError("Use uppercase, lowercase, number and symbol")
        return value


class Quote(BaseModel):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9.^_-]+$")
    price: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, value):
        return value.upper()


class Snapshot(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=5000)


class Visit(BaseModel):
    event_id: str = Field(min_length=8, max_length=100)
    kind: Literal["open", "close"]


class Decision(Quote):
    setup: str = Field(min_length=2, max_length=120)
    side: Literal["buy", "sell"]
    condition: Literal["above", "below"]
    trigger_price: float = Field(gt=0, allow_inf_nan=False)
    note: str = Field(min_length=1, max_length=5000)
    request_id: str = Field(min_length=8, max_length=100)

    @field_validator("setup", "note")
    @classmethod
    def text_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be blank")
        return value


class Review(BaseModel):
    outcome: Literal["win", "loss"]
    lesson: str = Field(min_length=1, max_length=5000)

    @field_validator("lesson")
    @classmethod
    def lesson_required(cls, value):
        if not value.strip():
            raise ValueError("Record a lesson")
        return value.strip()


class Alert(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    condition: Literal["above", "below"]
    target: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")





