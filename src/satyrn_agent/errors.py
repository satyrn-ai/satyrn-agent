"""Satyrn-specific configuration and DFlash failures."""


class SatyrnError(Exception):
    """Base class for downstream agent errors."""


class ConfigurationError(SatyrnError, ValueError):
    """A public configuration value is invalid or inconsistent."""


class DFlashUnavailable(SatyrnError):
    """The requested DFlash policy cannot be satisfied."""


class DFlashError(SatyrnError):
    """A native DFlash operation failed."""

    def __init__(self, operation: str, message: str) -> None:
        self.operation = operation
        super().__init__(f"{operation}: {message}")
