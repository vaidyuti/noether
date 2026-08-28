"""Dynamic plug URL mounting: every registered domain's urlconf under its slug."""

from django.urls import include, path

from noether.domains.registry import DomainRegistry

urlpatterns = [
    path(f"{config.slug}/", include(config.urls)) for config in DomainRegistry.all() if config.urls
]
