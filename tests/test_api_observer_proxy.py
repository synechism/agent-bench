from __future__ import annotations

from measure.api_observer_proxy import _summarize_request_json


def test_anthropic_messages_are_split_into_semantic_layers(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_API_OBSERVER_CAPTURE_PROMPTS", "1")
    monkeypatch.setenv("HARNESS_API_OBSERVER_CAPTURE_CHARS", "10000")

    payload = {
        "model": "claude-test",
        "system": [{"type": "text", "text": "system prompt"}],
        "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "please inspect redis"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [{"type": "text", "text": "src/server.c: result"}],
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "need to search"},
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Grep",
                        "input": {"pattern": "GETEX"},
                    },
                    {"type": "text", "text": "I will look at the command table."},
                ],
            },
        ],
    }

    summary = _summarize_request_json(payload)

    assert summary["messages"]["by_role"] == {"assistant": 1, "user": 1}
    assert summary["messages"]["by_type"] == {
        "text": 2,
        "thinking": 1,
        "tool_result": 1,
        "tool_use": 1,
    }
    assert set(summary["messages"]["by_semantic_layer"]) == {
        "assistant_memory",
        "reasoning_or_compaction_memory",
        "tool_call_memory",
        "tool_output_memory",
        "user_or_task",
    }
    assert "system_instructions" in summary["semantic_layers"]
    assert "tool_schema" in summary["semantic_layers"]
    assert summary["messages"]["messages"][0]["semantic_layer"] == "mixed"
    tool_use_block = summary["messages"]["messages"][1]["blocks"][1]
    assert tool_use_block["semantic_layer"] == "tool_call_memory"
    assert tool_use_block["id"] == "toolu_2"
    assert tool_use_block["name"] == "Grep"
