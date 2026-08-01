"""Static Next.js page, BFF operation and literal fetch collector."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.system_graph import SourceStatus
from app.services.system_graph.canonical import evidence_ref, make_node_id, normalize_route
from app.services.system_graph.collectors.base import (
    CollectorContext,
    CollectorOutput,
    observed_edge,
    observed_node,
    source_result,
)


_FETCH_RE = re.compile(
    r"fetch\(\s*(?P<quote>['\"`])(?P<url>/api/.*?)(?P=quote)", re.DOTALL
)
_EXPORT_RE = re.compile(
    r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\("
)
_KNOWLEDGE_RE = re.compile(
    r"\$\{base\.knowledge\}(?P<path>/api/v1[^`'\"\s,)]*)"
)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _route_from_file(api_root: Path, path: Path) -> str:
    relative = path.relative_to(api_root).parent.as_posix()
    relative = re.sub(r"\[\[\.\.\.([^]]+)\]\]", r"{\1*}", relative)
    relative = re.sub(r"\[\.\.\.([^]]+)\]", r"{\1*}", relative)
    relative = re.sub(r"\[([^]]+)\]", r"{\1}", relative)
    return normalize_route("/api/" + relative)


def _method_after_fetch(text: str, match_end: int) -> str:
    tail = text[match_end : match_end + 280]
    match = re.search(r"method\s*:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]", tail)
    return match.group(1) if match else "GET"


class FrontendCollector:
    collector_id = "frontend.static"
    version = "1"

    def collect(self, context: CollectorContext) -> CollectorOutput:
        output = CollectorOutput()
        api_root = context.repo / "frontend" / "src" / "app" / "api"
        route_index: dict[tuple[str, str], tuple[Path, int, str]] = {}
        if api_root.exists():
            for route_file in sorted(api_root.rglob("route.ts")):
                text = route_file.read_text(encoding="utf-8")
                route = _route_from_file(api_root, route_file)
                for match in _EXPORT_RE.finditer(text):
                    route_index[(match.group(1), route)] = (route_file, _line(text, match.start()), route)

        definitions = list(context.definitions)
        for definition in context.definitions:
            for alias in definition.aliases:
                definitions.append(
                    definition.model_copy(
                        update={
                            "routes": definition.routes.model_copy(
                                update={"canonical": alias.href, "visible": False}
                            ),
                            "aliases": [],
                        }
                    )
                )

        for definition in definitions:
            definition_path = context.repo / definition.source_path
            definition_evidence = [
                evidence_ref(context.repo, definition_path, 1, definition.feature_id)
            ]
            feature_id = make_node_id("feature", definition.feature_id)
            output.nodes.append(
                observed_node(
                    "feature",
                    definition.feature_id,
                    label=definition.title,
                    collector_id=self.collector_id,
                    evidence=definition_evidence,
                    attrs={"domain": definition.domain, "owner": definition.owner.id},
                    lifecycle=definition.lifecycle,
                )
            )

            route = definition.routes.canonical
            page_relative = route.strip("/") or "page"
            page_path = (
                context.repo
                / "frontend"
                / "src"
                / "app"
                / page_relative
                / "page.tsx"
            )
            if route == "/":
                page_path = context.repo / "frontend" / "src" / "app" / "page.tsx"
            if not page_path.exists():
                continue
            page_text = page_path.read_text(encoding="utf-8")
            page_evidence = [evidence_ref(context.repo, page_path, 1, route)]
            ui_id = make_node_id("ui_route", route)
            output.nodes.append(
                observed_node(
                    "ui_route",
                    route,
                    label=f"UI {route}",
                    collector_id=self.collector_id,
                    evidence=page_evidence,
                    attrs={"visible": definition.routes.visible},
                    lifecycle=definition.lifecycle,
                )
            )
            output.edges.append(
                observed_edge(
                    "declares",
                    feature_id,
                    ui_id,
                    collector_id=self.collector_id,
                    evidence=definition_evidence,
                )
            )

            for match in _FETCH_RE.finditer(page_text):
                fetched = match.group("url")
                fetched = re.sub(r"\$\{[^}]+\}", "", fetched)
                fetched_route = normalize_route(fetched)
                method = _method_after_fetch(page_text, match.end())
                indexed = route_index.get((method, fetched_route))
                if indexed is None:
                    indexed = next(
                        (
                            value
                            for (candidate_method, candidate_route), value in route_index.items()
                            if candidate_method == method
                            and "{path*}" in candidate_route
                            and fetched_route.startswith(candidate_route.split("/{path*}", 1)[0] + "/")
                        ),
                        None,
                    )
                if indexed is None:
                    continue
                bff_path, bff_line, indexed_route = indexed
                bff_key = f"{method}:{fetched_route}"
                bff_id = make_node_id("bff_operation", bff_key)
                bff_evidence = [
                    evidence_ref(context.repo, bff_path, bff_line, f"{method} {fetched_route}")
                ]
                output.nodes.append(
                    observed_node(
                        "bff_operation",
                        bff_key,
                        label=f"BFF {method} {fetched_route}",
                        collector_id=self.collector_id,
                        evidence=bff_evidence,
                    )
                )
                call_evidence = [
                    evidence_ref(
                        context.repo,
                        page_path,
                        _line(page_text, match.start()),
                        f"fetch {method} {fetched_route}",
                    )
                ]
                output.edges.append(
                    observed_edge(
                        "calls",
                        ui_id,
                        bff_id,
                        collector_id=self.collector_id,
                        evidence=call_evidence,
                    )
                )

                bff_text = bff_path.read_text(encoding="utf-8")
                exports = list(_EXPORT_RE.finditer(bff_text))
                for index, export in enumerate(exports):
                    if export.group(1) != method:
                        continue
                    end = exports[index + 1].start() if index + 1 < len(exports) else len(bff_text)
                    function_text = bff_text[export.start() : end]
                    delegated = re.search(r"\bproxy\(", function_text) is not None
                    outbound_text = bff_text if delegated else function_text
                    outbound_base = 0 if delegated else export.start()
                    for outbound in _KNOWLEDGE_RE.finditer(outbound_text):
                        raw_path = outbound.group("path")
                        if "${" in raw_path and "{path*}" in indexed_route:
                            bff_prefix = indexed_route.split("/{path*}", 1)[0]
                            suffix = fetched_route.removeprefix(bff_prefix)
                            raw_path = raw_path.split("${", 1)[0].rstrip("/") + suffix
                        else:
                            raw_path = raw_path.split("${", 1)[0]
                        rest_route = normalize_route(raw_path)
                        rest_key = f"{method}:{rest_route}"
                        rest_id = make_node_id("rest_operation", rest_key)
                        absolute_offset = outbound_base + outbound.start()
                        edge_evidence = [
                            evidence_ref(
                                context.repo,
                                bff_path,
                                _line(bff_text, absolute_offset),
                                f"proxy {method} {rest_route}",
                            )
                        ]
                        output.edges.append(
                            observed_edge(
                                "proxies_to",
                                bff_id,
                                rest_id,
                                collector_id=self.collector_id,
                                evidence=edge_evidence,
                            )
                        )

        output.source_results.append(
            source_result(self.collector_id, self.version, SourceStatus.SUCCESS)
        )
        return output
