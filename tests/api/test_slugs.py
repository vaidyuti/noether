from django.core.exceptions import ValidationError as DjangoValidationError

from noether.ledger.models import Account, Ledger
from noether.ledger.models_base import (
    SLUG_MAX_LENGTH,
    generate_external_id,
    slug_or_uuid_filters,
    validate_slug,
)
from noether.ledger.tests.factories import AccountFactory, LedgerFactory, UnitFactory
from tests.api.base import NoetherAPITestCase


class SlugValidatorTests(NoetherAPITestCase):
    def test_valid_slugs(self):
        for value in ("a", "a1", "cash-in-hand", "cash_in_hand", "a" * SLUG_MAX_LENGTH):
            assert validate_slug(value) == value

    def test_too_long(self):
        with self.assertRaisesRegex(DjangoValidationError, "at most"):
            validate_slug("a" * (SLUG_MAX_LENGTH + 1))

    def test_invalid_shapes(self):
        for value in ("", "-lead", "trail-", "_lead", "trail_", "Upper", "has space", "a b", "é"):
            with self.assertRaisesRegex(DjangoValidationError, "lowercase"):
                validate_slug(value)

    def test_slug_or_uuid_filters(self):
        ext = generate_external_id()
        assert slug_or_uuid_filters(Ledger, str(ext)) == {"external_id": ext}
        assert slug_or_uuid_filters(Ledger, "my-ledger") == {"slug": "my-ledger"}
        from noether.ledger.models import Unit

        assert slug_or_uuid_filters(Unit, "not-a-uuid") is None


class SlugModelTests(NoetherAPITestCase):
    def test_null_slugs_do_not_collide(self):
        a = AccountFactory(ledger=self.ledger, unit=self.unit)
        b = AccountFactory(ledger=self.ledger, unit=self.unit)
        assert a.slug is None
        assert b.slug is None

    def test_duplicate_slug_in_same_ledger_rejected(self):
        AccountFactory(ledger=self.ledger, unit=self.unit, slug="cash")
        with self.assertRaisesRegex(DjangoValidationError, "already taken"):
            AccountFactory(ledger=self.ledger, unit=self.unit, slug="cash")

    def test_same_slug_allowed_in_different_ledgers(self):
        other = LedgerFactory(domain=self.ledger.domain)
        other_unit = UnitFactory(ledger=other)
        AccountFactory(ledger=self.ledger, unit=self.unit, slug="cash")
        acc = AccountFactory(ledger=other, unit=other_unit, slug="cash")
        assert acc.slug == "cash"

    def test_resaving_same_row_is_allowed(self):
        acc = AccountFactory(ledger=self.ledger, unit=self.unit, slug="cash")
        acc.name = "renamed"
        acc.save()
        assert Account.objects.get(pk=acc.pk).name == "renamed"

    def test_invalid_slug_rejected_at_model_level(self):
        with self.assertRaisesRegex(DjangoValidationError, "lowercase"):
            AccountFactory(ledger=self.ledger, unit=self.unit, slug="Bad Slug")

    def test_ledger_slug_globally_unique(self):
        LedgerFactory(domain=self.ledger.domain, slug="books")
        with self.assertRaisesRegex(DjangoValidationError, "already taken"):
            LedgerFactory(domain=self.ledger.domain, slug="books")


class SlugApiTests(NoetherAPITestCase):
    def _create_account(self, **extra):
        payload = {
            "name": "Cash",
            "account_type": "generic",
            "unit": str(self.unit.external_id),
        }
        payload.update(extra)
        return self.client.post(self.ledger_url("accounts/"), payload, format="json")

    def test_create_with_slug(self):
        response = self._create_account(slug="cash-in-hand")
        assert response.status_code == 201, response.content
        assert response.json()["slug"] == "cash-in-hand"

    def test_create_without_slug_is_null(self):
        response = self._create_account()
        assert response.status_code == 201, response.content
        assert response.json()["slug"] is None

    def test_create_with_invalid_slug_400(self):
        response = self._create_account(slug="Cash In Hand")
        assert response.status_code == 400, response.content

    def test_duplicate_slug_same_ledger_400(self):
        assert self._create_account(slug="cash").status_code == 201
        response = self._create_account(slug="cash")
        assert response.status_code == 400, response.content
        assert "already taken" in str(response.json())

    def test_retrieve_by_slug_and_uuid(self):
        created = self._create_account(slug="cash-in-hand").json()
        by_slug = self.client.get(self.ledger_url("accounts/cash-in-hand/"))
        by_uuid = self.client.get(self.ledger_url(f"accounts/{created['id']}/"))
        assert by_slug.status_code == 200
        assert by_uuid.status_code == 200
        assert by_slug.json() == by_uuid.json()

    def test_retrieve_by_unknown_slug_404(self):
        assert self.client.get(self.ledger_url("accounts/nope/")).status_code == 404

    def test_retrieve_by_unknown_uuid_404(self):
        url = self.ledger_url(f"accounts/{generate_external_id()}/")
        assert self.client.get(url).status_code == 404

    def test_slug_that_looks_like_a_uuid_is_treated_as_uuid(self):
        """A slug-shaped value that parses as a UUID always addresses external_id."""
        looks_like = str(generate_external_id())
        acc = AccountFactory(ledger=self.ledger, unit=self.unit, slug=looks_like)
        assert acc.slug == looks_like
        response = self.client.get(self.ledger_url(f"accounts/{looks_like}/"))
        assert response.status_code == 404

    def test_patch_slug(self):
        self._create_account(slug="cash").json()
        response = self.client.patch(
            self.ledger_url("accounts/cash/"), {"slug": "petty-cash"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert response.json()["slug"] == "petty-cash"
        assert self.client.get(self.ledger_url("accounts/cash/")).status_code == 404
        assert self.client.get(self.ledger_url("accounts/petty-cash/")).status_code == 200

    def test_patch_to_taken_slug_400(self):
        self._create_account(slug="cash")
        self._create_account(slug="bank")
        response = self.client.patch(
            self.ledger_url("accounts/bank/"), {"slug": "cash"}, format="json"
        )
        assert response.status_code == 400, response.content

    def test_unslugged_model_lookup_by_non_uuid_404(self):
        assert self.client.get(self.ledger_url("units/not-a-uuid/")).status_code == 404


class LedgerSlugApiTests(NoetherAPITestCase):
    def test_create_ledger_with_slug_and_address_by_it(self):
        response = self.client.post(
            "/api/v1/ledgers/",
            {"domain": "testdomain", "name": "Books", "slug": "books"},
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.json()["slug"] == "books"
        assert self.client.get("/api/v1/ledgers/books/").status_code == 200

    def test_nested_route_addressable_by_ledger_slug(self):
        self.ledger.slug = "main"
        self.ledger.save()
        response = self.client.get("/api/v1/ledgers/main/accounts/")
        assert response.status_code == 200, response.content

    def test_unknown_ledger_slug_404(self):
        assert self.client.get("/api/v1/ledgers/nope/accounts/").status_code == 404
