"""Typed exceptions shared across the application."""


class AideError(Exception):
    """Base class for all aide errors."""


class ConfigError(AideError):
    """Configuration is missing or invalid."""


class ProviderError(AideError):
    """The LLM provider failed (auth, timeout, bad request, transport)."""


class AuthenticationError(ProviderError):
    """The provider rejected our credentials."""


class RateLimitError(ProviderError):
    """The provider throttled the request (HTTP 429)."""


class ServerError(ProviderError):
    """The provider returned a transient server-side error (5xx)."""


class TimeoutError_(ProviderError):
    """The provider request timed out."""


class FileToolError(AideError):
    """Base class for file-tool failures."""


class WorkspaceError(FileToolError):
    """Path is outside the workspace root or deny-listed."""


class FileNotFound_(FileToolError):
    """The target file does not exist."""


class AmbiguousMatchError(FileToolError):
    """The edit old_string matched multiple times; caller must disambiguate."""


class NoMatchError(FileToolError):
    """The edit old_string did not match anywhere in the file."""
