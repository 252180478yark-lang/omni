from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import video_production_workflow as workflow
from app.services.gemini_video_client import GeminiVideoClient


@pytest.mark.asyncio
async def test_raw_semantic_qa_requests_a_closed_response_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _Judge:
        def __init__(self, _: str) -> None:
            pass

        async def analyze_video(self, *_: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
            captured.update(kwargs)
            return (
                {"decision": "passed", "reason_codes": [], "evidence": ["可见产品和动作"]},
                {"total_tokens": 1},
            )

    from app.mcp import prompts
    from app.services import gemini_video_client

    monkeypatch.setattr(gemini_video_client, "GeminiVideoClient", _Judge)
    monkeypatch.setattr(workflow, "get_model_for_tool", lambda _: {"model": "judge", "provider": "gemini"})
    monkeypatch.setattr(prompts, "render", lambda *_args, **_kwargs: "prompt")
    video = tmp_path / "raw.mp4"
    video.write_bytes(b"raw")

    result = await workflow._run_raw_semantic_qa(
        path=video,
        prompt_source={},
        truth_snapshot={},
        content_spec={},
    )

    assert result["status"] == "passed"
    assert captured["response_schema"] == workflow.RAW_SEMANTIC_QA_RESPONSE_SCHEMA


@pytest.mark.asyncio
async def test_raw_semantic_qa_keeps_incomplete_decision_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TruncatedJudge:
        def __init__(self, _: str) -> None:
            pass

        async def analyze_video(self, *_: Any, **__: Any) -> tuple[dict[str, Any], dict[str, Any]]:
            # The client only returns JSON after parsing a complete object.  This
            # simulates its error on a response that stops after `decision`.
            raise RuntimeError('LLM returned incomplete JSON: {"decision":"passed"')

    from app.mcp import prompts
    from app.services import gemini_video_client

    monkeypatch.setattr(gemini_video_client, "GeminiVideoClient", _TruncatedJudge)
    monkeypatch.setattr(workflow, "get_model_for_tool", lambda _: {"model": "judge", "provider": "gemini"})
    monkeypatch.setattr(prompts, "render", lambda *_args, **_kwargs: "prompt")
    video = tmp_path / "raw.mp4"
    video.write_bytes(b"raw")

    result = await workflow._run_raw_semantic_qa(
        path=video,
        prompt_source={},
        truth_snapshot={},
        content_spec={},
    )

    assert result["status"] == "unavailable"
    assert result["reason_codes"] == ["semantic_qa_unavailable"]


@pytest.mark.asyncio
async def test_gemini_video_client_forwards_response_schema(tmp_path: Path) -> None:
    class _Model:
        def __init__(self) -> None:
            self.generation_config: dict[str, Any] | None = None

        def generate_content(self, _parts: list[Any], *, generation_config: dict[str, Any], stream: bool):
            assert stream is True
            self.generation_config = generation_config
            part = SimpleNamespace(text='{"decision":"passed","reason_codes":[],"evidence":[]}')
            candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
            return [SimpleNamespace(candidates=[candidate], usage_metadata=SimpleNamespace())]

    class _Genai:
        def upload_file(self, _path: str):
            return SimpleNamespace(name="files/test")

        def get_file(self, _name: str):
            return SimpleNamespace(state=SimpleNamespace(name="ACTIVE"))

        def delete_file(self, _name: str) -> None:
            return None

    model = _Model()
    client = object.__new__(GeminiVideoClient)
    client._genai = _Genai()
    client.model = model
    client.model_id = "judge"
    video = tmp_path / "raw.mp4"
    video.write_bytes(b"raw")
    schema = {"type": "object", "properties": {"decision": {"type": "string"}}}

    result, _usage = await client.analyze_video(
        str(video),
        "system",
        "user",
        response_schema=schema,
    )

    assert result["decision"] == "passed"
    assert model.generation_config is not None
    assert model.generation_config["response_schema"] == schema
