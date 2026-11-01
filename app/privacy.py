"""Keeps personal data and secrets out of log files."""
import logging
import re

PHONE = re.compile(r"(?:\+|%2[Bb])?\d{10,15}\b|\+\d{1,3}[ \-]?\d[\d \-]{6,}\d")
EMAIL = re.compile(r"([A-Za-z0-9._+\-])[A-Za-z0-9._+\-]*@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
SECRET_KEY = re.compile(r"\b(jrv|stf)_[A-Za-z0-9_\-]{6,}")


def _mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    return f"[phone ***{digits[-2:]}]"


def redact(text: str) -> str:
    """Hides phone numbers (keeps the last 2 digits), email addresses and API keys."""
    text = SECRET_KEY.sub(lambda m: f"{m.group(1)}_[hidden]", text)
    text = EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return PHONE.sub(_mask_phone, text)


def mask_email(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


_installed = False


def install_log_redaction() -> None:
    """Every log line from now on is cleaned before it is written anywhere."""
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return record

    logging.setLogRecordFactory(factory)
