"""AST-backed FastAPI, service, MCP and pytest fact collector."""

from __future__ import annotations

import ast
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


_TABLE_RE = re.compile(
    r"(?i)\b(FROM|JOIN|INTO|UPDATE|DELETE\s+FROM)\s+([a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*)"
)
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _expected_refs(context: CollectorContext) -> set[str]:
    refs: set[str] = set()
    for definition in context.definitions:
        for edge in definition.expected_edges:
            refs.add(edge.source)
            refs.add(edge.target)
        for check in definition.checks:
            refs.add(check.verifies)
            refs.add(make_node_id("test", check.target))
        for dependency in definition.dependencies:
            refs.add(dependency.ref)
    return refs


def _module_path(service_root: Path, module: str) -> Path:
    return service_root / (module.replace(".", "/") + ".py")


def _imports(tree: ast.AST) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[-1]] = alias.name
    return found


def _router_prefix(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        name = value.func.id if isinstance(value.func, ast.Name) else ""
        if name != "APIRouter":
            continue
        for keyword in value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return ""


def _decorated_route(function: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str, str] | None:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in _HTTP_METHODS or not decorator.args:
            continue
        if isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
            return method.upper(), decorator.args[0].value
    return None


def _is_mcp_tool(function: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for decorator in function.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call else decorator
        if isinstance(target, ast.Name) and target.id == "tool_with_audit":
            return True
    return False


def _function_by_name(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    return None


def _sql_facts(
    *,
    context: CollectorContext,
    output: CollectorOutput,
    path: Path,
    text: str,
    function: ast.AsyncFunctionDef | ast.FunctionDef,
    source_id: str,
    wanted: set[str],
    collector_id: str,
) -> None:
    segment = ast.get_source_segment(text, function) or ""
    segment_start = function.lineno
    for match in _TABLE_RE.finditer(segment):
        table = match.group(2)
        table_id = make_node_id("table", table)
        if table_id not in wanted:
            continue
        line = segment_start + segment.count("\n", 0, match.start())
        coordinate = [evidence_ref(context.repo, path, line, function.name)]
        output.nodes.append(
            observed_node(
                "table",
                table,
                label=f"Table {table}",
                collector_id=collector_id,
                evidence=coordinate,
            )
        )
        verb = match.group(1).upper().replace(" ", "")
        relation = "reads" if verb in {"FROM", "JOIN"} else "writes"
        output.edges.append(
            observed_edge(
                relation,
                source_id,
                table_id,
                collector_id=collector_id,
                evidence=coordinate,
            )
        )


class PythonGraphCollector:
    collector_id = "python.static"
    version = "1"

    def collect(self, context: CollectorContext) -> CollectorOutput:
        output = CollectorOutput()
        wanted = _expected_refs(context)
        service_root = context.repo / "services" / "knowledge-engine"
        app_root = service_root / "app"

        # FastAPI operations are facts only when the decorator and function are present.
        for path in sorted((app_root / "routers").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError:
                continue
            prefix = _router_prefix(tree)
            imported = _imports(tree)
            for function in tree.body:
                if not isinstance(function, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                route = _decorated_route(function)
                if route is None:
                    continue
                method, suffix = route
                full_route = normalize_route(prefix + suffix)
                key = f"{method}:{full_route}"
                rest_id = make_node_id("rest_operation", key)
                if rest_id not in wanted:
                    continue
                rest_evidence = [
                    evidence_ref(context.repo, path, function.lineno, function.name)
                ]
                output.nodes.append(
                    observed_node(
                        "rest_operation",
                        key,
                        label=f"REST {method} {full_route}",
                        collector_id=self.collector_id,
                        evidence=rest_evidence,
                        attrs={"symbol": function.name},
                    )
                )
                for call in ast.walk(function):
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                        continue
                    qualified = imported.get(call.func.id, "")
                    if not qualified.startswith("app.services."):
                        continue
                    service_id = make_node_id("service_symbol", qualified)
                    if service_id not in wanted:
                        continue
                    module_name, symbol = qualified.rsplit(".", 1)
                    service_path = _module_path(service_root, module_name)
                    if not service_path.exists():
                        continue
                    service_text = service_path.read_text(encoding="utf-8")
                    service_tree = ast.parse(service_text, filename=str(service_path))
                    service_function = _function_by_name(service_tree, symbol)
                    if service_function is None:
                        continue
                    service_evidence = [
                        evidence_ref(
                            context.repo, service_path, service_function.lineno, qualified
                        )
                    ]
                    output.nodes.append(
                        observed_node(
                            "service_symbol",
                            qualified,
                            label=qualified,
                            collector_id=self.collector_id,
                            evidence=service_evidence,
                        )
                    )
                    output.edges.append(
                        observed_edge(
                            "invokes",
                            rest_id,
                            service_id,
                            collector_id=self.collector_id,
                            evidence=[evidence_ref(context.repo, path, call.lineno, call.func.id)],
                        )
                    )
                    _sql_facts(
                        context=context,
                        output=output,
                        path=service_path,
                        text=service_text,
                        function=service_function,
                        source_id=service_id,
                        wanted=wanted,
                        collector_id=self.collector_id,
                    )

        # Expected service symbols not reached by a REST operation still remain verifiable facts.
        for ref in sorted(value for value in wanted if value.startswith("service_symbol:")):
            qualified = ref.split(":", 1)[1]
            module_name, symbol = qualified.rsplit(".", 1)
            path = _module_path(service_root, module_name)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            function = _function_by_name(tree, symbol)
            if function is None:
                continue
            output.nodes.append(
                observed_node(
                    "service_symbol",
                    qualified,
                    label=qualified,
                    collector_id=self.collector_id,
                    evidence=[evidence_ref(context.repo, path, function.lineno, qualified)],
                )
            )
            _sql_facts(
                context=context,
                output=output,
                path=path,
                text=text,
                function=function,
                source_id=ref,
                wanted=wanted,
                collector_id=self.collector_id,
            )

        # MCP tools are derived from actual decorators, not a name-only file guess.
        tools_root = app_root / "mcp" / "tools"
        for path in sorted(tools_root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError:
                continue
            for function in tree.body:
                if not isinstance(function, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                if not _is_mcp_tool(function):
                    continue
                tool_id = make_node_id("mcp_tool", function.name)
                if tool_id not in wanted:
                    continue
                output.nodes.append(
                    observed_node(
                        "mcp_tool",
                        function.name,
                        label=f"MCP {function.name}",
                        collector_id=self.collector_id,
                        evidence=[evidence_ref(context.repo, path, function.lineno, function.name)],
                    )
                )
                _sql_facts(
                    context=context,
                    output=output,
                    path=path,
                    text=text,
                    function=function,
                    source_id=tool_id,
                    wanted=wanted,
                    collector_id=self.collector_id,
                )

        # Tests are connected by explicit FeatureDefinition checks, never name similarity.
        for definition in context.definitions:
            for check in definition.checks:
                if "::" not in check.target:
                    continue
                relative, symbol = check.target.split("::", 1)
                path = context.repo / relative
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=str(path))
                function = _function_by_name(tree, symbol)
                if function is None:
                    continue
                test_id = make_node_id("test", check.target)
                coordinate = [evidence_ref(context.repo, path, function.lineno, symbol)]
                output.nodes.append(
                    observed_node(
                        "test",
                        check.target,
                        label=f"Test {symbol}",
                        collector_id=self.collector_id,
                        evidence=coordinate,
                        attrs={"check_id": check.check_id, "required": check.required},
                    )
                )
                output.edges.append(
                    observed_edge(
                        "verifies",
                        test_id,
                        check.verifies,
                        collector_id=self.collector_id,
                        evidence=coordinate,
                    )
                )

        output.source_results.append(
            source_result(self.collector_id, self.version, SourceStatus.SUCCESS)
        )
        return output
