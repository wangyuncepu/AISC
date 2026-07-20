"""Deterministic lock v2 serializer — byte-stable JSON output.

Deserialization is in aisc.domain.skill_models.deserialize_lock_v2.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from aisc.domain.skill_models import SkillLockV2


def serialize_lock_v2(lock: SkillLockV2) -> bytes:
    """Serialize a SkillLockV2 to deterministic JSON bytes."""
    skills_ordered = sorted(lock.skills.items(), key=lambda kv: kv[0])
    skills_dict: Dict[str, Any] = {}
    for name, entry in skills_ordered:
        skills_dict[name] = {
            "name": entry.name,
            "source_url": entry.source_url,
            "requested_ref": entry.requested_ref,
            "resolved_commit": entry.resolved_commit,
            "directory": entry.directory,
            "owner": entry.owner,
            "repo": entry.repo,
            "files": [
                {"path": f.path, "sha256": f.sha256, "size": f.size}
                for f in sorted(entry.files, key=lambda x: x.path)
            ],
            "dependencies": {
                "detected_references": sorted(entry.detected_references),
            },
        }
    output = {"version": 2, "skills": skills_dict}
    text = json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False)
    if not text.endswith("\n"): text += "\n"
    return text.encode("utf-8")
