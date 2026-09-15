import re

# AWS access keys: AKIA[0-9A-Z]{16}
# Generic API keys: ['"]?(?:api|secret|token|key|password)['"]?\s*[:=]\s*['"][A-Za-z0-9/+]{20,}['"]
# Private key PEM headers: -----BEGIN [A-Z\s]+ PRIVATE KEY-----
# JWT tokens: three Base64 segments separated by dots

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "generic_api_key": re.compile(
        r"['\"]?(?:api|secret|token|key|password)['\"]?\s*[:=]\s*['\"][A-Za-z0-9/+]{20,}['\"]",
        re.IGNORECASE,
    ),
    "pem_private_key": re.compile(r"-----BEGIN [A-Z\s]+ PRIVATE KEY-----"),
    "jwt_token": re.compile(r"ey[a-zA-Z0-9_-]+\.ey[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
}


def scan_and_redact_secrets(text: str, document_id: str) -> tuple[str, list]:  # type: ignore
    """
    Scans for secrets, redacts them, and returns the redacted text and a list of logged events.
    """
    if not text:
        return text, []

    events = []
    redacted_text = text

    for pattern_type, pattern in SECRET_PATTERNS.items():
        if pattern.search(redacted_text):
            events.append(
                {
                    "event": "secret_redacted",
                    "document_id": str(document_id),
                    "pattern_type": pattern_type,
                }
            )
            redacted_text = pattern.sub("[REDACTED]", redacted_text)

    return redacted_text, events
