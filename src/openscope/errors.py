class OpenScopeError(Exception):
    """Base class for all openscope errors."""


class UnitError(OpenScopeError):
    """Raised for unknown or incompatible units."""


class FactorError(OpenScopeError):
    """Raised when an emission factor is missing, malformed or not applicable."""


class GWPError(OpenScopeError):
    """Raised when a global warming potential is not available for a gas."""
