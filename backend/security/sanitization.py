"""
Input validation and sanitization applied at every API boundary that
accepts user text, URLs, or files.
"""
import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import bleach

logger = logging.getLogger("neuroflow.security.sanitization")

MAX_QUERY_LENGTH = 5000
MAX_PIPELINE_NAME_LENGTH = 100

URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# File magic bytes (signatures) for the file types NeuroFlow ingests —
# checked against the file's actual first bytes, not its extension or
# declared Content-Type, so a renamed executable can't pass as a PDF.
MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],  # docx/pptx/xlsx are all zip containers
    "pptx": [b"PK\x03\x04"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "webp": [b"RIFF"],  # followed by size + "WEBP", checked separately below
    "csv": [],  # plain text, no reliable magic signature — skipped
}

# Signatures that indicate an executable/script masquerading as a document
# — an explicit blocklist catches the "renamed .exe" attack even for file
# types (like csv) that have no magic signature of their own to check.
DANGEROUS_SIGNATURES: list[bytes] = [
    b"MZ",  # Windows PE executable
    b"\x7fELF",  # Linux ELF executable
    b"#!/",  # shebang script
    b"\xca\xfe\xba\xbe",  # Mach-O / Java class (fat binary)
]


class ValidationError(Exception):
    pass


def clean_text(text: str) -> str:
    """Strips all HTML tags — NeuroFlow's UI renders query/answer text as
    plain text, and stored HTML is both a stored-XSS risk if ever
    rendered elsewhere and irrelevant noise for embedding/retrieval."""
    return bleach.clean(text, tags=[], strip=True)


def validate_query_length(text: str) -> None:
    if len(text) > MAX_QUERY_LENGTH:
        raise ValidationError(f"query exceeds max length of {MAX_QUERY_LENGTH} characters")


def validate_pipeline_name_length(name: str) -> None:
    if len(name) > MAX_PIPELINE_NAME_LENGTH:
        raise ValidationError(f"pipeline name exceeds max length of {MAX_PIPELINE_NAME_LENGTH} characters")


# ── SSRF protection ──────────────────────────────────────────────────
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, incl. cloud metadata endpoints
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_address(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_url_for_ssrf(url: str) -> None:
    """Blocks localhost and private IP ranges — both the literal form
    (http://192.168.1.1) and a hostname that RESOLVES to one (e.g. a DNS
    entry pointing at an internal address), which is the more realistic
    SSRF vector since attackers rarely hardcode a raw private IP."""
    if not URL_SCHEME_RE.match(url):
        raise ValidationError("URL must start with http:// or https://")

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("URL has no hostname")

    if hostname.lower() in ("localhost", "localhost.localdomain") or hostname.lower().endswith(".local"):
        raise ValidationError("URLs targeting localhost are not allowed")

    if _is_private_address(hostname):
        raise ValidationError(f"URLs targeting private IP ranges are not allowed ({hostname})")

    try:
        resolved_ips = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return  # can't resolve — let the actual fetch fail naturally later, not our job to guess
    for ip in resolved_ips:
        if _is_private_address(ip):
            raise ValidationError(f"URL hostname '{hostname}' resolves to a private IP ({ip}), blocked")


# ── file type / magic byte validation ───────────────────────────────
def validate_file_signature(file_bytes: bytes, declared_type: str) -> None:
    """Checks the file's actual leading bytes against known signatures
    for `declared_type` (derived from the upload's extension) — an
    extension/MIME type alone is just a label the uploader chose, not
    proof of what the bytes actually are."""
    if not file_bytes:
        raise ValidationError("empty file")

    for dangerous in DANGEROUS_SIGNATURES:
        if file_bytes.startswith(dangerous):
            raise ValidationError(f"file content signature indicates an executable/script, not a {declared_type}")

    if declared_type == "webp":
        if not (file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"):
            raise ValidationError("file does not match WEBP signature")
        return

    signatures = MAGIC_SIGNATURES.get(declared_type)
    if not signatures:
        return  # no reliable signature for this type (e.g. csv) — dangerous-signature check above still applies

    if not any(file_bytes.startswith(sig) for sig in signatures):
        raise ValidationError(f"file content does not match expected signature for {declared_type}")
