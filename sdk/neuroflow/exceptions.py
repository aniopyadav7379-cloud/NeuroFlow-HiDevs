"""Exception types raised by NeuroFlowClient.

These wrap httpx errors so callers can catch SDK-specific exceptions instead
of reaching into httpx internals, and so timeout vs. transient-vs-permanent
failure vs. ingestion failure are all distinguishable.
"""

from __future__ import annotations

import httpx


class NeuroFlowError(Exception):
    """Base class for all NeuroFlow SDK errors."""


class NeuroFlowAPIError(NeuroFlowError):
    """The API returned an error response (after any applicable retries)."""

    def __init__(self, message: str, response: httpx.Response | None = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response is not None else None


class NeuroFlowTimeoutError(NeuroFlowError):
    """A client-side operation (e.g. polling) exceeded its configured timeout."""


class IngestionFailedError(NeuroFlowError):
    """The backend reported that ingestion for a document failed."""

    def __init__(self, document_id: str, detail: str | None = None):
        self.document_id = document_id
        self.detail = detail
        msg = f"Ingestion failed for document {document_id}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
