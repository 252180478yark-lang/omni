"""从 XHR 原始结果算 verdict + 抽字段（纯逻辑）。语义对齐 phase5 runner_v3.js。"""
from __future__ import annotations

from typing import Any

_AUTH_CODES = {403, 401, 4000, 1001, 2000, 621, 6210}


def extract_biz_code(parsed: Any) -> Any:
    """业务码统一判定：code ?? Code ?? status ?? st ?? errno。取不到返 None。"""
    if not isinstance(parsed, dict):
        return None
    for field in ("code", "Code", "status", "st", "errno"):
        if field in parsed and parsed[field] is not None:
            return parsed[field]
    return None


def _get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _has_data(parsed: Any) -> bool:
    if not isinstance(parsed, dict):
        return False
    data = parsed.get("data")
    if data is None:
        # 有些端点平铺，无 data 字段时看除业务码外是否还有内容
        keys = set(parsed.keys()) - {"code", "Code", "status", "st", "errno", "msg", "message", "BaseResp", "request_id"}
        return len(keys) > 0
    if isinstance(data, (list, str)):
        return len(data) > 0
    if isinstance(data, dict):
        return len(data) > 0
    return data is not None


def extract_fields(parsed: Any, expected_fields: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in expected_fields or []:
        val = _get_path(parsed, f) if "." in f else (parsed.get(f) if isinstance(parsed, dict) else None)
        if val is None and isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
            val = _get_path(parsed["data"], f)
        if val is not None and not isinstance(val, (dict, list)):
            out[f] = val
        elif val is not None:
            out[f] = val
    return out


def _normalize_code(code: Any) -> Any:
    if isinstance(code, str) and code.lstrip("-").isdigit():
        return int(code)
    return code


def compute_verdict(
    status: int,
    content_type: str,
    parsed: Any,
    raw_text_sample: str,
    expected_fields: list[str] | None,
) -> dict[str, Any]:
    """返回 {verdict, code, has_data, fields}。"""
    ct = (content_type or "").lower()
    code = _normalize_code(extract_biz_code(parsed))
    fields = extract_fields(parsed, expected_fields or []) if isinstance(parsed, dict) else {}

    if status == 404:
        return {"verdict": "FAIL_404", "code": code, "has_data": False, "fields": {}}
    if status == 403:
        return {"verdict": "FAIL_AUTH", "code": code, "has_data": False, "fields": {}}
    if status == 0 or status >= 500:
        return {"verdict": "FAIL_OTHER", "code": code, "has_data": False, "fields": {}}
    # 200 段
    if parsed is None:
        # 返了非 JSON（多半 SPA HTML shell = 漂移）
        if "html" in ct or raw_text_sample.lstrip().startswith("<"):
            return {"verdict": "FAIL_DRIFT", "code": None, "has_data": False, "fields": {}}
        return {"verdict": "FAIL_OTHER", "code": None, "has_data": False, "fields": {}}
    if code in _AUTH_CODES:
        return {"verdict": "FAIL_AUTH", "code": code, "has_data": False, "fields": {}}
    if code not in (0, None):
        return {"verdict": "FAIL_OTHER", "code": code, "has_data": False, "fields": {}}
    # code == 0 或没有业务码字段
    if _has_data(parsed):
        return {"verdict": "PASS", "code": code, "has_data": True, "fields": fields}
    return {"verdict": "PASS_NODATA", "code": code, "has_data": False, "fields": fields}
