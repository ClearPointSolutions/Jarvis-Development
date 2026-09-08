"""Best-effort bounded summaries. Exit status remains the verdict authority."""

import re

from jarvis_contracts.verification import ParsedVerification, ParserKind

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def parse_output(kind: ParserKind, output: str, exit_code: int | None) -> ParsedVerification:
    text = _ANSI.sub("", output[-65536:])
    counts: dict[str, int] = {}
    if kind in {"pytest", "vitest"}:
        # Use the last tool summary, never aggregate repeated progress/failure lines.
        for line in reversed(text.splitlines()):
            if kind == "vitest" and "Tests " not in line:
                continue
            matches = re.findall(r"\b(\d{1,9}) (passed|failed|skipped|errors?|errored)\b", line)
            if matches:
                for count, label in matches:
                    key = "errors" if label in {"error", "errors", "errored"} else label
                    counts[key] = int(count)
                break
    elif kind == "mypy":
        match = re.search(r"Found (\d{1,9}) errors?", text)
        if match:
            counts["errors"] = int(match[1])
        elif "Success: no issues found" in text:
            counts["errors"] = 0
    elif kind == "typescript":
        errors = re.findall(r"\berror TS\d+:", text)
        if errors:
            counts["errors"] = len(errors)
    elif kind in {"ruff", "eslint"}:
        match = re.search(r"(?:Found |\()?(\d{1,9}) errors?", text)
        if match:
            counts["errors"] = int(match[1])
        elif "All checks passed" in text:
            counts["errors"] = 0
    summary = ", ".join(f"{count} {label}" for label, count in sorted(counts.items()))
    return ParsedVerification(
        parser=kind,
        confidence="summary" if counts else "exit_code",
        passed=counts.get("passed"),
        failed=counts.get("failed"),
        skipped=counts.get("skipped"),
        errors=counts.get("errors"),
        summary=summary
        or f"{kind}: exit status {exit_code if exit_code is not None else 'unknown'}",
    )
