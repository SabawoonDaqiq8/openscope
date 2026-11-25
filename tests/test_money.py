from pathlib import Path

import pytest

from openscope import (
    ActivityRecord,
    CalculationMethod,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    Inventory,
    Scope,
    Scope2Method,
    Scope3Category,
)
from openscope.money import FXTable, PriceIndex, SpendNormalisationError, SpendNormaliser

# Round numbers for testing only — not real exchange rates or price indices.
FX = FXTable({(2025, "EUR", "USD"): 1.10})
PRICES = PriceIndex({("USD", 2022): 100.0, ("USD", 2025): 110.0})

FACTOR = EmissionFactor(
    factor_id="SPEND-USD-2022",
    name="Test spend factor",
    activity_unit="USD",
    co2e_kg=0.5,
    year=2022,
    source="test",
)


def spend(**kw: object) -> ActivityRecord:
    base: dict[str, object] = {
        "activity_id": "s",
        "quantity": 1000,
        "unit": "EUR",
        "scope": Scope.SCOPE_3,
        "scope3_category": Scope3Category.PURCHASED_GOODS_AND_SERVICES,
        "method": CalculationMethod.SPEND_BASED,
        "price_year": 2025,
    }
    return ActivityRecord.model_validate(base | kw)


def test_fx_inverse_and_identity() -> None:
    assert FX.rate(2025, "USD", "EUR") == pytest.approx(1 / 1.10)
    assert FX.rate(2025, "GBP", "gbp") == 1.0
    with pytest.raises(SpendNormalisationError):
        FX.rate(2024, "EUR", "USD")


def test_normalise_converts_then_deflates() -> None:
    qty, trace = SpendNormaliser(FX, PRICES).normalise(1000, "EUR", 2025, "USD", 2022)
    assert qty == pytest.approx(1000 * 1.10 * 100 / 110)
    assert len(trace) == 2


def test_engine_applies_normalisation() -> None:
    calc = Calculator(FactorRegistry(), spend_normaliser=SpendNormaliser(FX, PRICES))
    r = calc.calculate(spend(), FACTOR)
    assert r.co2e_kg == pytest.approx(1000 * 1.10 * 100 / 110 * 0.5)
    assert any(t.startswith("FX:") for t in r.trace)
    assert any(t.startswith("Price year:") for t in r.trace)


def test_currency_mismatch_without_normaliser_is_error() -> None:
    with pytest.raises(SpendNormalisationError, match="exchange rates"):
        Calculator(FactorRegistry()).calculate(spend(), FACTOR)


def test_year_mismatch_without_normaliser_warns() -> None:
    r = Calculator(FactorRegistry()).calculate(spend(unit="USD"), FACTOR)
    assert r.co2e_kg == pytest.approx(500)
    assert any("inflation is not removed" in t for t in r.trace)


def test_spend_year_defaults_to_period() -> None:
    a = spend(price_year=None, period_start="2024-01-01", period_end="2024-12-31")
    assert a.spend_year == 2024


def test_csv_loaders(tmp_path: Path) -> None:
    fx = tmp_path / "fx.csv"
    fx.write_text("year,from,to,rate\n2025,EUR,USD,1.1\n")
    pi = tmp_path / "pi.csv"
    pi.write_text("currency,year,index\nUSD,2022,100\nUSD,2025,110\n")
    n = SpendNormaliser(FXTable.from_csv(fx), PriceIndex.from_csv(pi))
    qty, _ = n.normalise(1000, "EUR", 2025, "USD", 2022)
    assert qty == pytest.approx(1000.0)


# -- Scope 2 market-based fallback ----------------------------------------------------------
def test_market_based_falls_back_to_location_for_uncovered_sites() -> None:
    lb = EmissionFactor(
        factor_id="LB", name="grid", activity_unit="kWh", co2e_kg=0.2, source="t",
        scope2_method=Scope2Method.LOCATION_BASED,
    )  # fmt: skip
    mb = EmissionFactor(
        factor_id="MB", name="contract", activity_unit="kWh", co2e_kg=0.0, source="t",
        scope2_method=Scope2Method.MARKET_BASED,
    )  # fmt: skip
    calc = Calculator(FactorRegistry([lb, mb]))

    def row(i: str, site: str, fid: str) -> ActivityRecord:
        return ActivityRecord(
            activity_id=i, quantity=1000, unit="kWh", scope=Scope.SCOPE_2, site=site, factor_id=fid
        )

    inv = Inventory(
        calc.calculate_many(
            [row("a-lb", "A", "LB"), row("a-mb", "A", "MB"), row("b-lb", "B", "LB")]
        ).results
    )
    assert inv.scope2_t(Scope2Method.LOCATION_BASED) == pytest.approx(0.4)
    assert inv.scope2_t(Scope2Method.MARKET_BASED) == pytest.approx(0.2)  # A=0 + B fallback
    assert inv.scope2_market_fallback_sites() == ["B"]
    assert {r.activity_id for r in inv.headline_results()} == {"a-mb", "b-lb"}
