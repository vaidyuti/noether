from noether.domains.config import ChartTemplate, DomainConfig, DomainConfigError


def create_ledger(
    *, domain_slug: str, name: str, owner, chart_template=None, description="", slug=None
):
    """Create a ledger programmatically, mirroring the REST creation path."""
    from noether.domains.registry import DomainRegistry
    from noether.ledger.models import Domain, Ledger
    from noether.security.models import LedgerUser
    from noether.security.models import Role as RoleModel
    from noether.security.roles.role import OWNER_ROLE

    config = DomainRegistry.get(domain_slug)
    domain_row = Domain.objects.filter(slug=domain_slug).first()
    if domain_row is None:
        raise DomainConfigError(f"domain {domain_slug!r} is not synced")
    template = None
    if chart_template is not None:
        template = next((t for t in config.chart_templates if t.name == chart_template), None)
        if template is None:
            raise DomainConfigError(f"unknown chart template {chart_template!r}")
    ledger = Ledger.objects.create(
        domain=domain_row,
        name=name,
        slug=slug,
        description=description,
        created_by=owner,
        updated_by=owner,
    )
    if template is not None:
        instantiate_chart(ledger=ledger, config=config, template=template)
    owner_role = RoleModel.objects.get(name=OWNER_ROLE.name)
    LedgerUser.objects.create(ledger=ledger, user=owner, role=owner_role)
    return ledger


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
