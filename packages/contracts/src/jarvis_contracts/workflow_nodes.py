"""Code-reviewed node definitions shared by publication, compiler and palette.

Config models contain data only. External services are injected into compiler
factories in later milestones; these definitions never perform external work.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from pydantic import Field, JsonValue

from jarvis_contracts.base import ContractModel
from jarvis_contracts.workflow import MAX_FANOUT, MAX_ITERATIONS, NodePolicy, WorkflowNodeType


class OrganizerConfig(ContractModel):
    summary_limit: int = Field(default=2000, ge=100, le=8000)


class ArchitectConfig(ContractModel):
    output_schema: Literal["task_plan.v1"] = "task_plan.v1"
    max_tasks: int = Field(default=100, ge=1, le=MAX_ITERATIONS)


class DispatchConfig(ContractModel):
    parallelism: Literal[1] = 1
    ready_order: Literal["dependency_then_task_key"] = "dependency_then_task_key"


class WorkerConfig(ContractModel):
    task_source: Literal["current_task"] = "current_task"


class VerifyConfig(ContractModel):
    commands_source: Literal["task.verification"] = "task.verification"
    stop_on_failure: Literal[True] = True


class ReviewerConfig(ContractModel):
    requires_repository_snapshot: Literal[True] = True


class IntegrateConfig(ContractModel):
    repository_source: Literal["project"] = "project"
    run_combined_gates: Literal[True] = True


class RouterConfig(ContractModel):
    pass


class FanoutConfig(ContractModel):
    children: tuple[str, ...] = Field(default=(), max_length=MAX_FANOUT)
    join_id: str = Field(default="join", min_length=1, max_length=80)
    max_fanout: int = Field(default=8, ge=1, le=MAX_FANOUT)
    cancellation_strategy: Literal["wait_all"] = "wait_all"


class JoinConfig(ContractModel):
    fanout_id: str = Field(default="fanout", min_length=1, max_length=80)
    require_all: Literal[True] = True


class ApprovalConfig(ContractModel):
    action_type: Literal["github.push_and_pr", "git.integrate", "worker.execute"] = (
        "github.push_and_pr"
    )
    expires_in_seconds: int | None = Field(default=None, ge=60, le=604800)


class PublishConfig(ContractModel):
    repository_source: Literal["project"] = "project"
    wait_for_ci: bool = True


class FinalizeConfig(ContractModel):
    outcome: Literal["derive", "failed", "blocked", "cancelled"] = "derive"


class NodeTypeDefinition(ContractModel):
    type: WorkflowNodeType
    config_schema: dict[str, JsonValue]
    default_config: dict[str, JsonValue]
    policy_schema: dict[str, JsonValue]
    required_capabilities: tuple[str, ...]
    input_channels: tuple[str, ...]
    output_channels: tuple[str, ...]
    external_behavior: bool


class NodeTypePage(ContractModel):
    items: tuple[NodeTypeDefinition, ...]


@dataclass(frozen=True)
class NodeDefinition:
    config_model: type[ContractModel]
    capabilities: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ("results",)
    outputs: tuple[str, ...] = ("results",)
    external: bool = False


NODE_DEFINITIONS = MappingProxyType(
    {
        WorkflowNodeType.ORGANIZER: NodeDefinition(OrganizerConfig, external=True),
        WorkflowNodeType.ARCHITECT: NodeDefinition(
            ArchitectConfig, outputs=("results", "tasks"), external=True
        ),
        WorkflowNodeType.TASK_DISPATCH: NodeDefinition(
            DispatchConfig, inputs=("tasks",), outputs=("results", "tasks")
        ),
        WorkflowNodeType.WORKER: NodeDefinition(WorkerConfig, ("code", "git"), external=True),
        WorkflowNodeType.VERIFY: NodeDefinition(
            VerifyConfig, ("tests",), outputs=("results", "verification"), external=True
        ),
        WorkflowNodeType.REVIEWER: NodeDefinition(
            ReviewerConfig, outputs=("results", "review"), external=True
        ),
        WorkflowNodeType.INTEGRATE: NodeDefinition(
            IntegrateConfig, outputs=("results", "tasks"), external=True
        ),
        WorkflowNodeType.ROUTER: NodeDefinition(RouterConfig),
        WorkflowNodeType.FANOUT: NodeDefinition(FanoutConfig, outputs=("expected_children",)),
        WorkflowNodeType.JOIN: NodeDefinition(
            JoinConfig, inputs=("expected_children", "child_results"), outputs=("results",)
        ),
        WorkflowNodeType.APPROVAL: NodeDefinition(
            ApprovalConfig, outputs=("results", "approval"), external=True
        ),
        WorkflowNodeType.GITHUB_PUBLISH: NodeDefinition(PublishConfig, external=True),
        WorkflowNodeType.FINALIZE: NodeDefinition(FinalizeConfig, outputs=("results", "final")),
    }
)


def node_type_page() -> NodeTypePage:
    return NodeTypePage(
        items=tuple(
            NodeTypeDefinition(
                type=kind,
                config_schema=item.config_model.model_json_schema(),
                default_config=item.config_model().model_dump(mode="json"),
                policy_schema=NodePolicy.model_json_schema(),
                required_capabilities=item.capabilities,
                input_channels=item.inputs,
                output_channels=item.outputs,
                external_behavior=item.external,
            )
            for kind, item in NODE_DEFINITIONS.items()
        )
    )
