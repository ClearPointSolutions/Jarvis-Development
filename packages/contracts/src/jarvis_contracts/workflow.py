"""Versioned declarative workflow specification contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from jarvis_contracts.base import ContractModel, sha256_digest
from jarvis_contracts.ids import WorkflowTemplateId, WorkflowVersionId


class WorkflowNodeType(StrEnum):
    ORGANIZER = "organizer"
    ARCHITECT = "architect"
    TASK_DISPATCH = "task_dispatch"
    WORKER = "worker"
    VERIFY = "verify"
    REVIEWER = "reviewer"
    INTEGRATE = "integrate"
    ROUTER = "router"
    FANOUT = "fanout"
    JOIN = "join"
    APPROVAL = "approval"
    GITHUB_PUBLISH = "github_publish"
    FINALIZE = "finalize"


class WorkflowEdgeKind(StrEnum):
    ALWAYS = "always"
    ON_RESULT = "on_result"
    RETRY = "retry"
    ITERATE = "iterate"


class PredicateOperator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    EXISTS = "exists"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    AND = "and"
    OR = "or"
    NOT = "not"


class Predicate(ContractModel):
    op: PredicateOperator
    path: str | None = Field(default=None, pattern=r"^\$\.[A-Za-z0-9_.-]+$")
    value: JsonValue | None = None
    args: tuple[Predicate, ...] = ()

    @model_validator(mode="after")
    def validate_shape(self) -> Predicate:
        logical = {PredicateOperator.AND, PredicateOperator.OR, PredicateOperator.NOT}
        if self.op in logical:
            required = 1 if self.op is PredicateOperator.NOT else 2
            if len(self.args) < required or self.path is not None:
                raise ValueError(f"{self.op.value} requires {required} predicate argument(s)")
        elif self.path is None or self.args:
            raise ValueError(f"{self.op.value} requires a path and no predicate arguments")
        if self.op is PredicateOperator.EXISTS and self.value is not None:
            raise ValueError("exists does not accept a comparison value")
        return self


class ApprovalPolicy(ContractModel):
    required_grant_from: str | None = None
    action_type: str | None = None
    expires_in_seconds: Annotated[int, Field(gt=0)] | None = None


class NodePolicy(ContractModel):
    worker_selector: str | None = None
    model_route_ref: str | None = None
    retry_policy_ref: str | None = None
    permission_policy_ref: str | None = None
    verification: dict[str, JsonValue] | None = None
    approval: ApprovalPolicy | None = None
    timeout_seconds: Annotated[int, Field(gt=0, le=86_400)] | None = None
    max_concurrency: Annotated[int, Field(gt=0, le=1_000)] | None = None
    accepts_runtime_instructions: bool = False


class WorkflowNode(ContractModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    type: WorkflowNodeType
    label: str = Field(min_length=1, max_length=160)
    config: dict[str, JsonValue]
    policy: NodePolicy = Field(default_factory=NodePolicy)


class WorkflowEdge(ContractModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    source: str = Field(alias="from", min_length=1, max_length=80)
    target: str = Field(alias="to", min_length=1, max_length=80)
    kind: WorkflowEdgeKind
    when: Predicate | None = None
    priority: int = 0
    fallback: bool = False
    retry_class: str | None = None
    iteration_key: str | None = None
    progress_path: str | None = Field(default=None, pattern=r"^\$\.[A-Za-z0-9_.-]+$")
    max_iterations: Annotated[int, Field(gt=0, le=10_000)] | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> WorkflowEdge:
        if self.kind is WorkflowEdgeKind.ALWAYS and self.when is not None:
            raise ValueError("always edges cannot define a predicate")
        if self.kind is WorkflowEdgeKind.RETRY and not self.retry_class:
            raise ValueError("retry edges require retry_class")
        if self.kind is WorkflowEdgeKind.ITERATE and (
            not self.iteration_key or not self.progress_path or self.max_iterations is None
        ):
            raise ValueError(
                "iterate edges require iteration_key, progress_path, and max_iterations"
            )
        return self


class WorkflowOutputs(ContractModel):
    result_path: str = Field(pattern=r"^\$\.[A-Za-z0-9_.-]+$")


class WorkflowSpec(ContractModel):
    spec_version: Literal["1.0"] = "1.0"
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2_000)
    entrypoint: str = Field(min_length=1, max_length=80)
    defaults: NodePolicy = Field(default_factory=NodePolicy)
    nodes: tuple[WorkflowNode, ...] = Field(min_length=1, max_length=500)
    edges: tuple[WorkflowEdge, ...] = Field(max_length=2_000)
    outputs: WorkflowOutputs

    @model_validator(mode="after")
    def validate_references(self) -> WorkflowSpec:
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("workflow edge IDs must be unique")
        if self.entrypoint not in set(node_ids):
            raise ValueError("entrypoint must reference a workflow node")
        missing = {
            endpoint
            for edge in self.edges
            for endpoint in (edge.source, edge.target)
            if endpoint not in set(node_ids)
        }
        if missing:
            raise ValueError(f"edges reference unknown nodes: {sorted(missing)}")
        return self

    @property
    def content_hash(self) -> str:
        return sha256_digest(self)


class WorkflowVersionContract(ContractModel):
    id: WorkflowVersionId
    workflow_template_id: WorkflowTemplateId
    version: Annotated[int, Field(gt=0)]
    spec_version: Literal["1.0"] = "1.0"
    compiler_version: str = Field(min_length=1, max_length=40)
    spec: WorkflowSpec
    layout: dict[str, JsonValue]
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    published: bool

    @model_validator(mode="after")
    def verify_hash(self) -> WorkflowVersionContract:
        if self.content_hash != self.spec.content_hash:
            raise ValueError("workflow content_hash does not match canonical executable spec")
        return self


Predicate.model_rebuild()
