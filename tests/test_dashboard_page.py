"""Step 27: the dashboard web page. It must hold no data, no keys, and run no outside code."""
import re


def page(client):
    return client.get("/dashboard")


def test_the_page_opens_without_a_key_and_contains_no_company_data(client, world):
    r = page(client)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    for secret in ("Smile Dental", "ShopEasy", "Asha", "+9190"):
        assert secret not in r.text
    assert not re.search(r"(stf|jrv)_[A-Za-z0-9_\-]{8,}", r.text)      # no real-looking key (the box only hints "stf_...")


def test_security_headers_and_a_fresh_nonce_each_time(client):
    first, second = page(client), page(client)
    csp = first.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([\w\-]+)'", csp).group(1)
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert f'nonce="{nonce}"' in first.text and first.text.count('nonce="') == 2   # one style, one script
    assert nonce not in second.headers["content-security-policy"]                     # never reused
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-frame-options"] == "DENY" and first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["referrer-policy"] == "no-referrer"


def test_the_page_script_never_stores_the_key_or_inserts_raw_html(client):
    html = page(client).text
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "innerHTML", "outerHTML",
                      "insertAdjacentHTML", "document.write", "eval(", "new Function", "location.search",
                      "location.hash"):
        assert forbidden not in html, forbidden
    assert re.findall(r"""(?:src|href)\s*=\s*["']https?://""", html) == []        # no outside files
    script = html.split("<script", 1)[1].replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in script and "https://" not in script


def test_the_page_is_not_in_the_api_docs_and_the_api_still_needs_keys(client, world):
    assert "/dashboard" not in client.get("/openapi.json").json()["paths"]
    assert client.get("/staff/dashboard").status_code == 401
