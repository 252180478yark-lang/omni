"""T2：trace 工具函数。"""
from app.mcp.trace import build_trace, attach_next_step


def test_build_trace_minimal():
    t = build_trace(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt="hello",
        params={"temperature": 0.3},
        cost_estimate="1 quota call",
    )
    assert t["model"] == "claude-sonnet-4-6"
    assert t["model_provider"] == "anthropic"
    assert t["final_prompt"] == "hello"
    assert t["params"] == {"temperature": 0.3}
    assert t["cost_estimate"] == "1 quota call"


def test_build_trace_truncates_long_prompt():
    long = "x" * 50_000
    t = build_trace(
        provider="anthropic", model="m", prompt=long, params={}, cost_estimate=""
    )
    # prompt 太长截断防止 audit 表 jsonb 行爆
    assert len(t["final_prompt"]) <= 16_384
    assert t["final_prompt"].endswith("...[truncated]")


def test_attach_next_step_adds_field():
    result = {"ok": True, "result": {"x": 1}, "trace": {"model": "m"}}
    out = attach_next_step(
        result,
        suggested_tool="generate_image",
        suggested_args={"prompts": ["a"]},
        human_text="出图",
    )
    assert out["next_step_hint"]["suggested_tool"] == "generate_image"
    assert out["next_step_hint"]["human_text"] == "出图"
    # 不破坏原 result
    assert out["result"] == {"x": 1}
