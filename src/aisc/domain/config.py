"""Pure domain models for AISC profile and network configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class PlatformPathConfig:
    """Platform-specific AISC config root."""

    config_dir: str
    state_dir: str


def _validate_absolute_root(name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value.strip() != value:
        raise ValueError(f"{name} has leading/trailing whitespace")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if not os.path.isabs(value):
        raise ValueError(f"{name} must be an absolute path")
    return value


@dataclass(frozen=True)
class PathPolicy:
    """Validated roots used while reading AISC configuration."""

    platform: PlatformPathConfig
    workspace: Optional[str] = None
    aisc_root: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace", _validate_absolute_root("workspace", self.workspace)
        )
        object.__setattr__(
            self, "aisc_root", _validate_absolute_root("aisc_root", self.aisc_root)
        )


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class SchemaIssue:
    severity: IssueSeverity
    path: str = ""
    reason_code: str = ""
    message: str = ""

    def __repr__(self) -> str:
        return (
            f"{self.severity.value.upper()}: {self.path} "
            f"[{self.reason_code}] — {self.message}"
        )
