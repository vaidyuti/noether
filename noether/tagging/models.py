from django.contrib.postgres.fields import ArrayField
from django.db import models


class TaggableMixin(models.Model):
    """Opt-in tagging storage for any model (ADR-0013).

    Tags are stored denormalized as an array of ``TagConfig`` integer primary
    keys on the tagged row itself, so reading a row's tags never costs a join
    and filtering uses array containment/overlap lookups.
    """

    tags = ArrayField(models.IntegerField(), default=list, blank=True)

    class Meta:
        abstract = True
