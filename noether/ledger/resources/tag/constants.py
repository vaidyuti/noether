from enum import StrEnum


class TagResource(StrEnum):
    """Resource types that may be tagged."""

    transaction = "transaction"


class TagStatus(StrEnum):
    active = "active"
    archived = "archived"
