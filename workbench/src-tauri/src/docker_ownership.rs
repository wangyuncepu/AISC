//! docker-ownership-foundation A0: Rust mirror of the frozen ownership-label
//! contract.
//!
//! Python `src/aisc/domain/docker_ownership.py` is authoritative; this module
//! and the shared fixture `tests/fixtures/docker-ownership/labels.json` stay
//! in lockstep (the A0 three-language gate; same pattern as
//! `data_root.rs`/`hash-vectors.json`). Constants only — the Rust side
//! consumes structured CLI results and never invents its own label strings.
//!
//! See docs/plans/docker-resource-lifecycle/02-domain-contract.md §1 and
//! 05-cross-plan-coordination.md §1.

// --- container / volume labels (io.aisc.*) ---------------------------------

/// Marker label proving AISC ownership. Value is always `true`.
pub const LABEL_MANAGED: &str = "io.aisc.managed";
/// Resource kind (`KIND_*`).
pub const LABEL_KIND: &str = "io.aisc.kind";
/// Creating component (`OWNER_*`).
pub const LABEL_OWNER: &str = "io.aisc.owner";
/// Ownership label schema version (label value; Docker labels are strings).
pub const LABEL_SCHEMA_VERSION: &str = "io.aisc.schema-version";
/// Workspace hash scoping a resource to one workspace (containers, volumes).
pub const LABEL_WORKSPACE_KEY: &str = "io.aisc.workspace-key";
/// Runtime UUID — runtime containers only.
pub const LABEL_RUNTIME_ID: &str = "io.aisc.runtime-id";

// --- image provenance labels (org.aisc.*) ----------------------------------

pub const IMAGE_LABEL_MANAGED: &str = "org.aisc.managed";
pub const IMAGE_LABEL_KIND: &str = "org.aisc.kind";
pub const IMAGE_LABEL_SCHEMA_VERSION: &str = "org.aisc.schema-version";
pub const IMAGE_LABEL_SOURCE_VERSION: &str = "org.aisc.source-version";

// --- label values -----------------------------------------------------------

pub const KIND_RUNTIME: &str = "runtime";
pub const KIND_ONE_SHOT: &str = "one-shot";
pub const KIND_TOOLCHAIN: &str = "toolchain";

pub const OWNER_WORKBENCH: &str = "workbench";
pub const OWNER_CLI: &str = "cli";

/// The only image kind v1 defines (workstation images from `aisc build`).
pub const IMAGE_KIND_WORKSTATION: &str = "workstation-image";

/// Value of `io.aisc.schema-version` / `org.aisc.schema-version`.
pub const OWNERSHIP_LABEL_SCHEMA_V1: &str = "1";

/// `schema_version` integer for the maintenance scan/cleanup JSON envelopes.
pub const OWNERSHIP_SCHEMA_V1: i64 = 1;

/// `docker --filter` value selecting AISC-managed resources, optionally
/// narrowed to one kind.
pub fn managed_filter(kind: Option<&str>) -> String {
    match kind {
        Some(k) => format!("label={LABEL_KIND}={k}"),
        None => format!("label={LABEL_MANAGED}=true"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::collections::BTreeMap;
    use std::path::PathBuf;

    fn fixture() -> Value {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/docker-ownership/labels.json");
        serde_json::from_str(&std::fs::read_to_string(path).expect("fixture readable"))
            .expect("fixture parses")
    }

    fn str_map(v: &Value) -> BTreeMap<String, String> {
        v.as_object()
            .expect("object")
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().expect("string value").to_string()))
            .collect()
    }

    #[test]
    fn constants_mirror_fixture() {
        let f = fixture();
        let container = str_map(&f["container_labels"]);
        assert_eq!(container["managed"], LABEL_MANAGED);
        assert_eq!(container["kind"], LABEL_KIND);
        assert_eq!(container["owner"], LABEL_OWNER);
        assert_eq!(container["schema_version"], LABEL_SCHEMA_VERSION);
        assert_eq!(container["workspace_key"], LABEL_WORKSPACE_KEY);
        assert_eq!(container["runtime_id"], LABEL_RUNTIME_ID);

        let image = str_map(&f["image_labels"]);
        assert_eq!(image["managed"], IMAGE_LABEL_MANAGED);
        assert_eq!(image["kind"], IMAGE_LABEL_KIND);
        assert_eq!(image["schema_version"], IMAGE_LABEL_SCHEMA_VERSION);
        assert_eq!(image["source_version"], IMAGE_LABEL_SOURCE_VERSION);

        let kinds = str_map(&f["kind_values"]);
        assert_eq!(kinds["runtime"], KIND_RUNTIME);
        assert_eq!(kinds["one_shot"], KIND_ONE_SHOT);
        assert_eq!(kinds["toolchain"], KIND_TOOLCHAIN);

        let owners = str_map(&f["owner_values"]);
        assert_eq!(owners["workbench"], OWNER_WORKBENCH);
        assert_eq!(owners["cli"], OWNER_CLI);

        assert_eq!(f["image_kind_workstation"].as_str().unwrap(), IMAGE_KIND_WORKSTATION);
        assert_eq!(f["label_schema_v1"].as_str().unwrap(), OWNERSHIP_LABEL_SCHEMA_V1);
        assert_eq!(f["envelope_schema_v1"].as_i64().unwrap(), OWNERSHIP_SCHEMA_V1);
    }

    #[test]
    fn filters_mirror_fixture() {
        let f = fixture();
        assert_eq!(
            managed_filter(None),
            f["example_managed_filter"].as_str().unwrap()
        );
        assert_eq!(
            managed_filter(Some(KIND_TOOLCHAIN)),
            f["example_kind_filter"].as_str().unwrap()
        );
    }
}
