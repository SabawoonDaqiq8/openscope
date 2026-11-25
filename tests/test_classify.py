import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openscope import Calculator, FactorRegistry, Inventory, Scope3Category
from openscope.classify import (
    ClassifiedLine,
    Decision,
    LedgerLine,
    LLMClassifier,
    PipelineConfig,
    RuleSet,
    Status,
    SupplierMemory,
    apply_review,
    classify_ledger,
    evaluate,
    read_labels,
    read_ledger,
    read_review_csv,
    to_activities,
    write_review_csv,
)
from openscope.classify.memory import normalise_supplier
from openscope.classify.models import Classification, Source
from openscope.cli import main
from openscope.errors import OpenScopeError

EX = Path(__file__).parent.parent / "examples"
LEDGER = EX / "ledger_sample.csv"
LABELS = EX / "ledger_sample_labels.csv"
SPEND = EX / "spend_factors_example.csv"
RULES = EX / "classification_rules_example.csv"


@pytest.fixture(scope="module")
def registry() -> FactorRegistry:
    return (
        FactorRegistry.bundled()
        .merge(FactorRegistry.from_csv(SPEND))
        .merge(FactorRegistry.dataset("useeio-1.3"))
    )


@pytest.fixture(scope="module")
def spend_factors() -> list[Any]:
    # the small illustrative catalogue keeps factor ids as a schema enum
    return list(FactorRegistry.from_csv(SPEND)) + [
        f for f in FactorRegistry.bundled() if f.activity_unit == "USD"
    ]


def line(i: str = "L1", **kw: Any) -> LedgerLine:
    base: dict[str, Any] = {"line_id": i, "amount": 100.0, "currency": "USD"}
    return LedgerLine.model_validate(base | kw)


# -- fake Claude client -------------------------------------------------------------------
class FakeMessages:
    def __init__(self, responder: Any) -> None:
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responder(kwargs)


class FakeClient:
    def __init__(self, responder: Any) -> None:
        self.messages = FakeMessages(responder)
        self.beta = SimpleNamespace(messages=self.messages)


def reply(results: list[dict[str, Any]], stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps({"results": results}))],
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=50, cache_read_input_tokens=900,
            cache_creation_input_tokens=0,
        ),
    )  # fmt: skip


def result(lid: str, **kw: Any) -> dict[str, Any]:
    base = {
        "line_id": lid,
        "decision": "classify",
        "scope3_category": 1,
        "factor_id": "DEMO-SPEND-SOFTWARE",
        "confidence": 0.95,
        "rationale": "SaaS subscription",
    }
    return base | kw


def lines_in(kwargs: dict[str, Any]) -> list[str]:
    text = kwargs["messages"][0]["content"]
    payload = text.split("<ledger_lines>\n", 1)[1].split("\n</ledger_lines>", 1)[0]
    return [d["line_id"] for d in json.loads(payload)]


# -- ledger ---------------------------------------------------------------------------------
def test_ledger_aliases_and_normalisation() -> None:
    lines = read_ledger(LEDGER)
    assert len(lines) == 40
    first = lines[0]
    assert first.line_id == "AP-1001"
    assert first.supplier == "Northbeam Consulting Ltd"
    assert first.account_name == "Consulting fees"
    assert first.amount == 18500 and first.currency == "USD"
    assert first.date is not None and first.date.year == 2025


def test_ledger_default_currency_and_generated_ids(tmp_path: Path) -> None:
    p = tmp_path / "l.csv"
    p.write_text('Vendor,Amount\nAcme,"1,200.50"\nBeta,10\n')
    lines = read_ledger(p, default_currency="EUR")
    assert [ln.line_id for ln in lines] == ["L00001", "L00002"]
    assert lines[0].amount == 1200.5 and lines[0].currency == "EUR"


def test_ledger_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "l.csv"
    p.write_text("Vendor,Memo\nAcme,x\n")
    with pytest.raises(OpenScopeError, match="amount"):
        read_ledger(p)


# -- rules & memory -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("account_name", "rule"),
    [
        ("Salaries and wages", "X-PAYROLL"),
        ("Sales tax payable", "X-TAX"),
        ("Depreciation expense", "X-DEPRECIATION"),
        ("Interest expense", "X-FINANCE"),
        ("Donations", "X-DONATION"),
    ],
)
def test_default_exclusion_rules(account_name: str, rule: str) -> None:
    hit = RuleSet.default().match(line(account_name=account_name))
    assert hit is not None and hit.rule_id == rule and hit.decision == Decision.EXCLUDE


def test_default_rules_do_not_exclude_ordinary_purchases() -> None:
    assert RuleSet.default().match(line(account_name="Consulting fees")) is None


def test_invalid_rule_reports_line(tmp_path: Path) -> None:
    p = tmp_path / "r.csv"
    p.write_text("rule_id,field,pattern,decision,scope3_category\nR1,supplier,x,classify,\n")
    with pytest.raises(OpenScopeError, match=":2:.*scope3_category"):
        RuleSet.from_csv(p)


def test_supplier_normalisation() -> None:
    assert normalise_supplier("Northbeam Consulting Ltd.") == "northbeam consulting"
    assert normalise_supplier("NORTHBEAM CONSULTING, LTD") == "northbeam consulting"


# -- LLM classifier --------------------------------------------------------------------------
def test_llm_request_shape(spend_factors: list[Any]) -> None:
    client = FakeClient(lambda kw: reply([result(i) for i in lines_in(kw)]))
    clf = LLMClassifier(client, spend_factors, batch_size=10)
    out = clf.classify([line("A", description="CRM subscription")])
    assert out["A"].factor_id == "DEMO-SPEND-SOFTWARE"
    assert out["A"].scope3_category == Scope3Category.PURCHASED_GOODS_AND_SERVICES

    (kw,) = client.messages.calls
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"]["effort"] == "low"
    schema = kw["output_config"]["format"]["schema"]
    item = schema["properties"]["results"]["items"]
    assert set(item["properties"]["factor_id"]["enum"]) == {
        "",
        *(f.factor_id for f in spend_factors),
    }
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "untrusted data" in kw["system"][0]["text"]


def test_llm_system_prompt_is_stable_across_batches(spend_factors: list[Any]) -> None:
    client = FakeClient(lambda kw: reply([result(i) for i in lines_in(kw)]))
    clf = LLMClassifier(client, spend_factors, batch_size=2)
    clf.classify([line(str(i)) for i in range(5)])
    assert len(client.messages.calls) == 3  # 2 + 2 + 1
    systems = {c["system"][0]["text"] for c in client.messages.calls}
    assert len(systems) == 1  # identical prefix -> cacheable
    assert clf.usage.requests == 3 and clf.usage.cache_read_input_tokens == 2700


def test_llm_output_is_sanitised(spend_factors: list[Any]) -> None:
    def responder(kw: dict[str, Any]) -> Any:
        return reply(
            [
                result("A", factor_id="NOT-A-FACTOR"),  # unknown factor -> dropped
                result("B", decision="exclude", scope3_category=4, factor_id="DEMO-SPEND-FREIGHT"),
                result("C", scope3_category=0),  # classify without category -> unsure
                result("D", confidence=7),  # out-of-range confidence -> clamped
                result("ZZZ"),  # not in batch -> ignored
            ]
        )

    clf = LLMClassifier(FakeClient(responder), spend_factors)
    out = clf.classify([line("A"), line("B"), line("C"), line("D")])
    assert out["A"].factor_id is None
    assert out["B"].decision == Decision.EXCLUDE and out["B"].scope3_category is None
    assert out["C"].decision == Decision.UNSURE
    assert out["D"].confidence == 1.0
    assert "ZZZ" not in out


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_llm_failed_batch_goes_to_review(spend_factors: list[Any], stop: str) -> None:
    clf = LLMClassifier(FakeClient(lambda kw: reply([], stop_reason=stop)), spend_factors)
    assert clf.classify([line("A")]) == {}
    assert stop in clf.usage.failed_batches[0]


def test_llm_unparseable_response(spend_factors: list[Any]) -> None:
    bad = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="not json")], usage=None
    )
    clf = LLMClassifier(FakeClient(lambda kw: bad), spend_factors)
    assert clf.classify([line("A")]) == {}
    assert "unparseable" in clf.usage.failed_batches[0]


# -- pipeline --------------------------------------------------------------------------------
def test_pipeline_order_rules_memory_llm(spend_factors: list[Any]) -> None:
    mem = SupplierMemory()
    from openscope.classify.memory import MemoryEntry

    mem.remember(
        "CloudStack Inc",
        MemoryEntry(
            decision=Decision.CLASSIFY,
            scope3_category=Scope3Category(1),
            factor_id="DEMO-SPEND-SOFTWARE",
            reviewer="sd",
            reviewed_at="2025-11-01T00:00:00+00:00",
        ),
    )
    client = FakeClient(lambda kw: reply([result(i, confidence=0.6) for i in lines_in(kw)]))
    llm = LLMClassifier(client, spend_factors)
    out = classify_ledger(
        [
            line("pay", account_name="Salaries and wages"),
            line("mem", supplier="CLOUDSTACK INC."),
            line("llm", description="something"),
        ],
        RuleSet.default(),
        mem,
        llm,
        PipelineConfig(threshold=0.85),
    )
    by_id = {c.line.line_id: c for c in out}
    assert by_id["pay"].classification.source == Source.RULE
    assert by_id["pay"].status == Status.EXCLUDED
    assert by_id["mem"].classification.source == Source.MEMORY
    assert by_id["mem"].status == Status.AUTO_ACCEPTED
    assert by_id["llm"].status == Status.NEEDS_REVIEW  # 0.6 < threshold
    assert lines_in(client.messages.calls[0]) == ["llm"]  # only undecided lines sent


def test_classified_without_factor_needs_review() -> None:
    c = Classification(
        decision=Decision.CLASSIFY,
        scope3_category=Scope3Category(6),
        confidence=0.99,
        source=Source.LLM,
    )
    out = classify_ledger([line("A")], llm=None)
    assert out[0].status == Status.NEEDS_REVIEW
    from openscope.classify.pipeline import status_for

    assert status_for(c, PipelineConfig()) == Status.NEEDS_REVIEW


# -- review round-trip -------------------------------------------------------------------------
def test_review_roundtrip_audit_memory_and_calculation(
    tmp_path: Path, registry: FactorRegistry, spend_factors: list[Any]
) -> None:
    client = FakeClient(lambda kw: reply([result(i, confidence=0.9) for i in lines_in(kw)]))
    classified = classify_ledger(
        [
            line(
                "sw", supplier="CloudStack Inc", description="SaaS", amount=1000, date="2025-03-01"
            ),
            line("air", supplier="BlueSky Airways", description="flight", amount=2000),
            line("odd", supplier="Misc", description="services", amount=50),
            line("pay", account_name="Payroll", amount=9999),
        ],
        RuleSet.default(),
        llm=LLMClassifier(client, spend_factors),
        config=PipelineConfig(threshold=0.95),
    )
    path = tmp_path / "review.csv"
    write_review_csv(classified, path)
    rows = read_review_csv(path)
    assert [r[0].status for r in rows][:3] == [Status.NEEDS_REVIEW] * 3  # review items first

    decisions = {
        "sw": {"review_action": "accept"},
        "air": {
            "review_action": "override",
            "review_category": "6",
            "review_factor_id": "DEMO-SPEND-AIR-TRAVEL",
            "review_note": "airfare",
        },
        "odd": {"review_action": "exclude", "review_note": "pass-through cost"},
    }
    edited = [(c, decisions.get(c.line.line_id, r)) for c, r in rows]
    memory = SupplierMemory()
    outcome = apply_review(
        edited,
        "S. Daqiq",
        known_factor_ids={f.factor_id for f in registry},
        memory=memory,
        now=datetime(2025, 11, 25, tzinfo=UTC),
    )
    assert len(outcome.audit_entries) == 3
    air = next(e for e in outcome.audit_entries if e["line_id"] == "air")
    assert air["before"]["factor_id"] == "DEMO-SPEND-SOFTWARE"  # type: ignore[index]
    assert air["after"]["factor_id"] == "DEMO-SPEND-AIR-TRAVEL"  # type: ignore[index]
    assert air["reviewer"] == "S. Daqiq"
    assert memory.lookup(line("x", supplier="BlueSky Airways Ltd")) is not None

    acts = to_activities(outcome.lines)
    assert {a.activity_id for a in acts} == {"sw", "air"}
    sw = next(a for a in acts if a.activity_id == "sw")
    assert sw.price_year == 2025 and sw.unit == "USD"

    inv = Inventory(Calculator(registry).calculate_many(acts).results)
    assert inv.scope3_t() == pytest.approx((1000 * 0.08 + 2000 * 0.9) / 1000)

    mem_path = tmp_path / "mem.json"
    memory.save(mem_path)
    assert len(SupplierMemory.load(mem_path)) == 3


@pytest.mark.parametrize(
    ("review", "msg"),
    [
        ({"review_action": "override", "review_category": "6"}, "needs review_category"),
        (
            {"review_action": "override", "review_category": "6", "review_factor_id": "NOPE"},
            "unknown factor_id",
        ),
        ({"review_action": "maybe"}, "unknown review_action"),
    ],
)
def test_review_validation(review: dict[str, str], msg: str) -> None:
    c = ClassifiedLine(
        line=line("A"),
        classification=Classification(decision=Decision.UNSURE, confidence=0, source=Source.NONE),
        status=Status.NEEDS_REVIEW,
    )
    with pytest.raises(OpenScopeError, match=msg):
        apply_review([(c, review)], "me", known_factor_ids={"X"})


def test_accept_incomplete_proposal_rejected() -> None:
    c = ClassifiedLine(
        line=line("A"),
        classification=Classification(decision=Decision.UNSURE, confidence=0, source=Source.NONE),
        status=Status.NEEDS_REVIEW,
    )
    with pytest.raises(OpenScopeError, match="incomplete"):
        apply_review([(c, {"review_action": "accept"})], "me")
    with pytest.raises(OpenScopeError, match="reviewer"):
        apply_review([], " ")


# -- evaluation ----------------------------------------------------------------------------------
def test_rules_only_baseline_on_sample_ledger() -> None:
    rules = RuleSet.default() + RuleSet.from_csv(RULES)
    classified = classify_ledger(read_ledger(LEDGER), rules)
    report = evaluate(classified, read_labels(LABELS))
    assert report.labelled == 40
    assert report.auto_precision == 1.0  # rules must never be wrong on the sample
    assert report.coverage == pytest.approx(15 / 40)


def test_evaluate_metrics_with_perfect_fake_llm(spend_factors: list[Any]) -> None:
    labels = read_labels(LABELS)
    truth = {}
    for lid, lab in labels.items():
        if lab == "exclude":
            truth[lid] = result(lid, decision="exclude", scope3_category=0, factor_id="")
        elif lab == "unsure":
            truth[lid] = result(
                lid, decision="unsure", scope3_category=0, factor_id="", confidence=0.3
            )
        else:
            cat = int(lab.removeprefix("cat"))
            fid = next(f.factor_id for f in spend_factors if f.scope3_category == cat)
            truth[lid] = result(lid, scope3_category=cat, factor_id=fid)

    client = FakeClient(lambda kw: reply([truth[i] for i in lines_in(kw)]))
    classified = classify_ledger(
        read_ledger(LEDGER), RuleSet.default(), llm=LLMClassifier(client, spend_factors)
    )
    report = evaluate(classified, labels)
    assert report.accuracy == 1.0
    assert report.auto_precision == 1.0
    assert report.coverage == pytest.approx(39 / 40)  # only the vague line is left for review


# -- CLI ------------------------------------------------------------------------------------------
def test_cli_classify_and_review_apply(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    review = tmp_path / "review.csv"
    rc = main(
        [
            "classify", str(LEDGER), "--dataset", "useeio-1.3", "--rules", str(RULES),
            "--out", str(review), "--labels", str(LABELS),
        ]
    )  # fmt: skip
    assert rc == 0
    assert '"auto_accept_precision": 1.0' in capsys.readouterr().out

    text = review.read_text().splitlines()
    header, body = text[0], text[1:]
    # reviewer accepts the airfare line that a rule classified, overrides one pending line
    edited = [header]
    for row in body:
        if row.startswith("AP-1004,"):
            row = row[: -len(",,,,")] + ",override,1,USEEIO-1.3-511210,SaaS"
        edited.append(row)
    review.write_text("\n".join(edited) + "\n")

    acts, audit, mem = tmp_path / "acts.csv", tmp_path / "audit.jsonl", tmp_path / "mem.json"
    rc = main(
        [
            "review-apply", str(review), "--dataset", "useeio-1.3", "--reviewer", "S. Daqiq",
            "--activities-out", str(acts), "--audit-log", str(audit), "--memory", str(mem),
        ]
    )  # fmt: skip
    assert rc == 0
    assert len(audit.read_text().splitlines()) == 1
    assert "cloudstack" in mem.read_text()
    assert main(["calculate", str(acts), "--dataset", "useeio-1.3"]) == 0


def test_large_catalogue_uses_string_schema_and_still_rejects_unknown_ids() -> None:
    useeio = [f for f in FactorRegistry.dataset("useeio-1.3")]
    client = FakeClient(
        lambda kw: reply(
            [
                result("A", factor_id="USEEIO-1.3-721110", scope3_category=6),
                result("B", factor_id="USEEIO-1.3-999999"),
            ]
        )
    )
    clf = LLMClassifier(client, useeio)
    out = clf.classify([line("A"), line("B")])
    schema = client.messages.calls[0]["output_config"]["format"]["schema"]
    fid = schema["properties"]["results"]["items"]["properties"]["factor_id"]
    assert "enum" not in fid
    assert out["A"].factor_id == "USEEIO-1.3-721110"
    assert out["B"].factor_id is None  # made-up id dropped
