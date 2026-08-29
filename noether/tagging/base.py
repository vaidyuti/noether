"""Reusable tagging engine (ADR-0013)."""

from rest_framework.exceptions import ValidationError

from noether.ledger.models import TagConfig
from noether.security.authorization.base import AuthorizationController, PermissionDeniedError


class BaseTagManager:
    """Storage-agnostic tagging protocol.

    Subclasses decide how tag configs are resolved (the scope) and where the
    denormalized id array lives on the tagged resource.
    """

    def get_resource_tags(self, resource):
        return resource.tags or []

    def set_instance_tags(self, resource, tags):
        resource.tags = tags
        return ["tags"]

    def get_tag_config_object(self, external_id):
        raise NotImplementedError

    def set_tag(self, resource_type, resource, tag, user):
        raise NotImplementedError

    def set_tags(self, resource_type, resource, tags, user):
        for tag in tags:
            self.set_tag(resource_type, resource, tag, user)

    def unset_tag(self, resource, tag, user):
        raise NotImplementedError

    def unset_tags(self, resource, tags, user):
        for tag in tags:
            self.unset_tag(resource, tag, user)

    def render_tags(self, resource):
        raise NotImplementedError


class LedgerTagManager(BaseTagManager):
    """Resolves and applies tag configs within a single ledger's scope."""

    def __init__(self, ledger):
        self.ledger = ledger

    def get_tag_config_object(self, external_id):
        return TagConfig.objects.filter(
            ledger=self.ledger, external_id=external_id, deleted=False
        ).first()

    def _resolve(self, external_id):
        tag_config = self.get_tag_config_object(external_id)
        if tag_config is None:
            raise ValidationError(f"unknown tag {external_id} in this ledger")
        return tag_config

    def _authorize(self, user, tag_config, verb):
        allowed = AuthorizationController.call(
            "can_apply_tag_config", user, self.ledger, tag_config
        )
        if not allowed:
            raise PermissionDeniedError(f"missing permission to {verb} tag {tag_config.display!r}")

    def _exclusive_root_ids(self, tag_config):
        """Ancestor ids (nearest first) that declare exclusive subtrees."""
        ancestor_ids = tag_config.parent_cache
        if not ancestor_ids:
            return []
        exclusive = TagConfig.objects.filter(
            id__in=ancestor_ids, exclusive_children=True
        ).values_list("id", flat=True)
        return [i for i in reversed(ancestor_ids) if i in set(exclusive)]

    def _check_exclusivity(self, tag_config, applied_ids):
        """Reject a tag when a governing ancestor declares subtree exclusivity."""
        if not applied_ids:
            return
        for root_id in self._exclusive_root_ids(tag_config):
            conflict = (
                TagConfig.objects.filter(id__in=applied_ids)
                .filter(parent_cache__contains=[root_id])
                .exclude(id=tag_config.id)
                .first()
            )
            if conflict is not None:
                root = TagConfig.objects.get(id=root_id)
                raise ValidationError(
                    f"tag {root.display!r} allows only one tag from its subtree; "
                    f"{conflict.display!r} is already applied"
                )

    def set_tag(self, resource_type, resource, tag, user):
        tags = self.get_resource_tags(resource)
        tag_config = self._resolve(tag)
        self._authorize(user, tag_config, "apply")
        if tag_config.resource != resource_type:
            raise ValidationError(
                f"tag {tag_config.display!r} applies to {tag_config.resource}, not {resource_type}"
            )
        if tag_config.id in tags:
            raise ValidationError(f"tag {tag_config.display!r} is already applied")
        self._check_exclusivity(tag_config, tags)
        fields = self.set_instance_tags(resource, [*tags, tag_config.id])
        resource.save(update_fields=fields)

    def unset_tag(self, resource, tag, user):
        tags = self.get_resource_tags(resource)
        tag_config = self._resolve(tag)
        self._authorize(user, tag_config, "remove")
        if tag_config.id not in tags:
            raise ValidationError(f"tag {tag_config.display!r} is not applied")
        fields = self.set_instance_tags(resource, [t for t in tags if t != tag_config.id])
        resource.save(update_fields=fields)

    def render_tags(self, resource):
        from noether.ledger.resources.tag.spec import TagConfigReadSpec

        tags = self.get_resource_tags(resource)
        queryset = TagConfig.objects.filter(id__in=tags).order_by("id")
        return [TagConfigReadSpec.serialize(tag_config).to_json() for tag_config in queryset]
