from noether.domains.config import DomainConfig, DomainConfigError


class DomainRegistry:
    _configs: dict[str, DomainConfig] = {}

    @classmethod
    def register(cls, config: DomainConfig) -> None:
        config.validate()
        if config.slug in cls._configs:
            raise DomainConfigError(f"domain {config.slug!r} already registered")
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
