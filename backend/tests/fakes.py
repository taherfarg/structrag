"""Deterministic stand-ins for the LLM provider. Unit and integration tests only.

The benchmark runner refuses to run with these unless explicitly told to, and
then marks the run's manifest `fake_llm: true`.
"""

import hashlib
import math
import re

from app.answer import AnswerOut, VerifyOut
from app.evaluation.runner import CorrectnessOut
from app.llm import Call, Ledger
from app.retrieval.structure import DocSelectOut, RouteOut

WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "is", "what", "for", "how", "in", "on", "to", "and", "does", "do", "which"}


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


class FakeLLM:
    is_fake = True

    def __init__(self, dim: int = 1536):
        self.dim = dim
        self.router = None  # optional callable(prompt) -> dict, to script routing in a test
        self.prompts: list[tuple[str, str]] = []

    async def aclose(self):
        pass

    async def embed(self, texts, *, purpose, ledger: Ledger, batch=64):
        ledger.calls.append(Call(purpose, "fake-embed", sum(len(t) // 4 for t in texts), 0, 0.0, 1.0))
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in words(t):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    async def chat_json(self, schema, messages, *, model, purpose, ledger: Ledger, max_tokens=1000):
        prompt = messages[-1]["content"]
        self.prompts.append((purpose, prompt))
        ledger.calls.append(Call(purpose, "fake-chat", len(prompt) // 4, 20, 0.0, 1.0))
        question = prompt.split("\n", 1)[0].removeprefix("Question: ")
        if schema is RouteOut:
            if self.router:
                return RouteOut(**self.router(prompt))
            best, score = None, 0
            for line in prompt.splitlines():
                m = re.match(r"\s*\[(S\d+)\] (.*?) \(", line)
                if m and len(words(m.group(2)) & words(question)) > score:
                    best, score = m.group(1), len(words(m.group(2)) & words(question))
            return RouteOut(selected_section_ids=[best] if best else [], confidence=0.8, reason="lexical")
        if schema is DocSelectOut:
            return DocSelectOut(selected_document_ids=re.findall(r"\[(D\d+)\]", prompt)[:3], confidence=0.5, reason="")
        if schema is AnswerOut:
            first = re.search(r"<<<\w+\n(.*?)\n\w+>>>", prompt, re.S)
            text = first.group(1)[:80] if first else ""
            return AnswerOut(answer=f"{text} [E1]", claims=[{"text": text, "evidence_ids": ["E1"]}])
        if schema is VerifyOut:
            n = len(re.findall(r"^\d+\. ", prompt.split("Claims:")[-1], re.M))
            return VerifyOut(verdicts=[{"claim_index": i, "cited_support": "supported",
                                        "context_support": "supported"} for i in range(n)])
        if schema is CorrectnessOut:
            return CorrectnessOut(verdict="correct", rationale="fake")
        raise AssertionError(f"FakeLLM has no reply for {schema.__name__}")
