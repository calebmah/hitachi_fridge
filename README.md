# Hitachi Fridge — Home Assistant Custom Integration

<p align="center">
  <img src="custom_components/hitachi_fridge/brand/icon@2x.png" alt="Hitachi Fridge" width="140" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom" />
  <img src="https://img.shields.io/badge/Home%20Assistant-2024.4%2B-blue.svg" alt="Home Assistant 2024.4+" />
  <img src="https://img.shields.io/badge/IoT%20Class-Local%20Polling-brightgreen.svg" alt="Local Polling" />
  <img src="https://img.shields.io/badge/version-1.0.0-informational.svg" alt="Version 1.0.0" />
  <img src="https://img.shields.io/badge/Created%20with-Google%20Gemini%20AI-8E75B2.svg" alt="Created with Google Gemini AI" />
</p>

> [!WARNING]
> **AI Disclaimer — Created Using Google Gemini**
>
> This integration and its documentation were created using **AI (Google Gemini)**. While tested on live Hitachi refrigerator hardware, the code was AI-generated and is provided **as-is** without warranty — please review before use and use at your own risk. This is an unofficial community project and is not affiliated with or endorsed by Hitachi.

A **local-first Home Assistant custom integration** (`hitachi_fridge`) for Wi-Fi-enabled **Hitachi Smart Refrigerators** (compatible with models supported by the official *Hitachi Fridge* app).

It communicates **directly with your refrigerator over Local LAN UDP (`port 50000`)** for fast, low-latency telemetry and sub-second controls without cloud dependency during normal operation, while automatically falling back to Hitachi Cloud when off-LAN and fetching Cloud-only metadata such as **10-day door-open history** and **firmware updates**.

---

## Key Features

- **Local-First Polling & Sub-Second Controls (`UDP :50000`)**: Automatically discovers your refrigerator on the LAN (`CMD=SEARCH`), polls real-time status every **5 seconds** (configurable down to **3 seconds**, ~50–120 ms round-trip), and sends control commands directly on your local network.
- **Seamless Cloud Fallback & Auto-Recovery**: If UDP port `50000` is unreachable (e.g., isolated Docker bridge or temporary Wi-Fi drop), the coordinator automatically falls back to Hitachi Cloud (`60 s` interval) and periodically re-probes LAN to switch back to `local_udp` automatically.
- **UI Sign-In & Silent Credential Renewal**: Sign in with your Hitachi Fridge email and password directly in Home Assistant. Cloud session tokens and per-appliance AES-256 UDP keys are persisted and **silently renewed** in the background whenever needed, with built-in **Reauthenticate** and **Reconfigure** flows.
- **Zero-Downtime Options Updates**: Adjust Local UDP and Cloud polling intervals or set a static LAN IP anytime via **Configure** — changes apply live in memory without reloading entities or creating `unavailable` gaps.
- **Strict Per-Model Capability Gating**: Automatically detects all **26 Hitachi Smart Refrigerator model prefixes** and creates **only** the sensors, binary sensors, selects, switches, and firmware entities supported by your exact refrigerator model.
- **Native Brand Icons Included**: Ships with `brand/` icons for Home Assistant `2026.3+`.

---

## Supported Models

All Wi-Fi-enabled Hitachi refrigerators supported by the official **Hitachi Fridge** mobile app (`jp.co.hitachi_gls.hitachi_refrigerator_mij`), including:

- **Overseas Multi-Door / Selectable Zone Series (`R-WB*`)**:
  `R-WB640VFX`, `R-WB640VH0X`, `R-WB640V0MSX`, `R-WB700VFX`, `R-WB780VMS3X` *(and regional equivalents sharing these hardware prefixes)*
- **Japanese Flagship `R-WXC*` & `R-ZXC*` Series**:
  `R-WXC620KS`, `R-WXC670KH`, `R-WXC670KS`, `R-WXC670RH`, `R-WXC740KH`, `R-WXC740KS`, `R-WXC740RH`, `R-WXC740WH`, `R-WXC740WS`, `R-ZXC740KH`, `R-ZXC740KJ`, `R-ZXC740KS`, `R-ZXC740KT`, `R-ZXC740RH`, `R-ZXC740RT`, `R-ZXC740WH`, `R-ZXC740WS`
- **Japanese `R-GWC*` Series**:
  `R-GWC670TH`, `R-GWC670TS`, `R-GWC670YS`
- **Japanese Selectable Switch Room `R-KWC*` & `R-KX*` Series**:
  `R-KWC570KH`, `R-KWC570KS`, `R-KX570K`

### Per-Model Feature Matrix

| Feature / Entity | Platform | Overseas `R-WB*` | JP `R-KWC570*` / `R-KX570K` | JP `R-GWC670*` | JP `R-WXC*` / `R-ZXC*` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Door Ajar Alarm & Water Supply Low** | `binary_sensor` | Yes | Yes | Yes | Yes |
| **Door Opens Today & Yesterday** (+ 10-day history attribute) | `sensor` | Yes | Yes | Yes | Yes |
| **Fridge & Drawer Door Open Duration** (Today, Yesterday & 10-day) | `sensor` | — | — | Yes | `WH` / `WS` models |
| **Selectable Zone Mode** (`Freezer`, `Soft Freeze`, `Chill / Meat`, `Refrigerator`) & **Switching Status** | `sensor` / `binary_sensor` | **Yes** | — | — | — |
| **Upper & Lower Selectable Compartment Mode & Switching Status** | `sensor` / `binary_sensor` | — | **Yes** | — | — |
| **Refrigerator Temperature** (Auto Normal 3-step / Fine 9 or 11-step) | `select` | Yes (3 / 9-step) | Yes (3 / 11-step) | Yes (3 / 11-step) | Yes (3 / 11-step) |
| **Freezer Temperature** (Auto Normal 3-step / Fine 9 or 11-step) | `select` | Yes (3 / 9-step) | *(Switch Rooms)* | Yes (3 / 11-step) | Yes (3 / 11-step) |
| **Upper & Lower Selectable Compartment Temp.** | `select` | — | `R-KX570K` | — | — |
| **Vacuum Compartment** | `select` / `switch` | `select` (`Off`, `Sub Zero -1 °C`, `Chilled +1 °C`) | `switch` on `KWC570` (`Off` / `On`) | `switch` (`Off` / `On`) | `select` (`Off`, `Sub Zero -1 °C`, `Chilled +1 °C`) |
| **Ice Maker** | `switch` / `select` | `switch` (`Off` / `On`) | `select` (`Off`, `On`, `Quick`) | `select` (`Off`, `On`, `Quick`) | `select` (`Off`, `On`, `Quick`) |
| **Energy Saver** (+ Active Eco Operation Binary Sensor) | `switch` / `binary_sensor` | Yes | Yes | Yes | Yes |
| **Quick Cooling** (+ In-Progress Binary Sensor) | `switch` / `binary_sensor` | **Yes** | — | **Yes** | — |
| **Quick Freezing** (+ In-Progress Binary Sensor) | `switch` / `binary_sensor` | **Yes** | — | — | — |
| **Spot Cooling & Speed Cooling** (+ In-Progress Binary Sensor) | `switch` / `binary_sensor` | — | — | — | **Yes** |
| **Vegetable Compartment** | `switch` | — | — | **Yes** | **Yes** |
| **Control Panel Lock** | `switch` | — | Yes | Yes | Yes |
| **Door Alarm Volume** (`Off`, `Mid`, `Max`) | `select` | — | Yes | Yes | Yes |
| **Auto Door / Electric Drawer Status** | `binary_sensor` | — | — | — | `R-ZXC740*` only |
| **Ice Making, Ice Maker Cleaning, Alert & Error/Notification Codes** | `binary_sensor` / `sensor` | Yes | Yes | Yes | Yes |
| **Firmware Update & Auto-Update** | `update` / `switch` | Yes | Yes | Yes | Yes |
| **Appliance Nickname & App Push Notification Toggles** | `text` / `switch` | Yes *(optional)* | Yes *(optional)* | Yes *(optional)* | Yes *(optional)* |

*(Note: In Hitachi's protocol, **Selectable Zone mode** on `R-WB*` and **Switch Room mode** on `R-KWC*`/`R-KX*` are read-only for food safety so stored food cannot be thawed or frozen accidentally via remote command.)*

---

## Installation

### Option 1: HACS (Recommended)

1. Open **HACS** in Home Assistant.
2. Click the three-dot menu (**`⋮`**) in the top-right corner and select **Custom repositories**.
3. Paste the URL of this GitHub repository and select **Integration** as the category, then click **Add**.
4. Find **Hitachi Fridge** in HACS, click **Download**, and **Restart Home Assistant**.

### Option 2: Manual Installation

1. Download this repository and copy the `custom_components/hitachi_fridge` folder into your Home Assistant `<config>/custom_components/` directory:
   ```text
   <config>/custom_components/hitachi_fridge/
   ```
2. Restart Home Assistant.

---

## Setup & Configuration

1. Go to **Settings -> Devices & Services -> + Add Integration**.
2. Search for **Hitachi Fridge** and enter:
   - **Email address**: Your Hitachi Fridge mobile app email (Hitachi ID).
   - **Password**: Your Hitachi Fridge account password.
   - **Static refrigerator LAN IP (optional)**: Leave blank for automatic UDP broadcast discovery, or enter your fridge's IPv4 address if Home Assistant runs in Docker bridge mode or on an unrouted subnet.
3. Click **Submit**. Your paired refrigerator(s) and supported entities will be created automatically.

### Integration Options (`Configure`)

Click **Configure** on the integration entry at any time to adjust:
- **Local LAN UDP polling interval**: `3`–`60` seconds (default: `5` seconds).
- **Cloud fallback polling interval**: `30`–`300` seconds (default: `60` seconds, used only when Local UDP is unreachable).
- **Static refrigerator LAN IP**: Optional static IPv4 override.

---

## Entities & Automation Tips

### 1. Instant Door-Open Trigger (`0–3 s`) vs. Door-Ajar Alarm (`60 s`)

Hitachi's refrigerator firmware exposes two distinct door signals:
- **`sensor.<fridge>_door_opens_today`**: Increments `+1` **immediately** when any refrigerator or freezer door is opened (and is not capped at `99` like the mobile app UI).
- **`binary_sensor.<fridge>_door`**: Reflects the fridge's **Door-Ajar Alarm** (`moveSign` bit 2), which turns **Open** once a door has been left open continuously for ~60 seconds (when the audible beeper starts) and clears immediately when closed.

To trigger an automation **immediately (`0–3 s`)** when someone opens the fridge (while ignoring midnight resets and restarts):

```yaml
triggers:
  - trigger: state
    entity_id: sensor.r_wb780vms3x_door_opens_today
    not_from:
      - unavailable
      - unknown
    not_to:
      - unavailable
      - unknown
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}"
actions:
  # Your action here (e.g., turn on kitchen under-cabinet lights)
```

### 2. Accessing the 10-Day Door Open History

`sensor.<fridge>_door_opens_yesterday` exposes a `ten_day_door_opens` attribute (`YYYY-MM-DD: count`) combining 8 days of midnight Cloud snapshots (`CMD=DELIVERY`) with yesterday's and today's live counts:

```jinja2
{{ state_attr('sensor.r_wb780vms3x_door_opens_yesterday', 'ten_day_door_opens') }}
```

### 3. Local LAN UDP (`50000/udp`) Networking Notes

Hitachi refrigerators ignore ephemeral UDP source ports and always send unicast replies to **`<home_assistant_ip>:50000`**:
- **Home Assistant OS / Supervised / Docker `network_mode: host`**: Works out of the box. If your fridge is on a separate IoT VLAN, allow `50000/udp` between Home Assistant and the fridge IP (and enter the fridge's Static LAN IP if broadcast packets do not cross your VLAN router).
- **Docker Bridge Networking**: Publish `-p 50000:50000/udp` and enter your fridge's Static LAN IP in **Configure**.
- **Shared Account Tip**: Hitachi allows up to 5 accounts paired to one refrigerator. If frequently opening the mobile app on your phone causes Cloud session contention with Home Assistant, you can create a dedicated secondary Hitachi ID for Home Assistant (note that Local LAN UDP uses static per-appliance keys that do not expire when web sessions rotate).

---

## Diagnostics & Troubleshooting

On the Hitachi Fridge device page, click **`⋮` -> Download diagnostics** to export a redacted JSON snapshot (`email`, `password`, tokens, and AES keys are automatically stripped, while raw `MOVEINF` hex telemetry and transport state are preserved for debugging).

---

## Disclaimer

This is an independent community integration and is not affiliated with, endorsed by, or supported by Hitachi Global Life Solutions, Inc. or Arçelik Hitachi Home Appliances. All product and company names are trademarks of their respective holders.
