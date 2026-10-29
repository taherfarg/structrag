"""End to end through the API against the local Supabase stack, with a fake LLM provider."""

import pytest

from .conftest import auth, wait_ready
from .test_ingest import MD

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def manual(client, alice):
    r = client.post("/api/documents", headers=auth(alice),
                    files={"file": ("manual.md", MD.encode(), "text/markdown")}, data={"metadata": '{"kind": "manual"}'})
    assert r.status_code in (200, 201), r.text
    doc = wait_ready(client, alice, r.json()["id"])
    assert doc["status"] == "ready", doc
    return doc


def tree_ids(nodes):
    return [n["id"] for n in nodes] + [i for n in nodes for i in tree_ids(n["children"])]


def test_upload_index_and_structure(client, alice, manual):
    assert manual["title"] == "Technical Manual" and manual["section_count"] == 5 and manual["chunk_count"] == 4
    s = client.get(f"/api/documents/{manual['id']}/structure", headers=auth(alice)).json()
    root = s["sections"][0]
    assert [c["heading"] for c in root["children"]] == ["Engine", "Battery"]
    assert root["children"][1]["children"][0]["heading"] == "Warranty"
    sec = client.get(f"/api/sections/{root['children'][1]['children'][0]['id']}", headers=auth(alice)).json()
    assert "8 years" in sec["content"] and sec["chunks"]


def test_duplicate_upload_returns_existing(client, alice, manual):
    r = client.post("/api/documents", headers=auth(alice), files={"file": ("again.md", MD.encode(), "text/markdown")})
    assert r.status_code == 200 and r.json()["duplicate"] and r.json()["id"] == manual["id"]


def test_rejects_bad_uploads_and_missing_auth(client, alice):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.post("/api/documents", headers=auth(alice), files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_type"


def test_rls_isolates_owners(client, alice, bob, manual):
    assert client.get("/api/documents", headers=auth(bob)).json() == []
    assert client.get(f"/api/documents/{manual['id']}", headers=auth(bob)).status_code == 404
    r = client.post("/api/retrieve/vector", headers=auth(bob), json={"query": "battery warranty"})
    assert r.status_code == 200 and r.json()["evidence"] == []
    r = client.post("/api/retrieve/structure", headers=auth(bob), json={"query": "battery warranty"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "routing_failed"


def test_reindex_is_idempotent_and_reuses_embeddings(client, alice, manual):
    before = client.get(f"/api/documents/{manual['id']}/structure", headers=auth(alice)).json()
    assert client.post(f"/api/documents/{manual['id']}/reindex", headers=auth(alice)).status_code == 202
    import time

    for _ in range(100):
        d = client.get(f"/api/documents/{manual['id']}", headers=auth(alice)).json()
        if d["version"] > manual["version"] and d["status"] == "ready":
            break
        time.sleep(0.2)
    assert d["version"] == manual["version"] + 1
    assert d["timings"]["embedded_chunks"] == 0 and d["timings"]["reused_chunks"] == 4
    after = client.get(f"/api/documents/{manual['id']}/structure", headers=auth(alice)).json()
    assert tree_ids(before["sections"]) == tree_ids(after["sections"])


def test_vector_baseline(client, alice, manual):
    r = client.post("/api/retrieve/vector", headers=auth(alice),
                    json={"query": "battery cell code", "config": {"top_k": 2}}).json()
    assert len(r["evidence"]) == 2 and r["evidence"][0]["score"] >= r["evidence"][1]["score"]
    assert "B-12" in r["evidence"][0]["text"]
    assert all(e["provenance"]["source"] == "vector" for e in r["evidence"])
    filtered = client.post("/api/retrieve/vector", headers=auth(alice),
                           json={"query": "battery", "metadata_filter": {"kind": "other"}}).json()
    assert filtered["evidence"] == []


def test_structure_routing_and_validation(client, alice, manual):
    client.fake.router = None
    r = client.post("/api/retrieve/structure", headers=auth(alice), json={"query": "battery?"}).json()
    paths = {tuple(e["heading_path"]) for e in r["evidence"]}
    # "Battery" has no text of its own; selecting it reads its whole subtree.
    assert paths == {("Battery", "Warranty")} and len(r["trace"]["selected"]) == 1

    client.fake.router = lambda p: {"selected_section_ids": ["S99", "sec_madeup"], "confidence": 0.9, "reason": "x"}
    r = client.post("/api/retrieve/structure", headers=auth(alice), json={"query": "battery warranty"})
    assert r.status_code == 422 and r.json()["error"]["details"]["invalid_ids"] == 2

    r = client.post("/api/retrieve/structure", headers=auth(alice),
                    json={"query": "battery warranty", "config": {"structure_fallback": "vector"}}).json()
    assert r["trace"]["fallback"] == "vector" and r["evidence"]
    assert all(e["provenance"]["source"] == "fallback_vector" for e in r["evidence"])

    client.fake.router = lambda p: {"selected_section_ids": [], "confidence": 0.1, "reason": "nothing relevant"}
    r = client.post("/api/retrieve/structure", headers=auth(alice), json={"query": "tyre pressure"}).json()
    assert r["evidence"] == [] and r["trace"]["no_relevant_sections"]
    client.fake.router = None


def test_structure_expansion_rounds(client, alice, manual):
    calls = []

    def router(prompt):
        calls.append(prompt)
        import re

        labels = dict((h, s) for s, h in re.findall(r"\[(S\d+)\] (\w+)", prompt))
        if len(calls) == 1:
            return {"expand_section_ids": [labels["Battery"]], "confidence": 0.5, "reason": "open battery"}
        return {"selected_section_ids": [labels["Warranty"]], "confidence": 0.9, "reason": "warranty"}

    client.fake.router = router
    r = client.post("/api/retrieve/structure", headers=auth(alice),
                    json={"query": "q", "config": {"toc_initial_depth": 1}}).json()
    client.fake.router = None
    assert "Warranty" not in calls[0] and len(r["trace"]["rounds"]) == 2
    assert {tuple(e["heading_path"]) for e in r["evidence"]} == {("Battery", "Warranty")}


def test_hybrid_keeps_provenance(client, alice, manual):
    r = client.post("/api/retrieve/hybrid", headers=auth(alice), json={"query": "battery warranty coverage"}).json()
    sources = {s for e in r["evidence"] for s in e["provenance"]["sources"]}
    assert sources == {"structure", "vector"}
    assert all("rrf" in e["provenance"] for e in r["evidence"])
    assert len({e["content_hash"] for e in r["evidence"]}) == len(r["evidence"])
    vec_only = client.post("/api/retrieve/hybrid", headers=auth(alice),
                           json={"query": "battery", "config": {"weight_structure": 0}}).json()
    assert all(e["provenance"]["sources"] == ["vector"] for e in vec_only["evidence"])


def test_ask_all_modes_with_citations(client, alice, manual):
    r = client.post("/api/ask", headers=auth(alice),
                    json={"query": "battery warranty", "config": {"verify_citations": True}}).json()
    assert set(r) == {"vector", "structure", "hybrid"}
    for mode, res in r.items():
        assert res["error"] is None, (mode, res["error"])
        a = res["answer"]
        assert a["citations"] and a["citations"][0]["filename"] == "manual.md"
        assert a["verification"][0]["cited_support"] == "supported"
        assert res["usage"]["by_purpose"]["answer"]["calls"] == 1
    an = client.get("/api/analytics", headers=auth(alice)).json()
    assert {m["mode"] for m in an["modes"]} >= {"vector", "structure", "hybrid"}
    assert an["index"][0]["stored_bytes"] > 0


def test_evidence_is_delimited_and_untrusted(client, alice, manual):
    client.fake.prompts.clear()
    client.post("/api/ask", headers=auth(alice), json={"query": "battery warranty", "modes": ["vector"]})
    answer_prompt = next(p for purpose, p in client.fake.prompts if purpose == "answer")
    assert "<<<" in answer_prompt and "[E1] manual.md > " in answer_prompt


def test_settings_roundtrip_and_validation(client, alice):
    r = client.put("/api/settings", headers=auth(alice), json={"top_k": 3})
    assert r.status_code == 200 and r.json()["config"]["top_k"] == 3
    assert client.get("/api/settings", headers=auth(alice)).json()["config"]["top_k"] == 3
    bad = client.put("/api/settings", headers=auth(alice), json={"top_k": 0})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_config"
    client.put("/api/settings", headers=auth(alice), json={"top_k": 8})


DATASET = {
    "name": "itest", "version": "v1", "corpus": ["manual.md"],
    "queries": [
        {"qid": "q1", "question": "What does the battery section promise?", "expected_answer": "8 years or 160,000 km",
         "gold": [{"doc": "manual.md", "path": ["Battery", "Warranty"]}], "tags": ["semantic"]},
        {"qid": "q2", "question": "What is the moon made of?", "answerable": False},
    ],
}


def test_benchmark_refuses_fake_llm_through_api(client, alice, manual):
    ds = client.post("/api/eval/datasets", headers=auth(alice), json=DATASET)
    assert ds.status_code == 201, ds.text
    run = client.post("/api/benchmarks", headers=auth(alice), json={"dataset_id": ds.json()["id"]}).json()
    import time

    for _ in range(50):
        got = client.get(f"/api/benchmarks/{run['id']}", headers=auth(alice)).json()
        if got["status"] == "failed":
            break
        time.sleep(0.1)
    assert got["status"] == "failed" and "fake LLM" in got["error"]


def test_benchmark_metrics_with_explicit_fake(client, alice, manual):
    from app.config import RetrievalConfig
    from app.evaluation.runner import create_run, execute_run

    ds = client.post("/api/eval/datasets", headers=auth(alice), json=DATASET).json()  # same content: same id
    run_id = client.portal.call(create_run, alice[0], ds["id"], ["vector", "structure"], RetrievalConfig(), "t")
    summary = client.portal.call(lambda: execute_run(run_id, alice[0], client.fake, allow_fake=True))
    st = summary["modes"]["structure"]
    assert st["recall@3"]["measured"] == 1 and st["recall@3"]["n"] == 2  # unanswerable query is not measurable
    assert st["hit@1"]["mean"] == 1.0
    assert summary["by_tag"]["structure"]["unanswerable"]["abstention_correct"]["n"] == 1
    run = client.get(f"/api/benchmarks/{run_id}", headers=auth(alice)).json()
    assert run["status"] == "done" and run["manifest"]["fake_llm"] is True
    assert run["manifest"]["corpus"][0]["filename"] == "manual.md" and len(run["results"]) == 4

    bad = dict(DATASET, version="v2", queries=[dict(DATASET["queries"][0], gold=[{"doc": "manual.md", "path": ["Nope"]}])])
    ds2 = client.post("/api/eval/datasets", headers=auth(alice), json=bad).json()
    run2 = client.portal.call(create_run, alice[0], ds2["id"], ["vector"], RetrievalConfig(), "t")
    with pytest.raises(ValueError, match="gold sections not found"):
        client.portal.call(lambda: execute_run(run2, alice[0], client.fake, allow_fake=True))
