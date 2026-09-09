"""Public dependency diagnostics constructed only from server-owned messages."""


class RuntimeDependencyError(ValueError):
    """Safe actionable preflight failure, never a native provider exception."""
