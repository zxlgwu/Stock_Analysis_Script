import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import litellm

from stock_agent.analysis.schemas import MaterialityBatch
from stock_agent.core.config import RoleConfig, Settings
from stock_agent.db.repository import Database
from stock_agent.llm.base import BudgetExceeded, LLMResult, Message
from stock_agent.llm.litellm_provider import LiteLLMProvider
from stock_agent.llm.local_embed import LocalEmbedProvider, hashed_bow
from stock_agent.llm.router import Router
from stock_agent.processing.dedupe import cosine


def _settings(tmp_path, **changes):
    loaded = Settings.load()
    roles = {
        name: RoleConfig("litellm" if role.provider == "cursor" else role.provider, role.model)
        for name, role in loaded.llm_roles.items()
    }
    return replace(loaded, root=tmp_path, database_path=tmp_path / "test.db", llm_roles=roles, **changes)


class _Vendor:
    def __init__(self, label):
        self.name = label
        self.calls = 0

    def complete(self, messages, *, model, temperature=0.0, max_tokens=None):
        self.calls += 1
        return LLMResult("ok", None, 4, 2, 0.2, model, self.name)

    def embed(self, texts, *, model):
        return [[1.0, 0.0] for _ in texts]


def test_settings_keep_role_routing_and_budgets():
    settings = Settings.load()
    assert settings.llm_roles["filter"].provider in {"litellm", "cursor"}
    assert settings.llm_roles["analysis"].provider == settings.llm_roles["filter"].provider
    assert settings.llm_roles["embed"].provider == "local"
    assert settings.weekly_budget_usd == 10
    assert settings.monthly_budget_usd == 40
    assert settings.llm_cache is True


def test_same_prompt_switches_vendor_by_config_and_logs_spend(tmp_path):
    clock = lambda: datetime(2026, 11, 8, tzinfo=timezone.utc)
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    first = _Vendor("vendor_a")
    second = _Vendor("vendor_b")
    messages = [Message("user", "Summarize Apple guidance.")]

    def routed(provider_name, model, vendor):
        roles = dict(settings.llm_roles)
        roles["filter"] = RoleConfig(provider_name, model)
        routed_settings = replace(settings, llm_roles=roles)
        router = Router(routed_settings, db, {provider_name: vendor, "local": vendor}, clock=clock)
        return router.complete("filter", messages)

    assert routed("vendor_a", "model-a", first).text == "ok"
    assert routed("vendor_b", "model-b", second).text == "ok"
    calls = db.llm_calls()
    assert [row["provider"] for row in calls] == ["vendor_a", "vendor_b"]
    assert [row["model"] for row in calls] == ["model-a", "model-b"]
    assert db.llm_spend_since(datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0.4
    db.close()


def test_cache_hit_does_not_call_the_provider_again(tmp_path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    vendor = _Vendor("litellm")
    router = Router(
        settings,
        db,
        {"litellm": vendor, "local": vendor},
        clock=lambda: datetime(2026, 11, 8, tzinfo=timezone.utc),
    )
    messages = [Message("user", "Same prompt")]
    router.complete("filter", messages)
    router.complete("filter", messages)
    assert vendor.calls == 1
    assert [row["cache_hit"] for row in db.llm_calls()] == [0, 1]
    assert db.llm_spend_since(datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0.2
    db.close()


def test_budget_guard_stops_new_calls(tmp_path):
    clock = lambda: datetime(2026, 11, 8, tzinfo=timezone.utc)
    settings = _settings(tmp_path, weekly_budget_usd=1)
    db = Database(settings.database_path)
    db.log_llm_call(
        ts=clock(),
        role="analysis",
        provider="litellm",
        model="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=1,
        cache_hit=False,
    )
    vendor = _Vendor("litellm")
    router = Router(settings, db, {"litellm": vendor, "local": vendor}, clock=clock)
    try:
        router.complete("filter", [Message("user", "another prompt")])
        raised = False
    except BudgetExceeded:
        raised = True
    assert raised
    assert vendor.calls == 0
    db.close()


def test_invalid_json_is_repaired_once(tmp_path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)

    class _Flaky:
        name = "litellm"

        def __init__(self):
            self.calls = 0

        def complete(self, messages, *, model, temperature=0.0, max_tokens=None):
            self.calls += 1
            text = "not json" if self.calls == 1 else json.dumps({"items": []})
            return LLMResult(text, None, 1, 1, 0.01, model, self.name)

        def embed(self, texts, *, model):
            return []

    vendor = _Flaky()
    router = Router(settings, db, {"litellm": vendor, "local": vendor})
    result = router.complete("filter", [Message("user", "clusters")], response_schema=MaterialityBatch)
    assert vendor.calls == 2
    assert result.parsed.items == []
    db.close()


def test_transport_retries_with_backoff(tmp_path):
    settings = _settings(tmp_path)
    db = Database(settings.database_path)
    delays = []

    class _Flaky:
        name = "litellm"

        def __init__(self):
            self.calls = 0

        def complete(self, messages, *, model, temperature=0.0, max_tokens=None):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary")
            return LLMResult("ok", None, 1, 1, 0.0, model, self.name)

        def embed(self, texts, *, model):
            return []

    vendor = _Flaky()
    router = Router(
        settings,
        db,
        {"litellm": vendor, "local": vendor},
        sleep=delays.append,
    )
    assert router.complete("filter", [Message("user", "hi")]).text == "ok"
    assert vendor.calls == 3
    assert delays == [0.5, 1.0]
    db.close()


def test_litellm_adapter_reads_text_usage_and_cost(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
        _hidden_params={"response_cost": 0.03},
    )
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: response)
    result = LiteLLMProvider().complete([Message("user", "hi")], model="openai/gpt-test")
    assert result.text == "hello"
    assert result.input_tokens == 5
    assert result.output_tokens == 2
    assert result.cost_usd == 0.03
    assert result.provider == "litellm"


def test_local_embedder_is_deterministic_and_groups_similar_text():
    provider = LocalEmbedProvider()
    first = provider.embed(["apple raises guidance"], model="hashed-bow")
    second = provider.embed(["apple raises guidance"], model="hashed-bow")
    assert first == second
    similar = cosine(hashed_bow("apple raises guidance"), hashed_bow("apple lifts guidance"))
    distant = cosine(hashed_bow("apple raises guidance"), hashed_bow("oil prices fall sharply"))
    assert similar > distant
