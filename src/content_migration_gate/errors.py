"""Typed dependency fails so API handlers can distinguish failure classes"""


class DependencyError(Exception):
    """Base class for a failed interaction with another service."""


class DependencyUnavailable(DependencyError):
    """A downstream service could not be reached within the request timeout."""


class DependencyRejected(DependencyError):
    """A downstream service returned an unexpected non-success status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class DependencyContractViolation(DependencyError):
    """A downstream service returned a response outside the agreed contract."""


class DraftNotFound(Exception):
    """The requested content draft does not exist."""


class PublicationConflict(Exception):
    """The requested slug is already owned by a different published draft."""
