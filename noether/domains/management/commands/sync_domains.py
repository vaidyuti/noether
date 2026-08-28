from django.core.management.base import BaseCommand

from noether.domains.services import sync_domain_rows


class Command(BaseCommand):
    help = "Mirror registered DomainConfigs into the Domain table"

    def handle(self, *args, **options):
        rows = sync_domain_rows()
        self.stdout.write(f"Synced {len(rows)} domain(s)")
