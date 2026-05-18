# RFC1918 Access Design

**Goal:** Allow the WebUI runtime to access RFC1918 private IPv4 ranges by default for both normal repository runs and release deployments.

**Scope:** This change affects the runtime safety checks used by `exec`, `web_fetch`, and `web_search`. It does not introduce a new configuration switch or partial allowlist behavior.

## Decision

Use a startup monkey patch in the WebUI layer to remove RFC1918 ranges from nanobot's blocked-network list.

The blocked list will continue to include:

- `0.0.0.0/8`
- `100.64.0.0/10`
- `127.0.0.0/8`
- `169.254.0.0/16`
- `::1/128`
- `fc00::/7`
- `fe80::/10`

The blocked list will stop including:

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`

## Why This Approach

This is the smallest change that matches the requested behavior. The underlying `nanobot-ai` package already centralizes internal-network checks in `nanobot.security.network`, and both `ExecTool` and the web tools depend on that module. Changing the shared network guard once is enough to affect all three tool paths.

This also avoids changing release-only configuration, because the user explicitly wants the new behavior everywhere.

## Implementation Shape

Add a new WebUI startup patch module that runs during `webui.__main__` initialization and mutates `nanobot.security.network._BLOCKED_NETWORKS` to remove the three RFC1918 ranges.

Register that patch from `webui/patches/__init__.py` so it is applied alongside the existing startup patches.

## Testing

Add focused tests that:

- verify a hostname resolving to `10.x.x.x`, `172.16.x.x`, or `192.168.x.x` is now allowed
- verify `contains_internal_url()` no longer flags commands targeting RFC1918 addresses
- verify loopback and link-local targets remain blocked

## Risks

This is intentionally broad. Any runtime using this WebUI will be able to reach RFC1918 destinations through the affected tools. That matches the requested deployment behavior, but it removes a defense-in-depth guard for those ranges.
