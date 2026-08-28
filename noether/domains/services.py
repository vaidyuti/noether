from noether.domains.config import ChartTemplate, DomainConfig


def sync_domain_rows() -> list:
    """Mirror registered DomainConfigs into the Domain table."""
    from noether.domains.registry import DomainRegistry
    from noether.ledger.models import Domain

    rows = []
    slugs = []
    for config in DomainRegistry.all():
        slugs.append(config.slug)
        row, _ = Domain.objects.update_or_create(
            slug=config.slug,
            defaults={"name": config.name, "version": config.version, "enabled": True},
        )
        rows.append(row)
    Domain.objects.exclude(slug__in=slugs).update(enabled=False)
    return rows


def instantiate_chart(*, ledger, config: DomainConfig, template: ChartTemplate) -> None:
    """Create default units and the chart template's account tree in a new ledger."""
    from noether.ledger.models import Account, Unit

    units = {}
    for unit_def in config.default_units:
        units[unit_def.symbol] = Unit.objects.create(
            ledger=ledger,
            symbol=unit_def.symbol,
            name=unit_def.name,
            precision=unit_def.precision,
        )
    created: dict[str, Account] = {}
    for node in template.nodes:
        segments = node.path.split("/")
        parent = None
        for depth in range(1, len(segments)):
            prefix = "/".join(segments[:depth])
            if prefix not in created:
                created[prefix] = Account.objects.create(
                    ledger=ledger,
                    parent=parent,
                    name=segments[depth - 1],
                    account_type=node.account_type,
                    unit=units[node.unit],
                    is_placeholder=True,
                )
            parent = created[prefix]
        if node.path not in created:
            created[node.path] = Account.objects.create(
                ledger=ledger,
                parent=parent,
                name=segments[-1],
                account_type=node.account_type,
                unit=units[node.unit],
                is_placeholder=node.placeholder,
            )
