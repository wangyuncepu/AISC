"""Validation for AISC-owned profile and network configuration."""

from __future__ import annotations

from typing import Any, List, Mapping

from aisc.domain.config import IssueSeverity, SchemaIssue


ALLOWED_TOP_KEYS = frozenset({"schema_version", "defaults"})
ALLOWED_DEFAULTS_KEYS = frozenset({"profile", "network"})
ALLOWED_PROFILES = frozenset({"safe", "unsafe"})
ALLOWED_NETWORKS = frozenset({"direct", "proxy"})


def validate_config(data: Any, *, is_workspace: bool = False) -> List[SchemaIssue]:
    """Validate only settings owned by AISC.

    Provider and authentication state deliberately live outside this schema and
    are managed exclusively by cc-switch.
    """
    del is_workspace
    issues: List[SchemaIssue] = []
    if not isinstance(data, dict):
        issues.append(
            SchemaIssue(
                severity=IssueSeverity.ERROR,
                path="(root)",
                reason_code="config_not_object",
                message="Config must be a JSON object",
            )
        )
        return issues

    schema_version = data.get("schema_version")
    if schema_version is None:
        issues.append(
            SchemaIssue(
                severity=IssueSeverity.ERROR,
                path="schema_version",
                reason_code="schema_version_missing",
                message="Missing required field",
            )
        )
    elif isinstance(schema_version, bool) or not isinstance(schema_version, int):
        issues.append(
            SchemaIssue(
                severity=IssueSeverity.ERROR,
                path="schema_version",
                reason_code="schema_version_type",
                message="schema_version must be integer",
            )
        )
    elif schema_version != 1:
        issues.append(
            SchemaIssue(
                severity=IssueSeverity.ERROR,
                path="schema_version",
                reason_code="schema_version_unsupported",
                message="Unsupported schema_version",
            )
        )

    for key in data:
        if key not in ALLOWED_TOP_KEYS:
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.WARNING,
                    path="(root)",
                    reason_code="unknown_key",
                    message="Unknown key — preserved but ignored",
                )
            )

    defaults = data.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.ERROR,
                    path="defaults",
                    reason_code="defaults_not_object",
                    message="defaults must be object",
                )
            )
        else:
            _validate_defaults(defaults, issues)
    return issues


def _validate_defaults(
    defaults: Mapping[str, Any], issues: List[SchemaIssue]
) -> None:
    for key in defaults:
        if key not in ALLOWED_DEFAULTS_KEYS:
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.WARNING,
                    path="defaults",
                    reason_code="unknown_key",
                    message="Unknown defaults key",
                )
            )

    profile = defaults.get("profile")
    if profile is not None:
        if not isinstance(profile, str):
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.ERROR,
                    path="defaults.profile",
                    reason_code="profile_type",
                    message="profile must be string",
                )
            )
        elif profile not in ALLOWED_PROFILES:
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.ERROR,
                    path="defaults.profile",
                    reason_code="profile_invalid",
                    message="Invalid profile",
                )
            )

    network = defaults.get("network")
    if network is not None:
        if not isinstance(network, str):
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.ERROR,
                    path="defaults.network",
                    reason_code="network_type",
                    message="network must be string",
                )
            )
        elif network not in ALLOWED_NETWORKS:
            issues.append(
                SchemaIssue(
                    severity=IssueSeverity.ERROR,
                    path="defaults.network",
                    reason_code="network_invalid",
                    message="Invalid network",
                )
            )
