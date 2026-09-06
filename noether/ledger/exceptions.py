class LedgerError(Exception):
    """Base for kernel lifecycle errors."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ConservationError(LedgerError):
    """Per-unit debits != credits, or another kernel invariant violated."""


class ImmutabilityError(LedgerError):
    """Attempted mutation of a posted/reversed transaction."""


class DomainValidationError(LedgerError):
    """A domain validator rejected the post."""


class ExternalIdConflictError(LedgerError):
    """A create replayed a known ``external_id`` with a different body.

    The client asserted "this id means *this* object" and then asserted
    something else. Returning the stored row would silently discard the second
    assertion, so the caller is told instead (ADR-0016).
    """


class ExternalIdUnavailableError(LedgerError):
    """A client-supplied ``external_id`` is taken by a row the caller cannot see.

    Deliberately distinct from :class:`ExternalIdConflictError`: the caller has
    no read access to the occupying row, so the server cannot say whether this
    is a replay, and must not confirm the row exists.
    """
