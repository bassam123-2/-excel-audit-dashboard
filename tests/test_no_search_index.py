import pytest
from django.test import Client, RequestFactory

from config.middleware import NoSearchIndexMiddleware
from config.views import robots_txt
from site_robots import ROBOTS_HTTP_HEADER_VALUE, ROBOTS_TXT


def test_no_search_index_middleware_sets_header():
    factory = RequestFactory()
    request = factory.get("/dashboards/")

    def get_response(_req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    response = NoSearchIndexMiddleware(get_response)(request)
    assert response["X-Robots-Tag"] == ROBOTS_HTTP_HEADER_VALUE


@pytest.mark.django_db
def test_robots_txt_disallows_all():
    client = Client()
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.content.decode() == ROBOTS_TXT
    assert response["X-Robots-Tag"] == ROBOTS_HTTP_HEADER_VALUE


def test_robots_txt_view():
    from django.http import HttpRequest

    response = robots_txt(HttpRequest())
    assert response.content.decode() == ROBOTS_TXT
