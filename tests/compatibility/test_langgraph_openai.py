from __future__ import annotations

from importlib.metadata import version
from typing import TypedDict

import httpx2
import pytest
from langgraph.graph import END, START, StateGraph
from openai import OpenAI


class CounterState(TypedDict):
    count: int


async def increment(state: CounterState) -> CounterState:
    return {"count": state["count"] + 1}


@pytest.mark.compatibility
@pytest.mark.asyncio
async def test_pinned_langgraph_compiles_invokes_and_streams_supported_apis() -> None:
    assert version("langgraph") == "1.2.11"
    builder = StateGraph(CounterState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    graph = builder.compile()

    assert await graph.ainvoke({"count": 0}) == {"count": 1}
    updates = [item async for item in graph.astream({"count": 4}, stream_mode="updates")]
    assert updates == [{"increment": {"count": 5}}]
    events = [item async for item in graph.astream_events({"count": 9}, version="v2")]
    assert any(item["event"] == "on_chain_start" for item in events)
    assert any(item["event"] == "on_chain_end" for item in events)


@pytest.mark.compatibility
def test_pinned_openai_responses_sdk_against_local_mock_transport() -> None:
    assert version("openai") == "3.8.0"

    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer unit-test-key"
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1_789_000_000,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "max_output_tokens": None,
                "model": "test-model",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "compatible",
                                "annotations": [],
                                "logprobs": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "previous_response_id": None,
                "reasoning": {"effort": None, "summary": None},
                "store": False,
                "temperature": None,
                "text": {"format": {"type": "text"}},
                "tool_choice": "auto",
                "tools": [],
                "top_p": None,
                "truncation": "disabled",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "metadata": {},
            },
        )

    client = OpenAI(
        api_key="unit-test-key",
        base_url="https://mock.invalid/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    response = client.responses.create(model="test-model", input="hello", store=False)

    assert response.output_text == "compatible"
