"""响应解析器 — 从 Gemini API 响应中提取并验证结构化数据"""

import json
import logging
import re
from typing import Optional

from app.models import AnalysisResult, Segment, Summary, PersonSummary, PersonScript

logger = logging.getLogger("livestream-analysis")


class ParseError(Exception):
    pass


def seconds_to_mmss(total_seconds: float) -> str:
    m = int(total_seconds) // 60
    s = int(total_seconds) % 60
    return f"{m:02d}:{s:02d}"


class ResponseParser:

    def parse(self, raw_response: dict) -> AnalysisResult:
        text = self._extract_text(raw_response)
        if not text:
            raise ParseError("API 响应中没有找到文本内容")
        json_data = self._extract_json(text)
        if json_data is None:
            raise ParseError(f"无法从响应中提取 JSON:\n{text[:500]}")
        return self._validate(json_data)

    def _extract_text(self, raw: dict) -> Optional[str]:
        try:
            parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return "\n".join(p["text"] for p in parts if not p.get("thought") and "text" in p) or None
        except (IndexError, KeyError, TypeError):
            return None

    def _extract_json(self, text: str) -> Optional[dict]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            candidate = text[i:j + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                fixed = self._fix_json(candidate)
                if fixed:
                    return fixed
        return self._fix_json(text)

    def _fix_json(self, broken: str) -> Optional[dict]:
        t = broken.strip()
        t = re.sub(r",\s*([}\]])", r"\1", t)
        t = t.replace("'", '"')
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            pass
        ob = t.count("{") - t.count("}")
        osb = t.count("[") - t.count("]")
        if ob > 0 or osb > 0:
            t += "]" * osb + "}" * ob
            try:
                return json.loads(t)
            except json.JSONDecodeError:
                pass
        return None

    def _validate(self, data: dict) -> AnalysisResult:
        try:
            return AnalysisResult.model_validate(data)
        except Exception:
            return self._manual_parse(data)

    def _manual_parse(self, data: dict) -> AnalysisResult:
        segments: list[Segment] = []
        for i, seg in enumerate(data.get("segments", [])):
            try:
                scripts: dict[str, PersonScript] = {}
                for k, v in seg.get("scripts", {}).items():
                    if isinstance(v, dict):
                        scripts[k] = PersonScript(role=v.get("role", f"人物{k}"), content=v.get("content", ""))
                    elif isinstance(v, str):
                        scripts[k] = PersonScript(role=f"人物{k}", content=v)
                segments.append(Segment(
                    time_start=str(seg.get("time_start", "00:00")),
                    time_end=str(seg.get("time_end", "00:00")),
                    duration_seconds=int(seg.get("duration_seconds", 0)),
                    phase=str(seg.get("phase", "未知")),
                    visual_description=str(seg.get("visual_description", "")),
                    background_elements=seg.get("background_elements", []),
                    overlay_elements=seg.get("overlay_elements", []),
                    person_count=int(seg.get("person_count", 0)),
                    person_roles=seg.get("person_roles", []),
                    scripts=scripts,
                    speech_pace=str(seg.get("speech_pace", "中速")),
                    rhythm_notes=str(seg.get("rhythm_notes", "")),
                    style_tags=seg.get("style_tags", []),
                    notes=seg.get("notes"),
                ))
            except Exception as e:
                logger.warning("解析第 %d 段失败: %s", i + 1, e)
        if not segments:
            raise ParseError("所有段落解析失败")

        raw_s = data.get("summary", {})
        ps_list = [PersonSummary(role=p.get("role", "未知"), description=p.get("description", ""))
                   for p in raw_s.get("person_summary", []) if isinstance(p, dict)]

        return AnalysisResult(
            segments=segments,
            summary=Summary(
                total_duration=str(raw_s.get("total_duration", "00:00")),
                total_segments=len(segments),
                person_summary=ps_list,
                phase_distribution=raw_s.get("phase_distribution", {}),
                overall_style=str(raw_s.get("overall_style", "")),
                highlights=raw_s.get("highlights", []),
                improvements=raw_s.get("improvements", []),
            ),
        )

    def merge_segments(self, results: list[AnalysisResult]) -> AnalysisResult:
        if len(results) == 1:
            return results[0]
        all_segs: list[Segment] = []
        persons: dict[str, PersonSummary] = {}
        phase_dist: dict[str, int] = {}
        hl: list[str] = []
        imp: list[str] = []
        for r in results:
            all_segs.extend(r.segments)
            for p in r.summary.person_summary:
                persons.setdefault(p.role, p)
            for ph, sec in r.summary.phase_distribution.items():
                phase_dist[ph] = phase_dist.get(ph, 0) + sec
            hl.extend(r.summary.highlights)
            imp.extend(r.summary.improvements)
        total_sec = sum(s.duration_seconds for s in all_segs)
        return AnalysisResult(
            segments=all_segs,
            summary=Summary(
                total_duration=seconds_to_mmss(total_sec),
                total_segments=len(all_segs),
                person_summary=list(persons.values()),
                phase_distribution=phase_dist,
                overall_style="; ".join(r.summary.overall_style for r in results if r.summary.overall_style),
                highlights=hl[:5],
                improvements=imp[:5],
            ),
        )
