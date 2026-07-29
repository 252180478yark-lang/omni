"""Versioned static catalogs plus isolated OpenAPI and MCP catalog confirmation."""

from __future__ import annotations

import re

from app.schemas.system_graph import SourceStatus
from app.services.system_graph.canonical import evidence_ref, make_node_id
from app.services.system_graph.collectors.base import (
    CollectorContext,
    CollectorOutput,
    observed_node,
    run_isolated_json,
    source_result,
)


_OPENAPI_CODE = r'''
import json
from app.main import app
schema = app.openapi()
operations = []
for path, item in schema.get("paths", {}).items():
    for method, operation in item.items():
        if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
            operations.append({"method": method.upper(), "path": path, "operation_id": operation.get("operationId", "")})
print(json.dumps(sorted(operations, key=lambda value: (value["method"], value["path"])), sort_keys=True))
'''

_MCP_CODE = r'''
import asyncio
import json
from app.mcp.server import mcp
async def main():
    tools = await mcp.list_tools()
    names = sorted(getattr(tool, "name", str(tool)) for tool in tools)
    print(json.dumps(names, sort_keys=True))
asyncio.run(main())
'''


def _expected(context: CollectorContext) -> set[str]:
    refs: set[str] = set()
    for definition in context.definitions:
        for edge in definition.expected_edges:
            refs.update((edge.source, edge.target))
        for check in definition.checks:
            refs.add(check.verifies)
    return refs


class CatalogCollector:
    collector_id = "catalog.static"
    version = "1"
    openapi_id = "catalog.openapi"
    mcp_id = "catalog.mcp"

    def collect(self, context: CollectorContext) -> CollectorOutput:
        output = CollectorOutput()
        expected = _expected(context)

        # Static external-source facts are only emitted for explicitly referenced catalog keys.
        catalog_root = context.repo / "services" / "scout-agent" / "catalog"
        for ref in sorted(value for value in expected if value.startswith("external_source:")):
            key = ref.split(":", 1)[1]
            for path in sorted(catalog_root.glob("*.json")) if catalog_root.exists() else []:
                text = path.read_text(encoding="utf-8")
                match = re.search(rf"(?m)[\"']{re.escape(key)}[\"']", text)
                if match is None:
                    continue
                output.nodes.append(
                    observed_node(
                        "external_source",
                        key,
                        label=f"Source {key}",
                        collector_id=self.collector_id,
                        evidence=[
                            evidence_ref(
                                context.repo,
                                path,
                                text.count("\n", 0, match.start()) + 1,
                                key,
                            )
                        ],
                    )
                )
                break

        metric_registry = (
            context.repo
            / "services"
            / "knowledge-engine"
            / "app"
            / "services"
            / "metric_registry.py"
        )
        if metric_registry.exists():
            text = metric_registry.read_text(encoding="utf-8")
            for ref in sorted(value for value in expected if value.startswith("metric:")):
                key = ref.split(":", 1)[1]
                match = re.search(rf"(?m)[\"']{re.escape(key)}[\"']\s*:", text)
                if match is None:
                    continue
                output.nodes.append(
                    observed_node(
                        "metric",
                        key,
                        label=f"Metric {key}",
                        collector_id=self.collector_id,
                        evidence=[
                            evidence_ref(
                                context.repo,
                                metric_registry,
                                text.count("\n", 0, match.start()) + 1,
                                key,
                            )
                        ],
                    )
                )

        output.source_results.append(
            source_result(self.collector_id, self.version, SourceStatus.SUCCESS)
        )

        openapi_payload, openapi_result = run_isolated_json(
            context,
            collector_id=self.openapi_id,
            version=self.version,
            code=_OPENAPI_CODE,
        )
        output.source_results.append(openapi_result)
        if isinstance(openapi_payload, list):
            main_path = (
                context.repo / "services" / "knowledge-engine" / "app" / "main.py"
            )
            for item in openapi_payload:
                if not isinstance(item, dict):
                    continue
                method = str(item.get("method", "")).upper()
                path = str(item.get("path", ""))
                key = f"{method}:{path}"
                node_id = make_node_id("rest_operation", key)
                if node_id not in expected or not main_path.exists():
                    continue
                output.nodes.append(
                    observed_node(
                        "rest_operation",
                        key,
                        label=f"REST {method} {path}",
                        collector_id=self.openapi_id,
                        evidence=[evidence_ref(context.repo, main_path, 112, "app.openapi")],
                        attrs={"openapi_confirmed": True},
                    )
                )

        mcp_payload, mcp_result = run_isolated_json(
            context,
            collector_id=self.mcp_id,
            version=self.version,
            code=_MCP_CODE,
        )
        output.source_results.append(mcp_result)
        if isinstance(mcp_payload, list):
            server_path = (
                context.repo
                / "services"
                / "knowledge-engine"
                / "app"
                / "mcp"
                / "server.py"
            )
            for name in sorted(str(value) for value in mcp_payload):
                node_id = make_node_id("mcp_tool", name)
                if node_id not in expected or not server_path.exists():
                    continue
                output.nodes.append(
                    observed_node(
                        "mcp_tool",
                        name,
                        label=f"MCP {name}",
                        collector_id=self.mcp_id,
                        evidence=[evidence_ref(context.repo, server_path, 26, "mcp.list_tools")],
                        attrs={"catalog_confirmed": True},
                    )
                )
        return output
