# Remaining work

## 2026-10-28 feature audit

Automated firmware, browser, and real MQTT broker coverage is documented in
[docs/feature-audit.md](docs/feature-audit.md). Remaining work is explicit:

- Run the physical two-board checklist: cold boot, relay safe state, RF loss and
  recovery, real watchdog expiry, flash persistence/reset/backup, and memory/soak.
- Verify discovery and bidirectional state in a real Home Assistant instance;
  automated tests establish its MQTT payload and broker exchange only.
- Add authenticated MQTT TLS/HTTPS if required; selecting a TLS port currently
  does not add encryption. DNS resolution remains platform dependent.
- Validate door CAD render/print/socket fit and thermal/electrical design. The
  checked-in DXF is a placeholder; generate and check a real template.
- Design the desk enclosure; no desk model is provided.
- Consider a physical override indicator and an explicit mDNS responder.

## Teams (planned feature)

The disabled Teams tab and stored fields are placeholders. There is no OAuth,
Microsoft Graph presence polling, webhook service, or bidirectional Teams sync.
A future implementation needs an authentication design and actual integration
tests before enabling the UI. No completion estimate is asserted.

This preserves the substance of the 2026-07-17 audit's deferred Teams finding.
