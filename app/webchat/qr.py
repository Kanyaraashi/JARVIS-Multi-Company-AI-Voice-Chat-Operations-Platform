"""QR codes for each company's chat page, made and revoked like staff keys.

    python -m app.webchat.qr new smile-dental              makes a NEW code and its QR files; older codes keep working
    python -m app.webchat.qr new smile-dental --replace    makes a new code and kills every older one (lost or leaked QR)
    python -m app.webchat.qr show smile-dental             remakes the QR files for the codes the company has now
    python -m app.webchat.qr revoke smile-dental           kills every code of the company
    python -m app.webchat.qr list                          shows each company's codes

A code is a random string, so the QR opens PUBLIC_BASE_URL/c/<code> and the company name is not in the address.
It is kept in .env as CHAT_CODE_<COMPANY> (several codes separated by commas, for example one per reception desk).
Printing a code on a wall is different from a secret key: anyone who can see the poster can chat. That is why codes
can be replaced at any time, and why the chat has its own limits. After any change, rebuild .env.chat and restart
the chat service (see DEPLOYMENT.md section 10). The picture is drawn on this server; nothing goes to an outside QR site.
"""
import io
import os
import pathlib
import re
import secrets
import sys

import segno

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
CODE = re.compile(r"^[A-Za-z0-9_-]{12,64}$")


def env_name(slug: str) -> str:
    return "CHAT_CODE_" + slug.upper().replace("-", "_")


def new_code() -> str:
    return secrets.token_urlsafe(9)          # 12 characters, 72 bits


def public_url(code: str, base: str = "") -> str:
    base = (base or os.getenv("PUBLIC_BASE_URL", "")).strip().rstrip("/")
    if not base.startswith(("https://", "http://")):
        raise ValueError("Set PUBLIC_BASE_URL in .env, for example https://jarvis.example.com")
    if not CODE.match(code or ""):
        raise ValueError("That chat code is not valid.")
    return f"{base}/c/{code}"


def make(url: str):
    return segno.make(url, error="m")


def svg_bytes(url: str, scale: int = 10) -> bytes:
    buf = io.BytesIO()
    make(url).save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True, dark="#000000", light="#ffffff")
    return buf.getvalue()


def png_bytes(url: str, scale: int = 14) -> bytes:
    buf = io.BytesIO()
    make(url).save(buf, kind="png", scale=scale, border=3, dark="#000000", light="#ffffff")
    return buf.getvalue()


POSTER = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Poster: __NAME__</title>
<style nonce="__NONCE__">
:root{--ink:#14171f;--mute:#5f6675;--line:#dde0e6;--accent:#0f766e}
*{box-sizing:border-box}
body{margin:0;background:#eef0f3;color:var(--ink);font:18px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.sheet{width:min(210mm,100%);min-height:297mm;margin:0 auto;background:#fff;padding:22mm 18mm;display:flex;flex-direction:column;align-items:center;text-align:center}
.brand{font-size:22px;font-weight:700;margin:0 0 28mm}
h1{font-size:54px;line-height:1.08;letter-spacing:-.025em;margin:0 0 10px;max-width:14ch}
.lead{color:var(--mute);font-size:22px;margin:0 0 14mm;max-width:28ch}
.qr{width:100mm;height:100mm;padding:6mm;border:2px solid var(--ink);border-radius:8mm;display:flex}
.qr svg{width:100%;height:100%}
.how{margin:12mm 0 0;font-size:24px;font-weight:600}
.small{margin-top:auto;padding-top:10mm;color:var(--mute);font-size:15px;overflow-wrap:anywhere}
.bar{width:min(210mm,100%);margin:0 auto;padding:12px 16px;display:flex;gap:12px;align-items:center;justify-content:center}
.bar button{padding:10px 18px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:600 16px system-ui,sans-serif;cursor:pointer}
@media print{body{background:#fff}.bar{display:none}.sheet{width:auto;min-height:0;height:297mm;padding:22mm 18mm}@page{size:A4;margin:0}}
</style>
</head>
<body>
<div class="bar"><button type="button" id="print">Print this poster</button></div>
<main class="sheet">
  <p class="brand">__NAME__</p>
  <h1>Book a visit or ask us anything</h1>
  <p class="lead">Scan the code with your phone camera and chat with us. No app needed.</p>
  <div class="qr" role="img" aria-label="QR code to open the chat">__SVG__</div>
  <p class="how">Point your camera here</p>
  <p class="small">Or type this address: __URL__</p>
</main>
<script nonce="__NONCE__">document.getElementById("print").addEventListener("click", function () { window.print(); });</script>
</body>
</html>
"""


def read_env(path: pathlib.Path) -> dict:
    from dotenv import dotenv_values
    return dict(dotenv_values(path)) if path.exists() else {}


def codes_of(values: dict, slug: str) -> list:
    return [c.strip() for c in (values.get(env_name(slug)) or "").split(",") if CODE.match(c.strip())]


def write_codes(path: pathlib.Path, slug: str, codes: list) -> None:
    """Sets (or removes) one CHAT_CODE_ line and leaves every other line of .env exactly as it was."""
    name = env_name(slug)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.startswith(name + "=")]
    if codes:
        lines.append(f"{name}={','.join(codes)}")
    path.write_text("\n".join(lines) + "\n")


def write_files(slug: str, code: str, base: str, folder: pathlib.Path) -> str:
    url = public_url(code, base)
    out = folder / "qr"
    out.mkdir(exist_ok=True)
    stem = f"{slug}-{code[:4]}"
    (out / f"{stem}.svg").write_bytes(svg_bytes(url))
    (out / f"{stem}.png").write_bytes(png_bytes(url))
    print(f"  {url}\n    files: qr/{stem}.svg (print at any size) and qr/{stem}.png\n    poster: {url}/poster")
    return url


def main(argv=None, folder: pathlib.Path = pathlib.Path(".")) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "Usage: python -m app.webchat.qr  new <company> [--replace] | show <company> | revoke <company> | list"
    if not argv or argv[0] not in ("new", "show", "revoke", "list"):
        print(usage)
        return 1
    env_path = folder / ".env"
    values = read_env(env_path)
    action = argv[0]

    if action == "list":
        found = False
        for key in sorted(values):
            if key.startswith("CHAT_CODE_"):
                found = True
                slug = key[len("CHAT_CODE_"):].lower().replace("_", "-")
                print(f"{slug}: {len(codes_of(values, slug))} active code(s)")
        if not found:
            print("No chat codes yet. Make one with: python -m app.webchat.qr new <company>")
        return 0

    if len(argv) < 2 or not SLUG.match(argv[1]):
        print(usage)
        return 1
    slug = argv[1]
    key_name = "JARVIS_KEY_" + slug.upper().replace("-", "_")
    base = values.get("PUBLIC_BASE_URL") or os.getenv("PUBLIC_BASE_URL", "")

    if action in ("new", "show") and not values.get(key_name):
        print(f"No company '{slug}': {key_name} is missing in .env. Set the company up first.")
        return 1

    try:
        if action == "new":
            replace = "--replace" in argv
            codes = [] if replace else codes_of(values, slug)
            code = new_code()
            codes.append(code)
            public_url(code, base)                                  # fail before changing anything
            write_codes(env_path, slug, codes)
            print(f"Made a new chat code for {slug}" + (" and revoked all older ones." if replace else ". Older codes still work."))
            write_files(slug, code, base, folder)
        elif action == "show":
            codes = codes_of(values, slug)
            if not codes:
                print(f"{slug} has no chat code yet. Make one with: python -m app.webchat.qr new {slug}")
                return 1
            for code in codes:
                write_files(slug, code, base, folder)
        else:
            had = codes_of(values, slug)
            write_codes(env_path, slug, [])
            print(f"Revoked {len(had)} code(s) of {slug}. Their QR codes stop working after the chat service restarts.")
            return 0
    except ValueError as exc:
        print(exc)
        return 1

    print("Next: rebuild .env.chat and restart the chat service so the change takes effect (DEPLOYMENT.md section 10).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
