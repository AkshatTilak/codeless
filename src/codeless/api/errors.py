"""API error types for Codeless."""

from __future__ import annotations


class CodelessApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(CodelessApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(CodelessApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(CodelessApiError):
    """Raised for generic request or transport failures."""
