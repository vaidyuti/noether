"""django-filter integration for taggable querysets."""

from uuid import UUID

from django_filters import rest_framework as filters

from noether.ledger.models import TagConfig


class TagFilter(filters.CharFilter):
    """Filter a taggable queryset by tag config external id(s).

    Accepts a comma separated list of tag external ids. ``behavior`` decides
    whether a row must carry any (default) or all of them.
    """

    def __init__(self, *args, behavior="any", **kwargs):
        self.behavior = behavior
        super().__init__(*args, **kwargs)

    def filter(self, qs, value):
        if not value:
            return qs
        external_ids = []
        for raw in value.split(","):
            candidate = raw.strip()
            try:
                external_ids.append(UUID(candidate))
            except ValueError:
                continue
        if not external_ids:
            return qs.none()
        tag_ids = list(
            TagConfig.objects.filter(external_id__in=external_ids, deleted=False).values_list(
                "id", flat=True
            )
        )
        if not tag_ids:
            return qs.none()
        if self.behavior == "all":
            return qs.filter(tags__contains=tag_ids)
        return qs.filter(tags__overlap=tag_ids)
