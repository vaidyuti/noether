from rest_framework_nested.routers import NestedSimpleRouter, SimpleRouter

from noether.ledger.api.accounts import AccountViewSet
from noether.ledger.api.domains import DomainViewSet
from noether.ledger.api.ledgers import LedgerViewSet
from noether.ledger.api.members import LedgerUserViewSet
from noether.ledger.api.prices import UnitPriceViewSet
from noether.ledger.api.roles import RoleViewSet
from noether.ledger.api.transactions import TransactionViewSet
from noether.ledger.api.units import UnitViewSet

router = SimpleRouter(use_regex_path=False)
router.register("domains", DomainViewSet, basename="domain")
router.register("ledgers", LedgerViewSet, basename="ledger")
router.register("roles", RoleViewSet, basename="role")

ledger_router = NestedSimpleRouter(router, "ledgers", lookup="ledger")
ledger_router.register("members", LedgerUserViewSet, basename="ledger-members")
ledger_router.register("units", UnitViewSet, basename="ledger-units")
ledger_router.register("accounts", AccountViewSet, basename="ledger-accounts")
ledger_router.register("transactions", TransactionViewSet, basename="ledger-transactions")
ledger_router.register("prices", UnitPriceViewSet, basename="ledger-prices")

urlpatterns = router.urls + ledger_router.urls
