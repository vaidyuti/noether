"""Viewset mixin adding set/unset tag detail actions to a taggable resource."""

from rest_framework.decorators import action
from rest_framework.response import Response

from noether.ledger.resources.tag.spec import TagRequest
from noether.tagging.base import LedgerTagManager


class TagMixin:
    """Adds ``set-tag`` / ``unset-tag`` detail actions.

    The viewset must declare ``tag_resource_type`` and expose ``get_ledger()``.
    """

    tag_resource_type = None
    tag_manager_class = LedgerTagManager

    def get_tag_manager(self):
        return self.tag_manager_class(self.get_ledger())

    def authorize_tag(self, instance):
        """Hook for viewset-level authorization; no-op by default."""

    @action(detail=True, methods=["POST"], url_path="set-tag")
    def set_tag(self, request, *args, **kwargs):
        instance = self.get_object()
        self.authorize_tag(instance)
        tag_request = TagRequest.model_validate(request.data)
        self.get_tag_manager().set_tags(
            self.tag_resource_type, instance, tag_request.tags, request.user
        )
        return Response(self.get_retrieve_pydantic_model().serialize(instance).to_json())

    @action(detail=True, methods=["POST"], url_path="unset-tag")
    def unset_tag(self, request, *args, **kwargs):
        instance = self.get_object()
        self.authorize_tag(instance)
        tag_request = TagRequest.model_validate(request.data)
        self.get_tag_manager().unset_tags(instance, tag_request.tags, request.user)
        return Response(self.get_retrieve_pydantic_model().serialize(instance).to_json())
