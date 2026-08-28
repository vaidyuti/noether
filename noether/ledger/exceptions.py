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
