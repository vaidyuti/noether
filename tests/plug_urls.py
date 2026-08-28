"""Tiny plug urlconf used by ADR-0011 mounting tests."""

from django.http import JsonResponse
from django.urls import path


def ping(request):
    return JsonResponse({"ok": True})


urlpatterns = [path("ping/", ping, name="plugtest-ping")]
