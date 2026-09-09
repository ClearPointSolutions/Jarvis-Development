"""Public dependency diagnostics constructed only from server-owned messages."""


class RuntimeDependencyError(ValueError):
    """Safe actionable preflight failure, never a native provider exception."""


def safe_boundary_code(error: BaseException) -> str | None:
    """Return a boundary error's curated constant, or None when there is none.

    Worker and provider boundaries raise with a fixed identifier such as
    `source_import_tree_mismatch`. That constant is safe to log and to show an
    operator, unlike native exception text, which can carry credentials, model
    output or command output. Requiring a bare identifier keeps anything with a
    URL, path, whitespace or punctuation out of the safe channel.
    """

    code = getattr(error, "code", None)
    if isinstance(code, str) and code.isidentifier() and len(code) <= 120:
        return code
    return None
