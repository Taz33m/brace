"""Owner onboarding inputs; creating a label does not establish a scan/unit binding."""
from typing import Literal

from pydantic import Field, field_validator

from .models import Wire


class CreateHouseholdInput(Wire):
    expected_revision: int = Field(ge=1, strict=True)
    unit_label: str | None = Field(default=None, max_length=120)

    @field_validator("unit_label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        label = value.strip()
        if any(ord(char) < 32 for char in label):
            raise ValueError("Use a single-line household label")
        return label or None


class CreatedHousehold(Wire):
    household_id: str
    unit_label: str | None
    unit_confirmed: Literal[False] = False


class CreateHouseholdResult(Wire):
    case_id: str
    household: CreatedHousehold
    case_revision: int
    analysis_revision: int
    duplicate: bool


class InvitationAccess(Wire):
    invitation_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None


class HouseholdAccess(Wire):
    household_id: str
    unit_label: str | None
    active_session_count: int
    active_invitation_count: int
    invitations: list[InvitationAccess]


class HouseholdAccessListing(Wire):
    case_id: str
    case_revision: int
    households: list[HouseholdAccess]


class RevokeHouseholdAccessInput(Wire):
    expected_revision: int = Field(ge=1, strict=True)


class RevokeHouseholdAccessResult(Wire):
    case_id: str
    household_id: str
    case_revision: int
    analysis_revision: int
    revoked_invitation_count: int
    revoked_session_count: int
    duplicate: bool
