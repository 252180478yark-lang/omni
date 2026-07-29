"""Feature health dependency and external delivery-attestation adapters."""

from __future__ import annotations

import json

from app.schemas.system_graph import EvidenceState, GraphState, HealthState, SourceStatus
from app.services.system_graph.canonical import evidence_ref, make_node_id
from app.services.system_graph.collectors.base import (
    CollectorContext,
    CollectorOutput,
    observed_edge,
    observed_node,
    run_isolated_json,
    source_result,
)


_HEALTH_CODE = r'''
import asyncio
import inspect
import json
try:
    from app.services import health_registry
except Exception:
    print(json.dumps({"available": False}, sort_keys=True))
    raise SystemExit(0)

async def main():
    for name in ("export_graph_facts", "graph_snapshot", "list_health_registrations"):
        candidate = getattr(health_registry, name, None)
        if not callable(candidate):
            continue
        try:
            value = candidate()
            if inspect.isawaitable(value):
                value = await value
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            print(json.dumps({"available": True, "items": value}, sort_keys=True, default=str))
            return
        except TypeError:
            continue
        except Exception:
            print(json.dumps({"available": False}, sort_keys=True))
            return
    print(json.dumps({"available": False}, sort_keys=True))

asyncio.run(main())
'''


_HEALTH_VALUES = {item.value for item in HealthState}


def _health_items(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or payload.get("available") is not True:
        return []
    value = payload.get("items")
    if isinstance(value, dict):
        if isinstance(value.get("features"), list):
            value = value["features"]
        elif isinstance(value.get("registrations"), list):
            value = value["registrations"]
        else:
            value = [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class HealthDeliveryCollector:
    collector_id = "health.definition"
    version = "1"
    health_dynamic_id = "health.runtime"
    delivery_id = "delivery.external"

    def collect(self, context: CollectorContext) -> CollectorOutput:
        output = CollectorOutput()
        for definition in context.definitions:
            definition_path = context.repo / definition.source_path
            coordinate = [
                evidence_ref(context.repo, definition_path, 1, definition.feature_id)
            ]
            feature_id = make_node_id("feature", definition.feature_id)
            for dependency in definition.dependencies:
                if not dependency.ref.startswith("health_registration:"):
                    continue
                key = dependency.ref.split(":", 1)[1]
                health_id = make_node_id("health_registration", key)
                output.nodes.append(
                    observed_node(
                        "health_registration",
                        key,
                        label=f"Health {key}",
                        collector_id=self.collector_id,
                        evidence=coordinate,
                        attrs={"required": dependency.required},
                    )
                )
                output.edges.append(
                    observed_edge(
                        "depends_on",
                        feature_id,
                        health_id,
                        collector_id=self.collector_id,
                        evidence=coordinate,
                        attrs={"required": dependency.required},
                    )
                )
        output.source_results.append(
            source_result(self.collector_id, self.version, SourceStatus.SUCCESS)
        )

        health_payload, health_result = run_isolated_json(
            context,
            collector_id=self.health_dynamic_id,
            version=self.version,
            code=_HEALTH_CODE,
        )
        items = _health_items(health_payload)
        if health_result.status == SourceStatus.SUCCESS and not items:
            health_result = source_result(
                self.health_dynamic_id,
                self.version,
                SourceStatus.UNKNOWN,
                "health_adapter_unavailable",
                retryable=True,
            )
        output.source_results.append(health_result)
        health_module = (
            context.repo
            / "services"
            / "knowledge-engine"
            / "app"
            / "services"
            / "health_registry.py"
        )
        if health_result.status == SourceStatus.SUCCESS and health_module.exists():
            for item in items:
                ref = str(item.get("ref") or item.get("health_id") or item.get("service_id") or "")
                status = str(item.get("status") or item.get("availability") or "unknown")
                if not ref or status not in _HEALTH_VALUES:
                    continue
                key = ref.split("health_registration:", 1)[-1]
                node = observed_node(
                    "health_registration",
                    key,
                    label=f"Health {key}",
                    collector_id=self.health_dynamic_id,
                    evidence=[evidence_ref(context.repo, health_module, 1, key)],
                    attrs={"runtime_confirmed": True},
                )
                node = node.model_copy(
                    update={
                        "state": GraphState(
                            health=HealthState(status), evidence=EvidenceState.BOTH
                        )
                    }
                )
                output.nodes.append(node)

        self._collect_delivery(context, output)
        return output

    def _collect_delivery(self, context: CollectorContext, output: CollectorOutput) -> None:
        path = context.delivery_attestation
        if path is None:
            output.source_results.append(
                source_result(
                    self.delivery_id,
                    self.version,
                    SourceStatus.UNKNOWN,
                    "attestation_not_supplied",
                    retryable=True,
                )
            )
            return
        try:
            resolved = path.resolve()
            resolved.relative_to(context.repo.resolve())
            raw = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("attestation must be an object")
            if (
                raw.get("schema_version") != 1
                or raw.get("authority") != "ci_attestation"
                or raw.get("status") != "COMPLETE"
            ):
                raise ValueError("unsupported attestation")
            delivered_commit = str(raw.get("delivered_commit", ""))
            if len(delivered_commit) < 40:
                raise ValueError("invalid delivered commit")
            coordinate = [evidence_ref(context.repo, resolved, 1, delivered_commit)]
            receipt_id = make_node_id("delivery_receipt", delivered_commit)
            output.nodes.append(
                observed_node(
                    "delivery_receipt",
                    delivered_commit,
                    label=f"Delivery {delivered_commit[:12]}",
                    collector_id=self.delivery_id,
                    evidence=coordinate,
                    attrs={"authority": "ci_attestation", "status": "COMPLETE"},
                )
            )
            contracts = raw.get("contracts")
            for contract in contracts if isinstance(contracts, list) else []:
                if not isinstance(contract, dict) or not contract.get("change_id"):
                    continue
                change_id = str(contract["change_id"])
                change_node_id = make_node_id("delivery_change", change_id)
                output.nodes.append(
                    observed_node(
                        "delivery_change",
                        change_id,
                        label=f"Change {change_id}",
                        collector_id=self.delivery_id,
                        evidence=coordinate,
                    )
                )
                output.edges.append(
                    observed_edge(
                        "delivers",
                        receipt_id,
                        change_node_id,
                        collector_id=self.delivery_id,
                        evidence=coordinate,
                    )
                )
            output.source_results.append(
                source_result(self.delivery_id, self.version, SourceStatus.SUCCESS)
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            output.source_results.append(
                source_result(
                    self.delivery_id,
                    self.version,
                    SourceStatus.UNKNOWN,
                    "attestation_unavailable",
                    retryable=True,
                )
            )
