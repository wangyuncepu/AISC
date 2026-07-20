# macOS .pkg Manual Test Checklist

This document describes manual verification steps for the AISC macOS
installer.  These tests must be performed on a real Apple Silicon Mac
(macOS 14+).  The CI build (macos-14 runner) verifies structural
integrity via `pkgutil --expand` + `lsbom`; these manual steps verify
the install / uninstall / Gatekeeper user experience.

## Prerequisites

- Apple Silicon Mac (arm64)
- Download `AISC-<version>-macos-arm64.pkg` and `.sha256` from the
  GitHub Actions `pkg-macos-arm64` artifact.
- Docker Desktop installed (for `build --dry-run`).

## 1. SHA256 verification

```bash
shasum -a 256 -c AISC-2.0.0-dev-macos-arm64.pkg.sha256
```

Expected: `OK`.

## 2. First install

Double-click the `.pkg` file.

- Installer should open and prompt for administrator password.
- Complete the standard Installer flow.

After install:

```bash
# Open a NEW Terminal window
aisc version
aisc provider list --format json
aisc build --dry-run
aisc doctor
```

Expected: all commands work; `build --dry-run` shows a docker build
plan pointing to `/usr/local/lib/aisc/aisc-bundle`.

Verify layout:

```bash
ls -l /usr/local/bin/aisc
# Should show: aisc -> ../lib/aisc/aisc

ls /usr/local/lib/aisc/
# Should show: aisc  aisc-bundle  uninstall.sh

ls /usr/local/lib/aisc/aisc-bundle/
# Should show: VERSION container/ config/ ...
```

Verify pkg receipt:

```bash
pkgutil --pkg-info com.aisc.cli
# Should show version: 2.0.0 (the receipt version, not display version)
```

## 3. Gatekeeper (unsigned)

Since the pkg is not signed with a Developer ID:

- First double-click may show: "AISC.pkg can't be opened because it is
  from an unidentified developer."
- **Correct response**: Open **System Settings → Privacy & Security**,
  scroll to the bottom, click **"Open Anyway"** next to the blocked
  item.
- **Do NOT** disable Gatekeeper globally (`spctl --master-disable`).

After allowing, double-click again to install.

## 4. Upgrade (install over existing)

With a previous version installed:

- Double-click the new `.pkg`.
- Complete the installer flow (password prompt).
- Open a new Terminal: `aisc version` should show the new version.

Verify no stale files from the old bundle:

```bash
ls /usr/local/lib/aisc/aisc-bundle/
# Should match exactly the new bundle contents
```

## 5. User config preservation

Before uninstall, create marker files:

```bash
mkdir -p ~/.aisc ~/.cc-config
echo "keep-me" > ~/.aisc/test-marker
echo "keep-me" > ~/.cc-config/test-marker
```

## 6. Uninstall

```bash
sudo /usr/local/lib/aisc/uninstall.sh
```

Verify:

- `/usr/local/bin/aisc` symlink removed.
- `/usr/local/lib/aisc/` directory removed.
- `pkgutil --pkg-info com.aisc.cli` shows "No receipt".
- `~/.aisc/test-marker` still exists ("keep-me").
- `~/.cc-config/test-marker` still exists ("keep-me").
- Docker images/containers still present.

## 7. Re-install after uninstall

Double-click the `.pkg` again.  Installer should succeed (clean
install).  Verify `aisc version` works.

## 8. Edge: install with custom path override

```bash
# Not recommended, but pkg should support alternate install root
installer -pkg AISC-2.0.0-dev-macos-arm64.pkg -target /
# (equivalent to double-click)
```

## Expected Results Summary

| Test | Expected |
|------|----------|
| SHA256 check | OK |
| Install (double-click) | Prompts for admin password, installs |
| `aisc version` | Shows version |
| `aisc provider list --format json` | Shows providers |
| `aisc build --dry-run` | Shows docker build plan |
| Symlink | `../lib/aisc/aisc` |
| Receipt | `com.aisc.cli` version 2.0.0 |
| Gatekeeper | Blocked → override via Settings |
| Upgrade (reinstall) | New version, no stale files |
| Config preserved | `~/.aisc`, `~/.cc-config` intact |
| Uninstall | Files removed, receipt forgotten, config kept |
| Reinstall after uninstall | Works cleanly |
