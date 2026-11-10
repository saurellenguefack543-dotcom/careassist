"""Pages publiques, contact, sitemap."""
from app import config


PAGES = ["/", "/fonctionnalites", "/specialites", "/tarifs", "/demo", "/faq", "/contact", "/cabinets"]


def test_public_pages_and_contact(client):
    assert config.CONTACT_EMAIL == "saurellenguefack543@gmail.com"
    assert config.CONTACT_PHONE == "06 05 50 85 42"
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.text
        assert "contact@getcareassist.com" not in body
        if path in ("/", "/contact", "/faq"):
            assert "saurellenguefack543@gmail.com" in body
            assert "06 05 50 85 42" in body
            assert "tel:+33605508542" in body


def test_form_placeholders_are_not_owner_gmail(client):
    contact = client.get("/contact").text
    assert "cabinet@exemple.fr" in contact
    assert 'placeholder="saurellenguefack543@gmail.com"' not in contact


def test_sitemap_lists_public_pages(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    text = r.text
    for path in ("/", "/fonctionnalites", "/specialites", "/tarifs", "/demo", "/faq", "/contact", "/cabinets"):
        assert f"https://getcareassist.com{path if path != '/' else '/'}" in text or f"getcareassist.com{path}" in text


def test_espace_and_admin_still_served(client):
    assert client.get("/espace").status_code == 200
    assert client.get("/admin").status_code == 200
