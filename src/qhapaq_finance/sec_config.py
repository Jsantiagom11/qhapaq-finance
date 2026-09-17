from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class SecConfig:
    organization: str
    contact_email: str
    max_rps: float

    @property
    def user_agent(self) -> str:
        return f"{self.organization} {self.contact_email}"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    @classmethod
    def from_env(cls) -> SecConfig:
        load_dotenv()

        organization = os.getenv("SEC_ORGANIZATION", "").strip()
        contact_email = os.getenv("SEC_CONTACT_EMAIL", "").strip()

        if not organization:
            raise RuntimeError("Missing required environment variable: SEC_ORGANIZATION")

        if not contact_email or "@" not in contact_email:
            raise RuntimeError("Missing or invalid environment variable: SEC_CONTACT_EMAIL")

        try:
            max_rps = float(os.getenv("SEC_MAX_RPS", "8"))
        except ValueError as exc:
            raise RuntimeError("SEC_MAX_RPS must be numeric") from exc

        if not 0 < max_rps <= 10:
            raise RuntimeError("SEC_MAX_RPS must be > 0 and <= 10")

        return cls(
            organization=organization,
            contact_email=contact_email,
            max_rps=max_rps,
        )
