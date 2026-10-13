"""/ask on other backends: OpenRouter, Ollama, or any OpenAI-compatible server.

The deployer picks the backend and the model; a visitor picks nothing. The
OpenAI-compatible loop is driven through `httpx.MockTransport`, so no model is
ever called and no network is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from atlas import agent, store

LLM_VARS = (
    "ATLAS_LLM",
    "ATLAS_LLM_MODEL",
    "ATLAS_LLM_BASE_URL",
    "ATLAS_LLM_API_KEY",
    "ATLAS_LLM_MAX_TOKENS",
    "ATLAS_LLM_LABEL",
)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name in LLM_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    for name, value in values.items():
        monkeypatch.setenv(name, value)


# --- choosing the backend ---------------------------------------------------------


def test_default_backend_is_anthropic_on_the_cheapest_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    backend = agent.backend()
    assert (backend.name, backend.model) == ("anthropic", agent.MODEL)


@pytest.mark.parametrize(
    ("name", "url"),
    [("openrouter", "https://openrouter.ai/api/v1"), ("ollama", "http://localhost:11434/v1")],
)
def test_presets_know_their_address(monkeypatch: pytest.MonkeyPatch, name: str, url: str) -> None:
    _env(monkeypatch, ATLAS_LLM=name, ATLAS_LLM_MODEL="m", ATLAS_LLM_API_KEY="k")
    assert agent.backend().base_url == url


def test_a_base_url_overrides_the_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        ATLAS_LLM="ollama",
        ATLAS_LLM_MODEL="qwen3",
        ATLAS_LLM_BASE_URL="http://ollama:11434/v1/",
    )
    assert agent.backend().base_url == "http://ollama:11434/v1"


def test_ollama_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, ATLAS_LLM="ollama", ATLAS_LLM_MODEL="qwen3")
    assert agent.backend().api_key is None


@pytest.mark.parametrize(
    ("env", "names"),
    [
        ({"ATLAS_LLM": "openrouter", "ATLAS_LLM_API_KEY": "k"}, "ATLAS_LLM_MODEL"),
        ({"ATLAS_LLM": "openrouter", "ATLAS_LLM_MODEL": "m"}, "ATLAS_LLM_API_KEY"),
        ({"ATLAS_LLM": "openai-compatible", "ATLAS_LLM_MODEL": "m"}, "ATLAS_LLM_BASE_URL"),
        ({"ATLAS_LLM": "gpt"}, "ATLAS_LLM"),
        (
            {"ATLAS_LLM": "ollama", "ATLAS_LLM_MODEL": "m", "ATLAS_LLM_MAX_TOKENS": "lots"},
            "ATLAS_LLM_MAX_TOKENS",
        ),
        (
            {"ATLAS_LLM": "ollama", "ATLAS_LLM_MODEL": "m", "ATLAS_LLM_MAX_TOKENS": "²"},
            "ATLAS_LLM_MAX_TOKENS",
        ),
    ],
)
def test_incomplete_configuration_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], names: str
) -> None:
    _env(monkeypatch, **env)
    with pytest.raises(RuntimeError, match=names):
        agent.backend()


@pytest.mark.parametrize(
    ("env", "label"),
    [
        ({}, "Anthropic"),
        (
            {"ATLAS_LLM": "openrouter", "ATLAS_LLM_MODEL": "m", "ATLAS_LLM_API_KEY": "k"},
            "OpenRouter, which passes it to the model's provider",
        ),
        (
            {"ATLAS_LLM": "ollama", "ATLAS_LLM_MODEL": "m"},
            "a model run by the operator of this site",
        ),
        (
            {
                "ATLAS_LLM": "ollama",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_BASE_URL": "http://ollama:11434/v1",
            },
            "an Ollama server at ollama, chosen by the operator of this site",
        ),
        (
            {
                "ATLAS_LLM": "ollama",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_BASE_URL": "https://gpu.example.org/v1",
            },
            "an Ollama server at gpu.example.org, chosen by the operator of this site",
        ),
        (
            # A proxy on a service name usually forwards to a hosted model: not "run by".
            {
                "ATLAS_LLM": "openai-compatible",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_BASE_URL": "http://litellm:4000/v1",
            },
            "a model server at litellm, chosen by the operator of this site",
        ),
        (
            {
                "ATLAS_LLM": "openai-compatible",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_BASE_URL": "http://[2001:db8::1]:8000/v1",
            },
            "a model server at 2001:db8::1, chosen by the operator of this site",
        ),
        (
            {
                "ATLAS_LLM": "openai-compatible",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_BASE_URL": "http://127.0.0.1:8000/v1",
            },
            "a model run by the operator of this site",
        ),
        (
            {
                "ATLAS_LLM": "ollama",
                "ATLAS_LLM_MODEL": "m",
                "ATLAS_LLM_LABEL": "the lab's own GPU server",
            },
            "the lab's own GPU server",
        ),
    ],
)
def test_the_privacy_label_names_where_questions_go(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], label: str
) -> None:
    _env(monkeypatch, **env)
    assert agent.describe_backend()["label"] == label


def test_anthropic_without_credentials_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Checked before an ask is counted, so an unkeyed default deploy spends nothing.
    _env(monkeypatch)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", "/nonexistent")  # no `ant auth login` profile either
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        agent.backend()
    assert agent.describe_backend() is None


def test_a_misconfigured_backend_describes_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, ATLAS_LLM="openrouter")
    assert agent.describe_backend() is None


# --- the OpenAI-compatible loop ------------------------------------------------------


class FakeModel:
    """A chat-completions server that replays scripted replies and keeps every request."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": {"message": "upstream says no"}})
        return httpx.Response(200, json={"choices": [reply]})

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].content)


def tool_call(name: str, arguments: str | dict, call_id: str = "c1") -> dict:
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    return {
        "finish_reason": "tool_calls",
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
    }


def final(text: str, finish: str = "stop") -> dict:
    return {"finish_reason": finish, "message": {"role": "assistant", "content": text}}


DPRE1_SQL = "SELECT rv_id FROM target_summary WHERE gene_name = 'dprE1'"


@pytest.fixture
def ollama(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, ATLAS_LLM="ollama", ATLAS_LLM_MODEL="qwen3")
    monkeypatch.setattr(agent, "STORE", evidence_store)
    monkeypatch.setattr(store, "STORE", evidence_store)
    monkeypatch.setattr(agent, "_connection", None)


def _ask(fake: FakeModel, question: str = "What is dprE1?") -> agent.Answer:
    return agent.ask(question, transport=httpx.MockTransport(fake))


def test_a_tool_call_round_trip_answers_from_the_store(ollama: None) -> None:
    fake = FakeModel([tool_call("query_store", {"sql": DPRE1_SQL}), final("dprE1 is Rv3790.")])
    answer = _ask(fake)

    assert answer.text == "dprE1 is Rv3790."
    assert [(c.name, c.rows) for c in answer.calls] == [("query_store", 1)]
    assert answer.sources  # provenance travels with every answer, as on Anthropic

    first, second = fake.body(0), fake.body(1)
    assert fake.requests[0].url.path == "/v1/chat/completions"
    assert first["model"] == "qwen3"
    assert first["messages"][0] == {"role": "system", "content": agent.SYSTEM}
    assert {t["function"]["name"] for t in first["tools"]} == {"describe_store", "query_store"}
    assert "max_tokens" not in first
    tool_reply = second["messages"][-1]
    assert tool_reply["role"] == "tool" and tool_reply["tool_call_id"] == "c1"
    assert "Rv3790" in tool_reply["content"]


def test_ollama_sends_no_key_and_openrouter_sends_its_own(
    ollama: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeModel([final("ok")])
    _ask(fake)
    assert "authorization" not in fake.requests[0].headers

    _env(monkeypatch, ATLAS_LLM="openrouter", ATLAS_LLM_MODEL="m", ATLAS_LLM_API_KEY="sk-or")
    fake = FakeModel([final("ok")])
    _ask(fake)
    assert fake.requests[0].headers["authorization"] == "Bearer sk-or"
    assert fake.requests[0].url.host == "openrouter.ai"


def test_max_tokens_is_sent_only_when_the_deployer_sets_it(
    ollama: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "4096")
    fake = FakeModel([final("ok")])
    _ask(fake)
    assert fake.body(0)["max_tokens"] == 4096


def test_a_loop_that_never_answers_is_labelled_not_passed_off(ollama: None) -> None:
    fake = FakeModel([tool_call("describe_store", {})] * agent.MAX_TURNS)
    answer = _ask(fake)
    assert len(fake.requests) == agent.MAX_TURNS
    assert answer.text.startswith(f"**{agent.STOPPED['tool_use']}**")


def test_a_cut_off_answer_says_so(ollama: None) -> None:
    answer = _ask(FakeModel([final("dprE1 is", finish="length")]))
    assert answer.text.startswith(f"**{agent.STOPPED['max_tokens']}**")
    assert answer.text.endswith("dprE1 is")


def test_an_upstream_error_is_a_runtime_error(ollama: None) -> None:
    with pytest.raises(RuntimeError, match="model call failed"):
        _ask(FakeModel([500]))


def test_a_reply_that_is_not_chat_completions_is_a_runtime_error(ollama: None) -> None:
    def nonsense(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(RuntimeError, match="model call failed"):
        agent.ask("What is dprE1?", transport=httpx.MockTransport(nonsense))


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (tool_call("query_store", "{not json"), "arguments"),
        (tool_call("drop_everything", {}), "no tool"),
        (tool_call("query_store", {"sql": "DELETE FROM genes"}), "only SELECT"),
    ],
)
def test_a_bad_tool_call_goes_back_to_the_model_as_an_error(
    ollama: None, call: dict, error: str
) -> None:
    fake = FakeModel([call, final("sorry")])
    answer = _ask(fake)
    tool_reply = fake.body(1)["messages"][-1]
    assert tool_reply["content"].startswith("ERROR") and error in tool_reply["content"]
    assert answer.text == "sorry"


def test_arguments_given_as_an_object_are_accepted(ollama: None) -> None:
    # Some servers send `arguments` as a JSON object rather than a string.
    reply = tool_call("query_store", "x")
    reply["message"]["tool_calls"][0]["function"]["arguments"] = {"sql": DPRE1_SQL}
    fake = FakeModel([reply, final("Rv3790")])
    _ask(fake)
    assert "Rv3790" in fake.body(1)["messages"][-1]["content"]


@pytest.mark.parametrize("reason", ["error", "tool_calls", "something_new"])
def test_an_unknown_finish_reason_is_labelled_not_passed_off(ollama: None, reason: str) -> None:
    answer = _ask(FakeModel([final("partial", finish=reason)]))
    assert answer.text.startswith("**") and answer.text.endswith("partial")
    assert answer.text != "partial"


def test_upstream_errors_never_show_the_service_address_or_a_key(
    ollama: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ATLAS_LLM_BASE_URL", "https://user:sk-secret@llm.internal.example/v1?key=sk-q"
    )
    with pytest.raises(RuntimeError) as caught:
        _ask(FakeModel([401]))
    message = str(caught.value)
    assert "401" in message
    for leak in ("sk-secret", "sk-q", "llm.internal.example", "user"):
        assert leak not in message


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"tool_calls": ["not a call"]}}]},
        {"choices": "nope"},
    ],
)
def test_a_malformed_reply_is_a_runtime_error_not_a_crash(ollama: None, body: dict) -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(RuntimeError, match="model call failed"):
        agent.ask("What is dprE1?", transport=httpx.MockTransport(reply))


def test_a_question_that_runs_past_its_deadline_stops_labelled(
    ollama: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "ASK_DEADLINE", 0.0)
    fake = FakeModel([tool_call("describe_store", {}), final("late")])
    answer = _ask(fake)
    assert len(fake.requests) == 1
    assert answer.text.startswith(f"**{agent.STOPPED['deadline']}**")
