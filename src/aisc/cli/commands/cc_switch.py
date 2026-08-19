"""``aisc cc-switch`` command layer (Stage 8d).

Thin wrappers over ``aisc.application.cc_switch_provider``: assemble the
request document (secrets from STDIN per the contract's ``--secret-stdin`` /
``--patch-stdin`` semantics — one JSON document on stdin carries both the
patch fields and the optional ``api_key``), then print the redacted snapshot.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from aisc.domain.models import CliError


def _read_stdin_request(*, required: bool) -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        if required:
            raise CliError(
                message="a JSON request document on stdin is required "
                        "(--secret-stdin/--patch-stdin semantics)",
                exit_code=2,
                error_code="AISC_ERR_USAGE",
            )
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(
            message=f"stdin request is not valid JSON: {exc}",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        ) from exc
    if not isinstance(data, dict):
        raise CliError(
            message="stdin request must be a JSON object",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return data


def cmd_cc_switch_list(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import list_providers

    return list_providers(
        runtime_id=args.runtime_id,
        agent=args.agent,
        workspace=args.workspace,
        executor=None,
    )


def cmd_cc_switch_add(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import add_provider

    request = _read_stdin_request(required=True)
    request["mode"] = getattr(args, "mode", None) or request.get("mode") or "simple"
    if getattr(args, "provider", None):
        request["provider"] = args.provider
    if getattr(args, "new_id", None):
        request["id"] = args.new_id
    return add_provider(
        runtime_id=args.runtime_id,
        agent=args.agent,
        request=request,
        workspace=args.workspace,
        executor=None,
    )


def cmd_cc_switch_edit(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import edit_provider

    request = _read_stdin_request(required=True)
    request.setdefault("patch", {})
    if not isinstance(request["patch"], dict):
        raise CliError(
            message="request.patch must be a JSON object",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return edit_provider(
        runtime_id=args.runtime_id,
        agent=args.agent,
        provider_id=args.provider_id,
        request=request,
        workspace=args.workspace,
        executor=None,
    )


def cmd_cc_switch_switch(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import switch_provider

    return switch_provider(
        runtime_id=args.runtime_id,
        agent=args.agent,
        provider_id=args.provider_id,
        workspace=args.workspace,
        executor=None,
    )


def cmd_cc_switch_delete(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import delete_provider

    if not getattr(args, "confirm", False):
        raise CliError(
            message="delete requires --confirm",
            exit_code=2,
            error_code="AISC_ERR_USAGE",
        )
    return delete_provider(
        runtime_id=args.runtime_id,
        agent=args.agent,
        provider_id=args.provider_id,
        workspace=args.workspace,
        executor=None,
    )


def cmd_cc_switch_fetch_models(args: Any) -> Dict[str, Any]:
    from aisc.application.cc_switch_provider import fetch_models

    return fetch_models(
        runtime_id=args.runtime_id,
        agent=args.agent,
        provider_id=args.provider_id,
        workspace=args.workspace,
        executor=None,
    )


def print_cc_switch_text(data: Optional[Dict[str, Any]]) -> None:
    """Human-readable output: one line per provider (secret-free)."""
    if not isinstance(data, dict):
        return
    for p in data.get("providers", []):
        current = " →" if p.get("is_current") else "  "
        key = p.get("api_key_mask") or "no-key"
        print(f"{current} {p.get('id', ''):24} {p.get('name', ''):20} "
              f"{p.get('base_url', '')} | {p.get('model', '')} | {key}")
