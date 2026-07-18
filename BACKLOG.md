# Backlog

## Portfolio audit backlog — 2026-07-17
_Findings from a 2026-07-17 code audit, preserved for later._

### Later / deferred
- **[low/L]** Teams integration is UI/config stub only — Coming Soon badge, disabled fields, no Graph API/OAuth code (door.py:689)
  - Fix: Not a defect — deliberately stubbed (badge + disabled inputs, config schema present). To ship: implement Azure AD device-code OAuth flow + MS Graph /me/presence polling on the desired interval, wire into the DND light state, and enable the disabled form fields. Real feature work, ~day+.
