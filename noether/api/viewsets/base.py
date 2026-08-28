import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http.response import Http404
from pydantic import ValidationError
from rest_framework import status
from rest_framework.exceptions import ValidationError as RestFrameworkValidationError
from rest_framework.fields import get_error_detail
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.viewsets import GenericViewSet

from noether.ledger.exceptions import (
    ConservationError,
    DomainValidationError,
    ImmutabilityError,
)
from noether.security.authorization.base import PermissionDeniedError


def noether_exception_handler(exc, context):
    if isinstance(exc, PermissionDeniedError):
        return Response(
            {"errors": [{"type": "permission_denied", "msg": str(exc)}]}, status=403
        )
    if isinstance(exc, DjangoValidationError):
        exc = RestFrameworkValidationError(detail={"detail": get_error_detail(exc)[0]})
    if isinstance(exc, ValidationError):
        return Response({"errors": json.loads(exc.json())}, status=400)
    if isinstance(exc, ConservationError):
        return Response(
            {"errors": [{"type": "conservation_error", "msg": exc.message}]}, status=400
        )
    if isinstance(exc, DomainValidationError):
        return Response(
            {"errors": [{"type": "domain_validation_error", "msg": exc.message}]}, status=400
        )
    if isinstance(exc, ImmutabilityError):
        return Response(
            {"errors": [{"type": "immutable_transaction", "msg": exc.message}]}, status=409
        )
    if isinstance(exc, Http404):
        return Response(
            {
                "errors": [
                    {
                        "type": "object_not_found",
                        "msg": exc.args[0] if exc.args else "Object not found",
                    }
                ]
            },
            status=404,
        )
    if isinstance(exc, RestFrameworkValidationError):
        detail = exc.detail
        if isinstance(detail, dict) and "errors" in detail:
            return Response(detail, status=400)
        if isinstance(detail, list):
            msg = " , ".join([str(e) for e in detail])
        else:
            msg = str(detail)
        return Response({"errors": [{"type": "validation_error", "msg": msg}]}, status=400)
    return drf_exception_handler(exc, context)


class NoetherPagination(LimitOffsetPagination):
    default_limit = 100


class NoetherRetrieveMixin:
    def authorize_retrieve(self, model_instance):
        pass

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self.authorize_retrieve(instance)
        data = self.get_retrieve_pydantic_model().serialize(instance).to_json()
        return Response(data)


class NoetherCreateMixin:
    def clean_create_data(self, request_data):
        return request_data

    def authorize_create(self, instance):
        pass

    def perform_create(self, instance):
        instance.created_by = self.request.user
        instance.updated_by = self.request.user
        with transaction.atomic():
            instance.save()

    def create(self, request, *args, **kwargs):
        return Response(self.handle_create(request.data), status=status.HTTP_201_CREATED)

    def handle_create(self, request_data):
        clean_data = self.clean_create_data(request_data)
        instance = self.pydantic_model.model_validate(clean_data)
        instance._context = {"is_create": True}
        self.validate_data(instance, None)
        self.authorize_create(instance)
        model_instance = instance.de_serialize()
        self.perform_create(model_instance)
        return self.get_retrieve_pydantic_model().serialize(model_instance).to_json()


class NoetherListMixin:
    def serialize_list(self, obj):
        return self.get_read_pydantic_model().serialize(obj).to_json()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        data = [self.serialize_list(obj) for obj in page]
        return paginator.get_paginated_response(data)


class NoetherUpdateMixin:
    def clean_update_data(self, request_data):
        if hasattr(request_data, "dict"):
            request_data = request_data.dict()
        for field in ("id", "external_id"):
            request_data.pop(field, None)
        return request_data

    def authorize_update(self, request_obj, model_instance):
        pass

    def perform_update(self, instance):
        instance.updated_by = self.request.user
        with transaction.atomic():
            instance.save()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(self.handle_update(instance, request.data))

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def handle_update(self, instance, request_data):
        clean_data = self.clean_update_data(request_data)
        pydantic_model = self.get_update_pydantic_model()
        serializer_obj = pydantic_model.model_validate(clean_data)
        serializer_obj._context = {"is_update": True, "object": instance}
        self.validate_data(serializer_obj, instance)
        self.authorize_update(serializer_obj, instance)
        model_instance = serializer_obj.de_serialize(obj=instance)
        self.perform_update(model_instance)
        return self.get_retrieve_pydantic_model().serialize(model_instance).to_json()


class NoetherDestroyMixin:
    def authorize_destroy(self, instance):
        pass

    def validate_destroy(self, instance):
        pass

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save(update_fields=["deleted"])

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.validate_destroy(instance)
        self.authorize_destroy(instance)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NoetherBaseViewSet(GenericViewSet):
    pydantic_model = None
    pydantic_read_model = None
    pydantic_update_model = None
    pydantic_retrieve_model = None
    database_model = None
    lookup_field = "external_id"
    pagination_class = NoetherPagination

    def get_exception_handler(self):
        return noether_exception_handler

    def get_queryset(self):
        return self.database_model.objects.filter(deleted=False).order_by("-id")

    def get_retrieve_pydantic_model(self):
        if self.pydantic_retrieve_model:
            return self.pydantic_retrieve_model
        return self.get_read_pydantic_model()

    def get_read_pydantic_model(self):
        if self.pydantic_read_model:
            return self.pydantic_read_model
        return self.pydantic_model

    def get_update_pydantic_model(self):
        if self.pydantic_update_model:
            return self.pydantic_update_model
        return self.pydantic_model

    def get_object(self):
        queryset = self.get_queryset()
        try:
            return queryset.get(**{self.lookup_field: self.kwargs[self.lookup_field]})
        except (self.database_model.DoesNotExist, DjangoValidationError, ValueError) as exc:
            raise Http404 from exc

    def validate_data(self, instance, model_obj=None):
        pass


class NoetherModelReadOnlyViewSet(NoetherRetrieveMixin, NoetherListMixin, NoetherBaseViewSet):
    pass


class NoetherModelViewSet(
    NoetherRetrieveMixin,
    NoetherCreateMixin,
    NoetherListMixin,
    NoetherUpdateMixin,
    NoetherDestroyMixin,
    NoetherBaseViewSet,
):
    pass
