import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models

#: Maximum stored length of a slug. 100 is long enough for deep human-readable
#: paths ("operating-expenses-utilities-electricity") and short enough to stay
#: comfortably inside a btree index entry.
SLUG_MAX_LENGTH = 100

#: Strict slug grammar: lowercase alphanumerics, hyphen and underscore as
#: internal separators only. No uppercase, no whitespace, no leading/trailing
#: separator, at least one character.
SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$"

_SLUG_RE = re.compile(SLUG_PATTERN)


def validate_slug(value: str) -> str:
    """Validate a slug against :data:`SLUG_PATTERN`. Returns it unchanged."""
    if len(value) > SLUG_MAX_LENGTH:
        raise ValidationError(f"slug must be at most {SLUG_MAX_LENGTH} characters")
    if _SLUG_RE.fullmatch(value) is None:
        raise ValidationError(
            "slug must be lowercase alphanumerics separated by '-' or '_', "
            "and may not start or end with a separator"
        )
    return value


def slug_or_uuid_filters(model, value):
    """Resolve a URL path segment into queryset filters.

    UUID-parsable values address ``external_id``; anything else addresses
    ``slug`` when the model is slugged. Returns ``None`` when the value can
    address nothing on this model.
    """
    try:
        return {"external_id": uuid.UUID(str(value))}
    except ValueError:
        pass
    if issubclass(model, SluggedModel):
        return {"slug": value}
    return None


class SluggedModel(models.Model):
    """Abstract mixin adding an optional, scope-unique human-readable slug.

    Concrete models declare their uniqueness scope via
    :attr:`SLUG_SCOPE_FIELDS` and add the matching
    ``UniqueConstraint(fields=[*SLUG_SCOPE_FIELDS, "slug"])`` in their Meta.
    An empty scope means globally unique.
    """

    SLUG_SCOPE_FIELDS: tuple[str, ...] = ()

    slug = models.CharField(
        max_length=SLUG_MAX_LENGTH,
        null=True,
        blank=True,
        default=None,
        db_index=True,
        validators=[validate_slug],
    )

    class Meta:
        abstract = True

    def validate_slug_field(self):
        if self.slug is None:
            return
        validate_slug(self.slug)
        scope = {field: getattr(self, field) for field in self.SLUG_SCOPE_FIELDS}
        queryset = type(self)._default_manager.filter(slug=self.slug, **scope)
        if self.pk is not None:
            queryset = queryset.exclude(pk=self.pk)
        if queryset.exists():
            raise ValidationError(f"slug {self.slug!r} is already taken in this scope")

    def save(self, *args, **kwargs):
        self.validate_slug_field()
        return super().save(*args, **kwargs)


class NoetherBaseModel(models.Model):
    external_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_date = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True
