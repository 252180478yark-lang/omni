"""Static SQL migration/table/view collector; it never connects to a database."""

from __future__ import annotations

import re

from app.schemas.system_graph import SourceStatus
from app.services.system_graph.canonical import evidence_ref, make_node_id
from app.services.system_graph.collectors.base import (
    CollectorContext,
    CollectorOutput,
    observed_edge,
    observed_node,
    source_result,
)


_DDL_RE = re.compile(
    r"(?im)^\s*(CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)|ALTER\s+TABLE)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*)"
)


def _wanted(context: CollectorContext) -> set[str]:
    refs: set[str] = set()
    for definition in context.definitions:
        for edge in definition.expected_edges:
            refs.update((edge.source, edge.target))
    return refs


class MigrationCollector:
    collector_id = "migration.static"
    version = "1"

    def collect(self, context: CollectorContext) -> CollectorOutput:
        output = CollectorOutput()
        wanted = _wanted(context)
        migration_root = context.repo / "migrations"
        if not migration_root.exists():
            output.source_results.append(
                source_result(
                    self.collector_id,
                    self.version,
                    SourceStatus.UNKNOWN,
                    "migration_root_missing",
                )
            )
            return output

        for path in sorted(migration_root.glob("*.sql"), key=lambda item: item.name):
            migration_key = path.stem
            migration_id = make_node_id("migration", migration_key)
            text = path.read_text(encoding="utf-8")
            matches = list(_DDL_RE.finditer(text))
            relevant = [
                match
                for match in matches
                if make_node_id(
                    "view" if "VIEW" in match.group(1).upper() else "table", match.group(2)
                )
                in wanted
            ]
            if migration_id not in wanted and not relevant:
                continue
            migration_evidence = [evidence_ref(context.repo, path, 1, migration_key)]
            output.nodes.append(
                observed_node(
                    "migration",
                    migration_key,
                    label=f"Migration {migration_key}",
                    collector_id=self.collector_id,
                    evidence=migration_evidence,
                )
            )
            for match in relevant:
                statement = match.group(1).upper()
                entity = match.group(2)
                kind = "view" if "VIEW" in statement else "table"
                entity_id = make_node_id(kind, entity)
                line = text.count("\n", 0, match.start()) + 1
                coordinate = [evidence_ref(context.repo, path, line, entity)]
                output.nodes.append(
                    observed_node(
                        kind,
                        entity,
                        label=f"{kind.title()} {entity}",
                        collector_id=self.collector_id,
                        evidence=coordinate,
                    )
                )
                relation = "alters" if statement.startswith("ALTER") else "creates"
                output.edges.append(
                    observed_edge(
                        relation,
                        migration_id,
                        entity_id,
                        collector_id=self.collector_id,
                        evidence=coordinate,
                    )
                )

        output.source_results.append(
            source_result(self.collector_id, self.version, SourceStatus.SUCCESS)
        )
        return output
