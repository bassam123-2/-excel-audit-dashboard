"""Site-wide utility views."""

from django.http import HttpResponse

from config.robots import ROBOTS_TXT


def robots_txt(_request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain; charset=utf-8")
