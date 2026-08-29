"""Specs for tag configs and tag mutation requests (ADR-0009)."""

import datetime

from pydantic import BaseModel

from noether.ledger.models import TagConfig
from noether.ledger.resources.tag.constants import TagResource, TagStatus
from noether.resources.base import ExternalId, NoetherResource


class TagConfigWriteSpec(NoetherResource):
    __model__ = TagConfig
    display: str
    description: str = ""
    status: TagStatus = TagStatus.active
    resource: TagResource
    parent: ExternalId | None = None
    exclusive_children: bool = False
    metadata: dict = {}

    def perform_extra_deserialization(self, is_update, obj):
        obj.parent = self._parent_row


class TagConfigUpdateSpec(NoetherResource):
    __model__ = TagConfig
    display: str | None = None
    description: str | None = None
    status: TagStatus | None = None
    exclusive_children: bool | None = None
    metadata: dict | None = None


class TagConfigReadSpec(NoetherResource):
    __model__ = TagConfig
    id: ExternalId | None = None
    display: str = ""
    description: str = ""
    status: str = ""
    resource: str = ""
    level_cache: int = 0
    has_children: bool = False
    exclusive_children: bool = False
    parent: dict = {}
    metadata: dict = {}
    created_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["parent"] = obj.get_parent_json()


class TagRequest(BaseModel):
    tags: list[ExternalId]
