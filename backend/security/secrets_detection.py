"""
Secret detection and redaction, run on every chunk BEFORE it's embedded
or written to the vector store — a leaked AWS key or API token in a
document should never make it into an embeddable, searchable artifact.
"""
import logging
import re

logger = logging.getLogger("neuroflow.security.secrets_detection")

REDACTED = "[REDACTED]"

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_api_key", re.compile(
        r"""['"]?(?:api|secret|token|key|password)['"]?\s*[:=]\s*['"][A-Za-z0-9/+]{20,}['"]""",
        re.IGNORECASE,
    )),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
]


def scan_and_redact(text: str) -> tuple[str, list[dict]]:
    """Returns (redacted_text, findings). Each finding is
    {"event": "secret_redacted", "pattern_type": ...} — document_id is
    attached by the caller, which knows it; this function is pure text
    in, text out, so it's trivially unit-testable without a DB."""
    if not text:
        return text, []

    redacted = text
    findings: list[dict] = []
    for pattern_type, pattern in _PATTERNS:
        def _replace(match: re.Match, pattern_type=pattern_type) -> str:
            findings.append({"event": "secret_redacted", "pattern_type": pattern_type})
            logger.warning("secret redacted: pattern_type=%s", pattern_type)
            return REDACTED

        redacted = pattern.sub(_replace, redacted)

    return redacted, findings
