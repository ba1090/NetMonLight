"""Sito di presentazione sullo stesso dominio: / (e /en/, /de/, /fr/), dashboard su /dashboard."""
import pytest


@pytest.mark.parametrize("path,lang", [("/", "it"), ("/en/", "en"), ("/de/", "de"), ("/fr/", "fr")])
def test_sito_pages(client, path, lang):
    r = client.get(path)
    assert r.status_code == 200
    assert f'<html lang="{lang}"' in r.text
    assert r.headers["content-language"] == lang
    assert "Content-Security-Policy" in r.headers
    # i link portano alla dashboard e all'informativa di questo server, non a un'altra macchina
    assert "dashboard.netmonhome.net" not in r.text
    assert 'href="/dashboard"' in r.text and 'href="/privacy"' in r.text
    # il browser la conserva: alla seconda richiesta, 304
    assert client.get(path, headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_sito_no_slash_redirect(client):
    r = client.get("/en", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/en/"
    assert client.get("/xx/").status_code == 404


def test_dashboard_and_old_status(client):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "<title>" in r.text
    r = client.get("/status", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/dashboard"


def test_links_point_to_dashboard(client, server):
    assert client.get("/scarica-sonda", follow_redirects=False).headers["location"] == "/dashboard#scarica-sonda"
    robots = client.get("/robots.txt").text
    assert "Allow: /dashboard" in robots and "Disallow: /admin" in robots
    sm = client.get("/sitemap.xml").text
    for p in ("/</loc>", "/en/</loc>", "/de/</loc>", "/fr/</loc>", "/dashboard</loc>", "/privacy</loc>"):
        assert p in sm
