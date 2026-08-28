class TransactionValidator:
    """Base class for domain post-time validation hooks.

    Subclasses implement ``validate(transaction, entries, balances_after)``
    and raise ``noether.ledger.exceptions.DomainValidationError`` to reject.
    Validators MUST be side-effect free and deterministic.
    """

    def validate(self, transaction, entries, balances_after) -> None:
        raise NotImplementedError
