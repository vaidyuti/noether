from noether.domains.config import DomainConfig, DomainConfigError


def _identical(existing: DomainConfig, incoming: DomainConfig) -> bool:
    if existing is incoming:
        return True
    return (
        (
            existing.slug,
            existing.name,
            existing.version,
            existing.account_types,
            existing.default_units,
            existing.chart_templates,
            existing.urls,
        )
        == (
            incoming.slug,
            incoming.name,
            incoming.version,
            incoming.account_types,
            incoming.default_units,
            incoming.chart_templates,
            incoming.urls,
        )
        and [type(v) for v in existing.validators] == [type(v) for v in incoming.validators]
        and type(existing.valuation) is type(incoming.valuation)
    )


class DomainRegistry:
    _configs: dict[str, DomainConfig] = {}

    @classmethod
    def register(cls, config: DomainConfig) -> None:
        config.validate()
        existing = cls._configs.get(config.slug)
        if existing is not None:
            if _identical(existing, config):
                return
            raise DomainConfigError(f"conflicting re-registration of domain {config.slug!r}")
        cls._configs[config.slug] = config

    @classmethod
    def get(cls, slug: str) -> DomainConfig:
        if slug not in cls._configs:
            raise DomainConfigError(f"domain {slug!r} is not registered")
        return cls._configs[slug]

    @classmethod
    def all(cls) -> list[DomainConfig]:
        return list(cls._configs.values())

    @classmethod
    def unregister(cls, slug: str) -> None:
        """Test helper: remove a registered domain."""
        cls._configs.pop(slug, None)
