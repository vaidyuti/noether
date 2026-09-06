import copy
import json
import uuid

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http.response import Http404
from pydantic import ValidationError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as RestFrameworkValidationError
from rest_framework.fields import get_error_detail
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.viewsets import GenericViewSet

from noether.ledger.exceptions import (
    ConservationError,
    DomainValidationError,
    ExternalIdConflictError,
    ExternalIdUnavailableError,
    ImmutabilityError,
)
from noether.ledger.models_base import slug_or_uuid_filters
from noether.security.authorization.base import PermissionDeniedError


def noether_exception_handler(exc, context):
    if isinstance(exc, PermissionDeniedError):
        return Response({"errors": [{"type": "permission_denied", "msg": str(exc)}]}, status=403)
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
    if isinstance(exc, ExternalIdConflictError):
        return Response({"errors": [{"type": "id_conflict", "msg": exc.message}]}, status=409)
    if isinstance(exc, ExternalIdUnavailableError):
        return Response({"errors": [{"type": "id_conflict", "msg": exc.message}]}, status=400)
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
        if isinstance(detail, list):  # noqa: SIM108 — branch coverage clarity
            msg = " , ".join([str(e) for e in detail])
        else:
            msg = str(detail)
        return Response({"errors": [{"type": "validation_error", "msg": msg}]}, status=400)
    return drf_exception_handler(exc, context)


def extract_client_external_id(request_data):
    """Pull a client-supplied ``id`` out of a write body (ADR-0016).

    Absent, ``None`` and ``""`` all mean "mint one server-side". Anything
    present but unparseable, or parseable but not a UUIDv7, is a client error:
    once an id carries idempotency meaning, silently discarding a bad one turns
    a botched retry into a duplicate row, which is the exact failure
    client-supplied ids exist to prevent.

    Module-level on purpose — both the create and the upsert mixin need it, and
    they are applied independently.
    """
    if not isinstance(request_data, dict):
        return None
    raw = request_data.get("id")
    if raw is None or raw == "":
        return None
    try:
        parsed = uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RestFrameworkValidationError(f"id must be a UUID, got {raw!r}") from exc
    if parsed.version != 7:
        raise RestFrameworkValidationError(f"id must be a UUIDv7, got version {parsed.version}")
    return parsed


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
    #: Response fields that never participate in replay comparison: they are
    #: server-derived, so a genuine replay legitimately differs on them.
    REPLAY_IGNORED_FIELDS = frozenset({"created_date", "modified_date"})

    def clean_create_data(self, request_data):
        return request_data

    def authorize_create(self, instance):
        pass

    def perform_create(self, instance):
        instance.created_by = self.request.user
        instance.updated_by = self.request.user
        with transaction.atomic():
            instance.save()

    def extract_client_external_id(self, request_data):
        return extract_client_external_id(request_data)

    def find_replay_target(self, external_id):
        """Return the visible row already holding ``external_id``, if any.

        Scoped to ``get_queryset()``, so a replay can never reach across a
        ledger boundary — the same rule ``get_object`` follows. An id held by a
        row outside that scope (another ledger's, or a soft-deleted one) is
        unavailable rather than a replay: the caller cannot see it, so the
        server must not confirm what occupies it.
        """
        visible = self.get_queryset().filter(external_id=external_id).first()
        if visible is not None:
            return visible
        if self.database_model.objects.filter(external_id=external_id).exists():
            raise ExternalIdUnavailableError(f"id {external_id} is not available")
        return None

    def build_replay_comparison(self, rendered):
        """Reduce a rendered body to the shape replay equality is judged on."""
        return {
            key: value for key, value in rendered.items() if key not in self.REPLAY_IGNORED_FIELDS
        }

    def replay_create(self, existing, request_data):
        """Answer a create whose id already exists.

        Authorization runs first and unconditionally: a replay is still a
        create attempt, and must not become a read oracle for a caller who
        could not have performed the original write.
        """
        self.authorize_create(self.pydantic_model.model_validate(request_data))
        stored = self.get_retrieve_pydantic_model().serialize(existing).to_json()
        candidate = self.render_replay_candidate(existing, request_data)
        if self.build_replay_comparison(stored) != self.build_replay_comparison(candidate):
            raise ExternalIdConflictError(
                f"id {existing.external_id} already identifies a different object"
            )
        return stored

    def render_replay_candidate(self, existing, request_data):
        """Render what this request *would* have produced, without writing.

        Defaults to overlaying the request body onto the stored row in memory.
        The row is never saved — the overlay exists purely to be compared.

        ``_replay_target`` is published for the duration so that create-time
        uniqueness checks in ``validate_data`` can exclude the row being
        replayed; without it every replay would trip its own uniqueness
        constraint instead of being recognised.
        """
        spec = self.pydantic_model.model_validate(request_data)
        spec._context = {"is_create": True}
        self._replay_target = existing
        try:
            self.validate_data(spec, None)
        finally:
            self._replay_target = None
        candidate = spec.de_serialize(obj=copy.copy(existing))
        return self.get_retrieve_pydantic_model().serialize(candidate).to_json()

    def create(self, request, *args, **kwargs):
        external_id = self.extract_client_external_id(request.data)
        if external_id is not None:
            existing = self.find_replay_target(external_id)
            if existing is not None:
                return Response(
                    self.replay_create(existing, request.data), status=status.HTTP_200_OK
                )
        return Response(
            self.handle_create(request.data, external_id=external_id),
            status=status.HTTP_201_CREATED,
        )

    def handle_create(self, request_data, external_id=None):
        clean_data = self.clean_create_data(request_data)
        instance = self.pydantic_model.model_validate(clean_data)
        instance._context = {"is_create": True}
        self.validate_data(instance, None)
        self.authorize_create(instance)
        model_instance = instance.de_serialize()
        if external_id is not None:
            model_instance.external_id = external_id
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


class _BatchRollback(Exception):
    """Internal signal: unwind the batch transaction after collecting errors."""


class NoetherUpsertMixin:
    """Idempotent bulk create-or-update over a batch of datapoints.

    Identity rule: a datapoint identifies an existing row by ``slug`` when the
    target model actually has a ``slug`` field; otherwise by ``id``
    (``external_id``). No identifier -> create. Identifier present but no row
    matches -> create (never 404), which is what makes re-import idempotent.
    """

    def model_has_slug_field(self):
        try:
            self.database_model._meta.get_field("slug")
        except FieldDoesNotExist:
            return False
        return True

    def resolve_identity(self, datapoint):
        """Return ``(lookup_field, value)`` or ``None`` when this is a create."""
        if self.model_has_slug_field() and "slug" in datapoint:
            return ("slug", datapoint["slug"])
        external_id = extract_client_external_id(datapoint)
        if external_id is not None:
            return ("external_id", external_id)
        return None

    def get_upsert_instance(self, identity):
        """Fetch the row an identity points at, or ``None`` for a create.

        Identity values are already well-formed by this point: ``resolve_identity``
        rejects a malformed ``id`` with a 400 rather than letting it fall through
        to a filter (ADR-0016).
        """
        if identity is None:
            return None
        field, value = identity
        return self.get_queryset().filter(**{field: value}).first()

    def validate_upsert_batch(self, request_data):
        if not isinstance(request_data, dict):
            raise RestFrameworkValidationError("Invalid request body: expected an object")
        datapoints = request_data.get("datapoints", [])
        if not isinstance(datapoints, list):
            raise RestFrameworkValidationError("'datapoints' must be a list")
        if len(datapoints) == 0:
            raise RestFrameworkValidationError("No datapoints provided")
        if len(datapoints) > settings.MAX_DATAPOINTS_PER_UPSERT:
            raise RestFrameworkValidationError(
                f"Too many datapoints provided (max {settings.MAX_DATAPOINTS_PER_UPSERT})"
            )
        seen = set()
        identities = []
        for datapoint in datapoints:
            if not isinstance(datapoint, dict):
                raise RestFrameworkValidationError("Each datapoint must be an object")
            identity = self.resolve_identity(datapoint)
            if identity is not None:
                if identity in seen:
                    raise RestFrameworkValidationError(
                        f"Duplicate identifier in batch: {identity[0]}={identity[1]}"
                    )
                seen.add(identity)
            identities.append(identity)
        return datapoints, identities

    @action(detail=False, methods=["POST"])
    def upsert(self, request, *args, **kwargs):
        datapoints, identities = self.validate_upsert_batch(request.data)
        results = []
        errored = False
        unhandled = False
        try:
            with transaction.atomic():
                for datapoint, identity in zip(datapoints, identities, strict=True):
                    try:
                        instance = self.get_upsert_instance(identity)
                        if instance is None:
                            external_id = None
                            if identity is not None and identity[0] == "external_id":
                                external_id = identity[1]
                            results.append(self.handle_create(datapoint, external_id=external_id))
                        else:
                            results.append(self.handle_update(instance, datapoint))
                    except Exception as exc:
                        errored = True
                        handled = noether_exception_handler(exc, {})
                        if handled is None:
                            unhandled = True
                            raise
                        results.append(handled.data)
                if errored:
                    raise _BatchRollback
        except Exception as exc:
            if unhandled:
                raise exc
            return Response(results, status=status.HTTP_400_BAD_REQUEST)
        return Response(results)


class NoetherBaseViewSet(GenericViewSet):
    pydantic_model = None
    pydantic_read_model = None
    pydantic_update_model = None
    pydantic_retrieve_model = None
    database_model = None
    lookup_field = "external_id"
    pagination_class = NoetherPagination

    #: Set only while a replayed create is being rendered for comparison
    #: (ADR-0016). ``validate_data`` uses it to exclude the row under replay
    #: from its own uniqueness checks.
    _replay_target = None

    def exclude_replay_target(self, queryset):
        """Drop the row currently under replay from a uniqueness queryset."""
        if self._replay_target is None:
            return queryset
        return queryset.exclude(pk=self._replay_target.pk)

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
        """Resolve the URL lookup value as a UUID external_id, else as a slug.

        Slug resolution is scoped automatically: ``get_queryset()`` is already
        narrowed to the viewset's scope (e.g. one ledger), so a slug lookup can
        never cross that boundary.
        """
        queryset = self.get_queryset()
        filters = slug_or_uuid_filters(self.database_model, self.kwargs[self.lookup_field])
        if filters is None:
            raise Http404("Object not found")
        try:
            return queryset.get(**filters)
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


from noether.ledger.api.base import LedgerScopedMixin  # noqa: E402

__all__ = [
    "LedgerScopedMixin",
    "NoetherBaseViewSet",
    "NoetherModelReadOnlyViewSet",
    "NoetherModelViewSet",
    "NoetherPagination",
    "NoetherUpsertMixin",
    "noether_exception_handler",
]
