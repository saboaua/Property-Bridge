# Property Bridge

**Manage all your rental Home Assistant instances from one place.**

One central portal for every property. View and control smart devices, build automations, and monitor connection health across your entire portfolio — perfect for Airbnb hosts, vacation rental managers, and multi-home owners.

## Features (v0.1)

- Add any number of remote Home Assistant instances via a clean UI config flow
- Secure connection using long-lived access tokens (works great over Tailscale / WireGuard)
- Connection health sensors per property (status, entity count, last seen)
- Entity ID and friendly-name prefixes so devices from different properties never collide
- Designed from day one for property managers and rental operators

> **Current status**: This is a clean, HACS-ready **skeleton**. The WebSocket state mirroring and service-call forwarding logic is stubbed so the integration installs, configures, and creates sensors. Full remote entity sync is the next development milestone.

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

Each property appears as a device with status sensors. Once the full connection layer is implemented, all selected remote entities will appear under that property (prefixed) and can be used in automations and dashboards on the central instance.

## Recommended Network Setup

- Install [Tailscale](https://tailscale.com/) (or Headscale) on every Home Assistant instance.
- Use the Tailscale hostname as the `host` value — works behind CGNAT, no open ports required.
- Apply ACLs so only the central management instance (and authorized users) can reach the property instances.

## Roadmap

- [x] HACS-compatible structure & config flow
- [x] Connection status sensors
- [ ] Full WebSocket state mirroring + service call forwarding
- [ ] Include / exclude domain & entity filters
- [ ] Automatic area / label assignment per property
- [ ] Bulk health dashboard
- [ ] Rental calendar helpers (check-in / check-out presets)
- [ ] Options for maintenance windows / consent (future multi-tenant features)

## Development

```bash
git clone https://github.com/saboaua/Property-Bridge.git
```

Use `pytest-homeassistant-custom-component` for tests.

## Credits & Inspiration

Inspired by the community component [remote_homeassistant](https://github.com/custom-components/remote_homeassistant).  
Built for people managing smart vacation rentals and multi-property portfolios with Home Assistant.

## License

MIT License – see [LICENSE](LICENSE)
