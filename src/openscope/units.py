"""Physical unit handling.

Every unit belongs to a *dimension* and has a factor that converts it to the
dimension's base unit. Conversions are only allowed within a dimension, so a
factor expressed "per kWh" can never silently be applied to litres.

Currencies are deliberately modelled as separate dimensions (``currency:USD``,
``currency:EUR`` …). Converting money requires exchange rates *and* inflation
adjustment to the factor's base year, which is a modelling decision, not a unit
conversion — so it is never done implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from openscope.errors import UnitError


@dataclass(frozen=True, slots=True)
class Unit:
    symbol: str
    dimension: str
    to_base: float  # multiply a quantity in this unit by to_base to get base units


_UNITS: dict[str, Unit] = {}


def _register(dimension: str, base: str, table: dict[str, float]) -> None:
    for symbol, factor in {base: 1.0, **table}.items():
        _UNITS[symbol.lower()] = Unit(symbol, dimension, factor)


# Energy — base kWh
_register(
    "energy",
    "kWh",
    {
        "Wh": 1e-3,
        "MWh": 1e3,
        "GWh": 1e6,
        "J": 1 / 3.6e6,
        "kJ": 1 / 3.6e3,
        "MJ": 1 / 3.6,
        "GJ": 1e3 / 3.6,
        "therm": 29.307107,  # US therm
        "MMBtu": 293.07107,
        "Btu": 293.07107e-6,
    },
)

# Volume — base litre
_register(
    "volume",
    "L",
    {
        "mL": 1e-3,
        "m3": 1e3,
        "gal": 3.785411784,  # US gallon
        "gal_us": 3.785411784,
        "gal_imp": 4.54609,
        "bbl": 158.987294928,  # US oil barrel
        "scf": 28.316846592,  # standard cubic foot
        "ccf": 2831.6846592,
    },
)

# Mass — base kg
_register(
    "mass",
    "kg",
    {
        "g": 1e-3,
        "t": 1e3,
        "tonne": 1e3,
        "lb": 0.45359237,
        "short_ton": 907.18474,
        "long_ton": 1016.0469088,
    },
)

# Distance — base km
_register("distance", "km", {"m": 1e-3, "mi": 1.609344})

# Freight — base tonne-km
_register("freight", "tkm", {"ton_mile": 1.459972})  # short ton-mile

# Passenger transport — base passenger-km
_register("passenger_distance", "pkm", {"passenger_mile": 1.609344})

# Count-based activity (e.g. hotel nights, units purchased)
_register("count", "unit", {"night": 1.0, "item": 1.0})

_CURRENCIES = {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "CNY", "INR", "SEK", "NOK", "DKK"}


def get_unit(symbol: str) -> Unit:
    """Look up a unit by symbol (case-insensitive). Currencies are ISO 4217 codes."""
    key = symbol.strip()
    if key.upper() in _CURRENCIES:
        code = key.upper()
        return Unit(code, f"currency:{code}", 1.0)
    try:
        return _UNITS[key.lower()]
    except KeyError:
        raise UnitError(f"Unknown unit '{symbol}'") from None


def convert(quantity: float, from_unit: str, to_unit: str) -> float:
    """Convert ``quantity`` between two units of the same dimension."""
    src, dst = get_unit(from_unit), get_unit(to_unit)
    if src.dimension != dst.dimension:
        if src.dimension.startswith("currency:") and dst.dimension.startswith("currency:"):
            raise UnitError(
                f"Cannot convert {src.symbol} to {dst.symbol} implicitly: currency conversion "
                "requires an exchange rate and inflation adjustment to the factor's base year."
            )
        raise UnitError(
            f"Incompatible units: '{from_unit}' ({src.dimension}) vs '{to_unit}' ({dst.dimension})"
        )
    return quantity * src.to_base / dst.to_base


def is_compatible(a: str, b: str) -> bool:
    return get_unit(a).dimension == get_unit(b).dimension
