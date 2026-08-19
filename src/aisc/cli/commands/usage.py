"""``aisc usage`` command layer (IDEA-2 2c).

Thin wrapper over ``aisc.application.usage`` — subscription status plus
per-provider token usage aggregated across all data-root workspaces.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def cmd_usage_overview(args: Any) -> Dict[str, Any]:
    from aisc.application.usage import usage_overview

    return usage_overview(
        range_key=getattr(args, "range", "7d") or "7d",
        workspace=getattr(args, "workspace", None),
    )


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def print_usage_overview_text(data: Optional[Dict[str, Any]]) -> None:
    """Human-readable output (secret-free: masked subscription URL only)."""
    if not isinstance(data, dict):
        return
    sub = data.get("subscription") or {}
    if sub.get("configured"):
        userinfo = sub.get("userinfo")
        if isinstance(userinfo, dict):
            total = userinfo.get("total")
            used = userinfo.get("upload", 0) + userinfo.get("download", 0)
            usage_bit = (f"{_fmt_tokens(used)} / {_fmt_tokens(total)} bytes"
                         if total else f"{_fmt_tokens(used)} bytes (unlimited)")
        else:
            # null userinfo = the source provided no usage header (manual
            # content import, or a provider that omits subscription-userinfo)
            usage_bit = "no usage info"
        print(f"Subscription: {sub.get('url_masked') or '(manually imported)'}"
              f"  [{sub.get('source')}]  {usage_bit}")
    else:
        print("Subscription: none configured")

    print(f"Range: {data.get('range')}")
    for ws in data.get("workspaces", []):
        name = ws.get("workspace_path") or ws.get("workspace_hash") or "?"
        try:
            from pathlib import Path as _P
            name = _P(str(name)).name or str(name)
        except Exception:
            pass
        state = ("live" if ws.get("source") == "live"
                 else "cache" if ws.get("source") == "cache" else "no data")
        print(f"\nWorkspace {name} [{state}]")
        for p in ws.get("providers", []):
            print(f"  {p['app']:7} {p['provider_name']:24} "
                  f"req={p['requests']:>6} ok={p['success']:>6} "
                  f"tokens={_fmt_tokens(p['tokens_total']):>9} "
                  f"${p['cost_estimate']:.4f}")
        if not ws.get("providers"):
            print("  (no usage rows)")

    totals = data.get("totals") or {}
    print(f"\nTotals: requests={totals.get('requests', 0)} "
          f"tokens={_fmt_tokens(totals.get('tokens_total', 0))} "
          f"cost=${totals.get('cost_estimate', 0.0):.4f}")
