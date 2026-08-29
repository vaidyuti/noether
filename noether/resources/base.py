import uuid
from typing import Annotated

from django.db import models
from pydantic import BaseModel, Field

from noether.ledger.models_base import SLUG_MAX_LENGTH, SLUG_PATTERN

#: pydantic field type for slugs: same grammar as the model-level validator.
SlugStr = Annotated[str, Field(pattern=SLUG_PATTERN, max_length=SLUG_MAX_LENGTH)]

#: pydantic field type for an ``external_id``.
#:
#: Deliberately version-agnostic. The core mints UUIDv7 (ADR-0016) but ids are
#: opaque on the wire: a client that supplies its own must not be rejected for
#: choosing a different UUID version, and historical v4 ids stay addressable.
ExternalId = uuid.UUID


class NoetherResource(BaseModel):
    """pydantic v2 spec base for API resources"""

    __model__ = None
    __exclude__: list[str] = []

    @classmethod
    def get_database_mapping(cls):
        return [
            field.name
            for field in cls.__model__._meta.fields
            if not isinstance(field, models.ForeignKey)
        ]

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        mapping["id"] = obj.external_id

    @classmethod
    def serialize(cls, obj):
        constructed = {}
        for mapping in cls.get_database_mapping():
            if mapping in cls.model_fields and mapping not in cls.__exclude__:
                constructed[mapping] = getattr(obj, mapping)
        cls.perform_extra_serialization(constructed, obj)
        return cls.model_construct(**constructed)

    def get_context(self):
        return self._context

    def perform_extra_deserialization(self, is_update, obj):
        pass

    def de_serialize(self, obj=None):
        is_update = obj is not None
        if obj is None:
            obj = self.__model__()
        database_fields = self.get_database_mapping()
        dump = self.model_dump(mode="json", exclude_defaults=True)
        for field in dump:
            is_writable = field in database_fields and field not in self.__exclude__
            if is_writable and field not in ("id", "external_id"):
                setattr(obj, field, dump[field])
        self.perform_extra_deserialization(is_update, obj)
        return obj

    def to_json(self):
        return self.model_dump(mode="json")
