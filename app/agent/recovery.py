from __future__ import annotations

from typing import Any


def classify_mineru_failure(parse_result: dict[str, Any]) -> dict[str, Any]:
    status = str(parse_result.get("status") or "").lower()
    stdout = str(parse_result.get("stdout") or "")
    stderr = str(parse_result.get("stderr") or "")
    message = str(parse_result.get("message") or "")
    joined = f"{status}\n{message}\n{stdout}\n{stderr}".lower()

    if status == "missing_input":
        return _classification(
            "missing_input",
            recoverable=False,
            terminal=True,
            actions=["Check mounted paths or fetch URL inputs before parsing."],
        )
    if "localentrynotfounderror" in joined or "cannot find the appropriate snapshot" in joined:
        return _classification(
            "model_cache_unavailable",
            recoverable=True,
            terminal=False,
            actions=["Verify local MinerU model cache or retry with a reachable model source."],
        )
    if "'nonetype' object has no attribute 'get'" in joined and (
        "models_download_utils" in joined or "local_models_config" in joined
    ):
        return _classification(
            "model_config_missing",
            recoverable=True,
            terminal=False,
            actions=["Create a valid mineru.json model mapping or retry with remote hybrid backend."],
        )
    if "cuda out of memory" in joined or "outofmemoryerror" in joined or "resource exhausted" in joined:
        return _classification(
            "resource_exhausted",
            recoverable=True,
            terminal=False,
            actions=["Reduce page window or concurrency, then retry with remote/hybrid backend if available."],
        )
    if "connection refused" in joined or "failed to establish a new connection" in joined:
        return _classification(
            "remote_backend_unavailable",
            recoverable=True,
            terminal=False,
            actions=["Retry local pipeline or verify remote MinerU endpoint health."],
        )
    if "timed out" in joined or "timeout" in joined:
        return _classification(
            "timeout",
            recoverable=True,
            terminal=False,
            actions=["Retry a smaller page window or use a larger worker timeout."],
        )
    if parse_result.get("returncode") not in {None, 0}:
        return _classification(
            "mineru_cli_failed",
            recoverable=True,
            terminal=False,
            actions=["Retry with alternate parse method/backend and inspect stderr tail."],
        )
    return _classification(
        "unknown_parse_failure",
        recoverable=True,
        terminal=False,
        actions=["Retry with conservative OCR settings and preserve diagnostics for review."],
    )


def _classification(
    category: str,
    *,
    recoverable: bool,
    terminal: bool,
    actions: list[str],
) -> dict[str, Any]:
    return {
        "category": category,
        "recoverable": recoverable,
        "terminal": terminal,
        "recommended_actions": actions,
    }
