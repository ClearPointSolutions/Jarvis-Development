"""Reusable templates never select another project's private repository."""

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from jarvis_contracts.verification import VerificationCommand
from jarvis_contracts.workers import WorkerProject
from jarvis_orchestrator.runtime.configuration import (
    RealRuntimeConfiguration,
    RepositoryBinding,
    VerificationIsolation,
)


def test_reusable_workflow_requires_exact_project_binding(tmp_path: Path) -> None:
    first, second, workflow = uuid4(), uuid4(), uuid4()

    def binding(project_id: UUID, slug: str) -> RepositoryBinding:
        return RepositoryBinding.model_validate(
            {
                "worker_revision_id": str(uuid4()),
                "project": WorkerProject.model_validate(
                    {
                        "project_id": project_id,
                        "repository_id": uuid4(),
                        "slug": slug,
                        "workspace_root": "/workspaces/" + slug,
                        "branch": "main",
                        "base_sha": "a" * 40,
                    }
                ),
                "combined_commands": (VerificationCommand(argv=("pytest",)),),
            }
        )

    a, b = binding(first, "first"), binding(second, "second")
    settings = RealRuntimeConfiguration(
        workflows={workflow: a},
        source_root=tmp_path,
        verification_isolation=VerificationIsolation(
            broker_argv=(sys.executable,), image_id="sha256:" + "a" * 64
        ),
        executables={},
        executable_path="",
        git_executable=Path(sys.executable),
        ssh_executable=Path(sys.executable),
        git_author_name="Fixture",
        git_author_email="fixture@localhost",
    )
    assert settings.repository_binding(first, workflow) == a
    with pytest.raises(ValueError, match="project does not match"):
        settings.repository_binding(second, workflow)
    settings = settings.model_copy(update={"project_workflows": {second: {workflow: b}}})
    assert settings.repository_binding(second, workflow) == b
    assert settings.repository_binding(first, workflow) == a
    with pytest.raises(ValueError, match="no server-side"):
        settings.repository_binding(first, uuid4())
