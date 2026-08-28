import re
from dataclasses import dataclass, field

VALID_SLUG = re.compile(r"^[a-z0-9-]{1,32}$")
VALID_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
VALID_NORMAL_BALANCES = ("debit", "credit")


class DomainConfigError(Exception):
    """Raised at startup when a DomainConfig is invalid."""


@dataclass(frozen=True)
class AccountTypeDef:
    name: str
    normal_balance: str


@dataclass(frozen=True)
class UnitDef:
    symbol: str
    name: str
    precision: int


@dataclass(frozen=True)
class ChartNode:
    path: str
    account_type: str
    unit: str
    placeholder: bool = False


@dataclass(frozen=True)
class ChartTemplate:
    name: str
    nodes: tuple[ChartNode, ...] | list[ChartNode] = field(default_factory=list)


@dataclass(frozen=True)
class DomainConfig:
    slug: str
    name: str
    version: str
    account_types: list[AccountTypeDef] = field(default_factory=list)
    default_units: list[UnitDef] = field(default_factory=list)
    chart_templates: list[ChartTemplate] = field(default_factory=list)
    validators: list = field(default_factory=list)
    valuation: object | None = None
    urls: str | None = None

    def validate(self) -> None:
        if not VALID_SLUG.match(self.slug):
            raise DomainConfigError(f"invalid domain slug: {self.slug!r}")
        if not VALID_SEMVER.match(self.version):
            raise DomainConfigError(f"invalid version {self.version!r} for domain {self.slug}")
        type_names = [t.name for t in self.account_types]
        if len(type_names) != len(set(type_names)):
            raise DomainConfigError(f"duplicate account type in domain {self.slug}")
        for t in self.account_types:
            if t.normal_balance not in VALID_NORMAL_BALANCES:
                raise DomainConfigError(
                    f"invalid normal_balance {t.normal_balance!r} for type {t.name}"
                )
        unit_symbols = {u.symbol for u in self.default_units}
        if len(unit_symbols) != len(self.default_units):
            raise DomainConfigError(f"duplicate unit symbol in domain {self.slug}")
        for u in self.default_units:
            if u.precision < 0 or u.precision > 10:
                raise DomainConfigError(f"unit {u.symbol} precision must be 0-10")
        template_names = [c.name for c in self.chart_templates]
        if len(template_names) != len(set(template_names)):
            raise DomainConfigError(f"duplicate chart template name in domain {self.slug}")
        for template in self.chart_templates:
            self._validate_template(template, set(type_names), unit_symbols)

    def _validate_template(self, template: ChartTemplate, types: set, units: set) -> None:
        for node in template.nodes:
            if node.account_type not in types:
                raise DomainConfigError(
                    f"chart node {node.path}: unknown account type {node.account_type!r}"
                )
            if node.unit not in units:
                raise DomainConfigError(f"chart node {node.path}: unknown unit {node.unit!r}")
