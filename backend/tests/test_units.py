import uuid

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.config import Settings
from app.evaluation.metrics import aggregate, answer_metrics, retrieval_metrics
from app.llm import LLM, Ledger, LLMError, extract_json
from app.retrieval.common import Evidence, fit_budget
from app.retrieval.hybrid import rrf


def test_retrieval_metrics_basic():
    m = retrieval_metrics(["a", "g1", "b", "g2"], ["g1", "g2"], {}, [1, 3, 5])
    assert m["hit@1"] == 0.0 and m["hit@3"] == 1.0
    assert m["recall@3"] == 0.5 and m["recall@5"] == 1.0
    assert m["precision@3"] == pytest.approx(1 / 3) and m["precision@5"] == pytest.approx(2 / 5)
    assert m["mrr"] == 0.5
    assert 0 < m["ndcg@5"] < 1


def test_descendants_of_gold_count_once():
    anc = {"c1": {"g"}, "c2": {"g"}}
    m = retrieval_metrics(["c1", "c2"], ["g"], anc, [3])
    assert m["recall@3"] == 1.0 and m["precision@3"] == pytest.approx(2 / 3)
    assert m["ndcg@3"] == 1.0  # the second child of the same gold section earns no extra gain


def test_unanswerable_retrieval_is_not_measurable():
    assert all(v is None for v in retrieval_metrics(["a"], [], {}, [1]).values())


def test_answer_metrics_none_vs_zero():
    abstain = answer_metrics(answerable=False, abstained=True, correctness=None, claims=[], verdicts=[])
    assert abstain["abstention_correct"] == 1.0 and abstain["faithfulness"] is None
    wrong_abstain = answer_metrics(answerable=True, abstained=True, correctness=None, claims=[], verdicts=[])
    assert wrong_abstain["correctness"] == 0.0 and wrong_abstain["abstention_correct"] == 0.0
    claims = [{"text": "a", "evidence_ids": ["E1"]}, {"text": "b", "evidence_ids": []}]
    verdicts = [{"claim_index": 0, "cited_support": "supported", "context_support": "supported"},
                {"claim_index": 1, "cited_support": "no_citation", "context_support": "partial"}]
    m = answer_metrics(True, False, 1.0, claims, verdicts)
    assert m["faithfulness"] == 0.75 and m["citation_support"] == 1.0 and m["unsupported_claim_rate"] == 0.5


def test_aggregate_counts_unmeasured():
    a = aggregate([{"x": 1.0}, {"x": None}, {"x": 0.0}])
    assert a["x"]["mean"] == 0.5 and a["x"]["measured"] == 2 and a["x"]["n"] == 3


def ev(cid: str, tokens: int = 10, h: str | None = None) -> Evidence:
    return Evidence(chunk_id=cid, section_id="s", document_id=uuid.uuid4(), document_title="t", filename="f",
                    heading_path=[], page=None, text=cid, token_count=tokens, content_hash=h or cid)


def test_rrf_fuses_and_records_provenance():
    out = rrf([("structure", 1.0, [ev("a"), ev("b")]), ("vector", 1.0, [ev("b"), ev("c")])], k=60)
    assert [e.chunk_id for e in out] == ["b", "a", "c"]
    assert out[0].provenance["sources"] == ["structure", "vector"]
    assert out[0].provenance["structure_rank"] == 2 and out[0].provenance["vector_rank"] == 1
    weighted = rrf([("structure", 0.1, [ev("a")]), ("vector", 1.0, [ev("c")])], k=60)
    assert weighted[0].chunk_id == "c"


def test_fit_budget_skips_overflow_and_reranks():
    out = fit_budget([ev("a", 60), ev("b", 50), ev("c", 30)], 100)
    assert [(e.chunk_id, e.rank) for e in out] == [("a", 1), ("c", 2)]


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}


class Out(BaseModel):
    x: int


def _llm() -> LLM:
    return LLM(Settings(llm_api_key="k", llm_base_url="https://llm.test/v1", embedding_dim=2))


@respx.mock
async def test_retries_200_with_upstream_error_body(monkeypatch):
    monkeypatch.setattr("app.llm.asyncio.sleep", lambda *_: _noop())
    route = respx.post("https://llm.test/v1/chat/completions").mock(side_effect=[
        httpx.Response(200, json={"error": {"message": "Upstream error", "code": 502}}),
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 3}'}}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.001}}),
    ])
    ledger = Ledger()
    out = await _llm().chat_json(Out, [{"role": "user", "content": "hi"}], model="m", purpose="t", ledger=ledger)
    assert out.x == 3 and route.call_count == 3
    assert ledger.totals()["cost_usd"] == 0.001 and ledger.totals()["input_tokens"] == 10


@respx.mock
async def test_non_retryable_error_raises_and_bad_json_is_repaired(monkeypatch):
    monkeypatch.setattr("app.llm.asyncio.sleep", lambda *_: _noop())
    respx.post("https://llm.test/v1/chat/completions").mock(side_effect=[
        httpx.Response(200, json={"choices": [{"message": {"content": '{"x": "not a number"}'}}], "usage": {}}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}], "usage": {}}),
    ])
    respx.get("https://llm.test/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get("https://llm.test/v1/embeddings/models").mock(return_value=httpx.Response(200, json={"data": []}))
    ledger = Ledger()
    out = await _llm().chat_json(Out, [{"role": "user", "content": "hi"}], model="m", purpose="t", ledger=ledger)
    assert out.x == 1 and len(ledger.calls) == 2 and not ledger.calls[0].ok
    assert ledger.totals()["cost_usd"] is None  # unknown price is unknown, not free

    respx.post("https://llm.test/v1/embeddings").mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(LLMError, match="401"):
        await _llm().embed(["a"], purpose="t", ledger=Ledger())


async def _noop():
    return None
