# Property Bridge

**Manage all your rental Home Assistant instances from one place.**

One central portal for every property. View and control smart devices, build automations, and monitor connection health across your entire portfolio — perfect for Airbnb hosts, vacation rental managers, and multi-home owners.

## Features (v0.2.0)

- Add any number of remote Home Assistant instances via a clean UI config flow
- Secure connection using long-lived access tokens (works great over Tailscale / WireGuard)
- Connection health sensors per property (status, entity count, last seen)
- Entity ID and friendly-name prefixes so devices from different properties never collide
- **Automatic Area & Label** creation per property
- **Rental calendar helpers** – check-in / check-out preset services (script + scene)
- **Maintenance windows & consent** – time-boxed access with optional consent gate (multi-tenant ready)
- Designed from day one for property managers and rental operators

> **Current status**: Solid feature skeleton. WebSocket state mirroring and service-call forwarding is still stubbed; area/label, presets and maintenance services are fully implemented and ready to use.

## Installation (HACS)

1. Make sure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS → Integrations → ⋮ → Custom repositories**.
3. Add the repository URL:  
   `https://github.com/saboaua/Property-Bridge`  
   and select category **Integration**.
4. Click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** and search for **Property Bridge**.

## Manual Installation

Copy the `custom_components/property_bridge` folder into your Home Assistant `custom_components` directory and restart.

## Configuration

1. On each remote Home Assistant create a **Long-Lived Access Token**  
   (Profile → Security → Long-Lived Access Tokens).
2. In the central Home Assistant, add the **Property Bridge** integration.
3. Fill in:
   - **Property name** (e.g. `Aruba Ocean View`)
   - **Host** (IP, hostname, or Tailscale name)
   - **Port** (default 8123)
   - **Access token**
   - Optional entity / friendly-name prefixes
   - Toggle automatic Area / Label creation

### Options (per property)

After adding a property, open **Configure** on the integration entry:

| Option | Purpose |
|--------|---------|
| Create Area / Label | Auto-create Home Assistant Area and Label named after the property |
| Check-in script / scene | Entity IDs run by the `apply_checkin_preset` service |
| Check-out script / scene | Entity IDs run by the `apply_checkout_preset` service |
| Maintenance enabled | Turn the maintenance-window feature on |
| Require consent | Block opening a window until `grant_maintenance_consent` is called |
| Default window hours | Duration used when requesting a maintenance window |

## Services

All services require the config **entry_id** of the property (visible on the device page or under Settings → Devices & Services → Property Bridge).

| Service | Description |
|---------|-------------|
| `property_bridge.apply_checkin_preset` | Runs the configured check-in script and/or scene |
| `property_bridge.apply_checkout_preset` | Runs the configured check-out script and/or scene |
| `property_bridge.grant_maintenance_consent` | Grants consent for maintenance |
| `property_bridge.request_maintenance_window` | Opens a time-limited maintenance window |
| `property_bridge.end_maintenance_window` | Closes the window and revokes consent |

### Example automation (check-in from calendar)

```yaml
automation:
  - alias: "Property check-in preset"
    trigger:
      - platform: calendar
        event: start
        entity_id: calendar.airbnb_aruba_ocean_view
    action:
      - service: property_bridge.apply_checkin_preset
        data:
          entry_id: "YOUR_CONFIG_ENTRY_ID"
```

## Sensors & binary sensors (per property)

- **Connection Status** – Connected / Disconnected  
- **Mirrored Entities** – count of remote entities (once mirroring is live)  
- **Maintenance Until** – ISO timestamp when the current window ends  
- **Maintenance Allowed** (binary) – on while a valid window is open  
- **Maintenance Consent** (binary) – on when consent has been granted  

## Recommended Network Setup

- Install [Tailscale](https://tailscale.com/) (or Headscale) on every Home Assistant instance.
- Use the Tailscale hostname as the `host` value — works behind CGNAT, no open ports required.
- Apply ACLs so only the central management instance (and authorized users) can reach the property instances.
