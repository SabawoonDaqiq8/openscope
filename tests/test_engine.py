import pytest
from pydantic import ValidationError

from openscope import (
    ActivityRecord,
    CalculationMethod,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    FactorStatus,
    Scope,
    Scope2Method,
    Scope3Category,
)
from openscope.errors import FactorError


@pytest.fixture
def calc() -> Calculator:
    return Calculator(FactorRegistry.bundled(), gwp_set="AR6", reporting_year=2025)


def act(**kw: object) -> ActivityRecord:
    base: dict[str, object] = {"activity_id": "a1", "scope": Scope.SCOPE_1}
    return ActivityRecord.model_validate(base | kw)


def test_natural_gas_per_gas_math(calc: Calculator) -> None:
    r = calc.calculate(act(quantity=1200, unit="MMBtu", factor_id="EPA-STAT-NATGAS"))
    expected = 1200 * (53.06 + 0.001 * 29.8 + 0.0001 * 273)
    assert r.co2e_kg == pytest.approx(expected)
    assert r.gas_kg["CH4"] == pytest.approx(1.2)
    assert any("GWP 29.8" in t for t in r.trace)


def test_unit_conversion_applied(calc: Calculator) -> None:
    a = calc.calculate(act(quantity=12_000, unit="therm", factor_id="EPA-STAT-NATGAS"))
    b = calc.calculate(act(quantity=1_200, unit="MMBtu", factor_id="EPA-STAT-NATGAS"))
    assert a.co2e_kg == pytest.approx(b.co2e_kg)
    assert a.converted_quantity == pytest.approx(1200)


def test_gwp_set_changes_result_for_per_gas_factor() -> None:
    a = act(quantity=1, unit="kg", factor_id="REFRIG-HFC134A")
    ar5 = Calculator(gwp_set="AR5").calculate(a)
    ar6 = Calculator(gwp_set="AR6").calculate(a)
    assert ar5.co2e_kg == pytest.approx(1300)
    assert ar6.co2e_kg == pytest.approx(1530)


def test_incompatible_unit_rejected(calc: Calculator) -> None:
    with pytest.raises(FactorError, match="incompatible"):
        calc.calculate(act(quantity=1, unit="L", factor_id="EPA-STAT-NATGAS"))


def test_unknown_factor(calc: Calculator) -> None:
    with pytest.raises(FactorError, match="Unknown factor_id"):
        calc.calculate(act(quantity=1, unit="kWh", factor_id="NOPE"))


def test_scope2_method_mismatch_rejected(calc: Calculator) -> None:
    a = act(
        scope=Scope.SCOPE_2,
        scope2_method=Scope2Method.LOCATION_BASED,
        quantity=1,
        unit="kWh",
        factor_id="DEMO-RESIDUAL-MIX-MB",
    )
    with pytest.raises(FactorError, match="market_based"):
        calc.calculate(a)


def test_scope2_method_inherited_from_factor(calc: Calculator) -> None:
    r = calc.calculate(
        act(scope=Scope.SCOPE_2, quantity=10, unit="MWh", factor_id="DEMO-RESIDUAL-MIX-MB")
    )
    assert r.scope2_method == Scope2Method.MARKET_BASED
    assert r.co2e_kg == pytest.approx(5000)


def test_scope3_requires_category() -> None:
    with pytest.raises(ValidationError, match="scope3_category"):
        act(scope=Scope.SCOPE_3, quantity=1, unit="USD")


def test_illustrative_factor_warns_and_penalises(calc: Calculator) -> None:
    r = calc.calculate(
        act(
            scope=Scope.SCOPE_3,
            scope3_category=Scope3Category.PURCHASED_GOODS_AND_SERVICES,
            quantity=1000,
            unit="USD",
            method=CalculationMethod.SPEND_BASED,
            factor_id="DEMO-SPEND-PROF-SERVICES",
        )
    )
    assert r.factor_status == FactorStatus.ILLUSTRATIVE
    assert r.data_quality_score == 5
    assert any("illustrative" in t for t in r.trace)


def test_explicit_custom_factor(calc: Calculator) -> None:
    f = EmissionFactor(
        factor_id="SUPPLIER-X-PCF",
        name="Widget PCF from supplier X",
        activity_unit="item",
        co2e_kg=2.5,
        source="Supplier X EPD 2025",
        status=FactorStatus.CUSTOM,
        year=2025,
    )
    r = calc.calculate(
        act(
            scope=Scope.SCOPE_3,
            scope3_category=Scope3Category.PURCHASED_GOODS_AND_SERVICES,
            quantity=400,
            unit="unit",
            method=CalculationMethod.SUPPLIER_SPECIFIC,
        ),
        factor=f,
    )
    assert r.co2e_kg == pytest.approx(1000)
    assert r.data_quality_score == 1


def test_calculate_many_collects_errors(calc: Calculator) -> None:
    batch = calc.calculate_many(
        [
            act(activity_id="ok", quantity=1, unit="MMBtu", factor_id="EPA-STAT-NATGAS"),
            act(activity_id="bad", quantity=1, unit="MMBtu", factor_id="MISSING"),
        ]
    )
    assert [r.activity_id for r in batch.results] == ["ok"]
    assert [e.activity_id for e in batch.errors] == ["bad"]
    assert not batch.ok
