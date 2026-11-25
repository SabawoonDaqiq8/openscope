import pytest

from openscope import units
from openscope.errors import UnitError


@pytest.mark.parametrize(
    ("qty", "src", "dst", "expected"),
    [
        (1, "MWh", "kWh", 1000),
        (3.6, "MJ", "kWh", 1),
        (1, "MMBtu", "therm", 10),
        (1, "GJ", "MMBtu", 0.947817),
        (1, "gal", "L", 3.785411784),
        (1, "t", "kg", 1000),
        (1, "mi", "km", 1.609344),
        (100, "USD", "usd", 100),
    ],
)
def test_conversions(qty: float, src: str, dst: str, expected: float) -> None:
    assert units.convert(qty, src, dst) == pytest.approx(expected, rel=1e-5)


def test_incompatible_dimensions() -> None:
    with pytest.raises(UnitError, match="Incompatible"):
        units.convert(1, "kWh", "L")


def test_currency_never_implicitly_converted() -> None:
    with pytest.raises(UnitError, match="exchange rate"):
        units.convert(1, "EUR", "USD")


def test_unknown_unit() -> None:
    with pytest.raises(UnitError, match="Unknown unit"):
        units.get_unit("furlong")
