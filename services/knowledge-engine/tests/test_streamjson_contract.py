"""L0-7 回归网种子：Claude CLI stream-json 契约测试。

背景（蓝图 §4 L0-1 / L0-7 · 阶段0 design）：
- omni 三端（web frontend / omni-desktop / omni-orch）的 claude-runner 都靠
  `claude --output-format stream-json` 逐行 `JSON.parse` 拿 Claude 的输出，再按
  `chunk.type` 分流（system / assistant / user(tool_result) / result）。这套解析
  **没有版本钉死、没有运行时 schema 校验、且三端各写一份已分叉【R-3】**。
- L0-1 的 DoD 要求 stream-json 运行时 schema 校验**落在三端共享 runner 包里**
  （TS 端），本文件**不是**那个落地——真 runner 是 TypeScript。
- 本文件做两件事：
  ① **契约文档化**：用 py dict 把每类 chunk 的最小契约 schema 写死成可读、可测的
     事实，作为三端 runner 共享包 schema 的"单一真相草案"。
  ② **KE 侧可测原型**：在测试文件内自带一个轻量原型校验器 `validate_stream_chunk`，
     喂合法/非法样本行，断言它能正确识别。TS 端落地时照此原型对齐行为即可。

chunk 形状取自 frontend `ws-handler.ts` 实际消费的字段（grounded，不是臆造）：
  - system : {type:'system', subtype, session_id, ...}
  - assistant : {type:'assistant', message:{content:[{type:'text'|'tool_use', ...}]}, session_id}
  - user(tool_result) : {type:'user', message:{content:[{type:'tool_result', tool_use_id, ...}]}}
  - result : {type:'result', subtype, total_cost_usd, session_id, is_error, ...}
"""
import json

import pytest


# ---------------------------------------------------------------------------
# 契约 schema（最小集）—— 三端 runner 共享包 schema 的草案单一真相。
# 每个 chunk type 列出 required 顶层字段 + 校验函数。只校"分流/归因/成本归集"
# 真正依赖的字段，多出来的字段一律放行（向前兼容 CLI 加字段，避免脆性）。
# ---------------------------------------------------------------------------

#: 已知合法的顶层 chunk.type 集合。CLI 升级若新增 type，这里要同步扩（否则会被
#: 判为未知 type）。保持"白名单"而非黑名单，宁可漏放新 type 也不静默吞坏数据。
KNOWN_CHUNK_TYPES = {"system", "assistant", "user", "result"}


def _is_str(v) -> bool:
    return isinstance(v, str)


def _is_content_list(v) -> bool:
    """message.content 必须是 list[dict]，每个 block 带 str 'type'。"""
    if not isinstance(v, list):
        return False
    for block in v:
        if not isinstance(block, dict):
            return False
        if not _is_str(block.get("type")):
            return False
    return True


def _validate_system(chunk: dict) -> bool:
    # system chunk：会话起始/配置事件。ws-handler 读 session_id 做关联。
    return _is_str(chunk.get("subtype")) and _is_str(chunk.get("session_id"))


def _validate_assistant(chunk: dict) -> bool:
    # assistant chunk：必须带 message.content[]，里面才有 text / tool_use 块。
    msg = chunk.get("message")
    if not isinstance(msg, dict):
        return False
    return _is_content_list(msg.get("content"))


def _validate_user(chunk: dict) -> bool:
    # user chunk：承载 tool_result 块（block.tool_use_id 是归因链的焊点）。
    msg = chunk.get("message")
    if not isinstance(msg, dict):
        return False
    return _is_content_list(msg.get("content"))


def _validate_result(chunk: dict) -> bool:
    # result chunk：会话终结。total_cost_usd 是 L0-2 月度成本归集的来源，
    # 必须是数字（CLI 偶尔省略时按缺字段判非法，逼调用方显式兜 0 而非静默丢成本）。
    if not _is_str(chunk.get("subtype")):
        return False
    cost = chunk.get("total_cost_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return False
    return True


#: type → 校验函数 的契约表。三端 runner 共享包照此对齐。
CONTRACT_VALIDATORS = {
    "system": _validate_system,
    "assistant": _validate_assistant,
    "user": _validate_user,
    "result": _validate_result,
}


def validate_stream_chunk(line) -> bool:
    """原型校验器：判一行 stream-json 是否符合契约。

    入参可以是已 parse 的 dict，也可以是原始 JSON 字符串（模拟 runner 逐行
    `JSON.parse`）。返回 True/False，**不抛**——契约校验本身不能成为新的崩点，
    坏行应被识别为 False 由上层决定告警/丢弃（对齐 L0-3「静默失败一律告警」：
    上层拿到 False 该显式 log，而不是这里吞）。
    """
    # 1) 原始字符串 → 尝试 parse；parse 失败即非法行。
    if isinstance(line, str):
        try:
            chunk = json.loads(line)
        except (ValueError, TypeError):
            return False
    else:
        chunk = line

    # 2) 顶层必须是 dict 且带 str 'type'。
    if not isinstance(chunk, dict):
        return False
    ctype = chunk.get("type")
    if not _is_str(ctype):
        return False

    # 3) 未知 type → 非法（白名单）。
    validator = CONTRACT_VALIDATORS.get(ctype)
    if validator is None:
        return False

    # 4) 按 type 跑专属字段校验。
    return validator(chunk)


# ---------------------------------------------------------------------------
# 合法样本（每类 chunk 一条最小合法行）
# ---------------------------------------------------------------------------

VALID_SAMPLES = {
    "system": {
        "type": "system",
        "subtype": "init",
        "session_id": "sess-abc",
        "tools": ["search_kb"],
    },
    "assistant_text": {
        "type": "assistant",
        "session_id": "sess-abc",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "你好"}],
        },
    },
    "assistant_tool_use": {
        "type": "assistant",
        "session_id": "sess-abc",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "search_kb", "input": {}}
            ],
        },
    },
    "user_tool_result": {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}
            ],
        },
    },
    "result": {
        "type": "result",
        "subtype": "success",
        "session_id": "sess-abc",
        "total_cost_usd": 0.0123,
        "is_error": False,
    },
    "result_zero_cost_int": {
        # total_cost_usd 给整数 0 也合法（int 落 cost 归集）
        "type": "result",
        "subtype": "success",
        "session_id": "sess-abc",
        "total_cost_usd": 0,
    },
}


# ---------------------------------------------------------------------------
# 非法样本（每条标注它违反的契约点）
# ---------------------------------------------------------------------------

INVALID_SAMPLES = {
    "not_json": "{this is not valid json,,,",
    "not_object": "[1, 2, 3]",
    "missing_type": {"session_id": "x", "message": {"content": []}},
    "type_not_string": {"type": 123},
    "unknown_type": {"type": "telemetry", "session_id": "x"},
    "system_missing_session": {"type": "system", "subtype": "init"},
    "assistant_no_message": {"type": "assistant", "session_id": "x"},
    "assistant_content_not_list": {
        "type": "assistant",
        "message": {"content": "oops"},
    },
    "assistant_block_no_type": {
        "type": "assistant",
        "message": {"content": [{"text": "missing type field"}]},
    },
    "user_no_content": {"type": "user", "message": {}},
    "result_no_subtype": {"type": "result", "total_cost_usd": 0.1},
    "result_cost_not_number": {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": "0.1",
    },
    "result_cost_bool": {
        # bool 是 int 子类，必须显式排掉（True/False 不是成本）
        "type": "result",
        "subtype": "success",
        "total_cost_usd": True,
    },
}


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(VALID_SAMPLES.keys()))
def test_valid_chunk_accepted_as_dict(name):
    """每条合法样本（dict 形态）都应通过校验。"""
    assert validate_stream_chunk(VALID_SAMPLES[name]) is True, f"合法样本被拒: {name}"


@pytest.mark.parametrize("name", list(VALID_SAMPLES.keys()))
def test_valid_chunk_accepted_as_jsonline(name):
    """每条合法样本序列化成 JSON 行后也应通过（模拟 runner 逐行 parse）。"""
    line = json.dumps(VALID_SAMPLES[name])
    assert validate_stream_chunk(line) is True, f"合法 JSON 行被拒: {name}"


@pytest.mark.parametrize("name", list(INVALID_SAMPLES.keys()))
def test_invalid_chunk_rejected(name):
    """每条非法样本都应被识别为非法。"""
    assert validate_stream_chunk(INVALID_SAMPLES[name]) is False, f"非法样本被放行: {name}"


def test_validator_never_raises_on_garbage():
    """喂各种垃圾输入，校验器只返 False、绝不抛（契约校验不能变成新崩点）。"""
    for garbage in [None, 123, 3.14, b"bytes", [], {}, "", "   ", "null", "true"]:
        assert validate_stream_chunk(garbage) is False


def test_known_chunk_types_match_contract_table():
    """白名单集合必须跟契约校验表的 key 一一对应（防漏配一种 type 的校验）。"""
    assert KNOWN_CHUNK_TYPES == set(CONTRACT_VALIDATORS.keys())


def test_tool_use_id_is_attribution_anchor():
    """归因链焊点冒烟：tool_use(assistant) 的 id 与 tool_result(user) 的
    tool_use_id 能对上——这是蓝图阶段0「差评→哪次调用」join 的最小前提。"""
    assist = VALID_SAMPLES["assistant_tool_use"]
    user = VALID_SAMPLES["user_tool_result"]
    assert validate_stream_chunk(assist) and validate_stream_chunk(user)
    use_id = assist["message"]["content"][0]["id"]
    result_ref = user["message"]["content"][0]["tool_use_id"]
    assert use_id == result_ref == "toolu_1"


def test_result_cost_extractable_for_budget_rollup():
    """L0-2 成本归集冒烟：result chunk 的 total_cost_usd 可被安全取数累加。"""
    chunk = VALID_SAMPLES["result"]
    assert validate_stream_chunk(chunk)
    cost = chunk.get("total_cost_usd") or 0
    assert isinstance(cost, (int, float)) and cost >= 0
