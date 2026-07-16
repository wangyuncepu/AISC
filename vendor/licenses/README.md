# Vendor Licenses

This document tracks the license status of all third-party components bundled
in the AISC project for offline and China-network builds.

## Component License Summary

| Component | Version | License | SPDX | Notes |
|-----------|---------|---------|------|-------|
| mihomo | v1.19.27 | GPL-3.0 | GPL-3.0 | Clash Meta proxy core |
| geodata | latest | unknown | — | GeoIP/GeoSite data files from MetaCubeX |
| caveman | 0.1.0 | MIT | MIT | Caveman AI coding agent plugin |
| claude-hud | 0.0.11 | MIT | MIT | Real-time HUD for Claude Code |
| claude-plugins-official | embedded | Apache-2.0 | Apache-2.0 | Official Claude Code plugin marketplace |
| anthropic-agent-skills | 1.0.0 | Apache-2.0 | Apache-2.0 | Anthropic example/document skills |
| gstack-skills | 1.1.0 | unknown | — | gstack browser QA skills suite |

## License Compatibility

All currently identified licenses are permissive (MIT, Apache-2.0) or copyleft
(GPL-3.0). Key considerations:

- **GPL-3.0 (mihomo)**: Distribution of the AISC container image that includes
  the mihomo binary requires the corresponding source code to be made available.
  The mihomo source is at https://github.com/MetaCubeX/mihomo.
- **MIT (caveman, claude-hud)**: Permissive — requires only that the license
  notice and copyright are retained.
- **Apache-2.0 (claude-plugins-official, anthropic-agent-skills)**: Permissive —
  requires license notice, copyright notice, and a copy of the license text to
  be distributed with any substantial portions.
- **unknown (geodata, gstack-skills)**: License terms have not been confirmed.
  These should be verified before redistribution.

## Verifying Licenses

Before distributing the AISC container image, verify that all vendored
components have compatible licenses:

```bash
# Review the manifest and checksums
cat vendor/manifest.json | python3 -m json.tool
sha256sum -c vendor/checksums.txt
```

## Refreshing Vendor Artifacts

To update vendored components, run the vendor refresh tool (created in P2.4):

```bash
bash tools/vendor-refresh.sh
```

This will:
1. Download updated versions of binaries and geodata
2. Pull the latest plugin/skill bundle snapshots
3. Regenerate `vendor/manifest.json` and `vendor/checksums.txt`

## File Inventory

- `vendor/manifest.json` — Machine-readable component inventory (schema v1)
- `vendor/checksums.txt` — SHA256 checksums of all vendored files
- `vendor/licenses/README.md` — This document
