# Octosynk

Octosynk synchronizes Octopus Energy "Intelligent" tariff charging schedules with Sunsynk solar inverters, optimizing battery charging by combining regular off-peak rates with smart dispatch windows.

## ⚠️ WARNING

**USE AT YOUR OWN RISK.** This software modifies settings on your solar inverter. The authors provide **NO WARRANTY** of any kind, express or implied. By using this software, you acknowledge that:

- You understand it will automatically change your inverter's charging schedule
- Any misconfiguration could result in unexpected behavior or equipment issues
- You are solely responsible for monitoring your inverter and energy system
- The authors are not liable for any damages, losses, or issues that may arise from use of this software

If you are not comfortable with automated inverter control, do not use this software.

## Features

- Fetches planned dispatch times from Octopus Energy Intelligent API
- Merges dispatches with configured off-peak windows
- Generates optimized 6-slot charging schedule
- Updates Sunsynk inverter configuration automatically
- Optional MQTT integration for Home Assistant control and monitoring
- Optional healthcheck monitoring via healthchecks.io
- Docker deployment with automated scheduling

In short, this application will periodically check for smart dispatch schedules from Octopus (the additional off-peak rate periods they use to charge your EV). Using these, your Sunsynk inverter's charge schedule will be updated to ensure your battery charges at the same time.

## Requirements

- Python 3.13+
- Octopus Energy account with Intelligent tariff
- Octopus Energy API key
- Sunsynk inverter with API access
- Docker and Docker Compose (for production deployment)

You can acquire your Octopus API key from the the personal details section of your Octopus account. At the time of writing you can generate one [here](https://octopus.energy/dashboard/new/accounts/personal-details/api-access)

## Configuration

Create a `.env` file in the project root with the following variables:

### Required Variables

```bash
# Octopus Energy Configuration
OCTOPUS_API_KEY=your_api_key_here
OCTOPUS_DEVICE_ID=your_device_id_here

# Sunsynk Configuration
SUNSYNK_USERNAME=your_sunsynk_email
SUNSYNK_PASSWORD=your_sunsynk_password
SUNSYNK_DEVICE_ID=your_device_id_here
```

### Optional Variables

```bash
# Off-peak time window (default: 23:30-05:30)
OFF_PEAK_START_TIME=23:30
OFF_PEAK_END_TIME=05:30

# API URLs (defaults shown)
OCTOPUS_API_URL=https://api.octopus.energy/v1/graphql/
SUNSYNK_API_URL=https://api.sunsynk.net/api/v1/
SUNSYNK_AUTH_URL=https://api.sunsynk.net/oauth/

# Logging level (default: INFO)
# Options: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# Healthchecks.io monitoring (optional)
# Get your UUID from https://healthchecks.io after creating a check
HEALTHCHECK_UUID=your-healthcheck-uuid-here

# MQTT Configuration (optional - for Home Assistant integration)
MQTT_BROKER=homeassistant.local  # or IP address of your MQTT broker
MQTT_PORT=1883                    # default MQTT port
MQTT_USERNAME=your_mqtt_username  # optional
MQTT_PASSWORD=your_mqtt_password  # optional
MQTT_TOPIC_PREFIX=octosynk        # default topic prefix
```

## Finding Your Device IDs

### Octopus Device ID

To find your Octopus Energy device ID, use the included `list-devices.py` script:

```bash
# Set your API key
export OCTOPUS_API_KEY=your_api_key_here

# Run the script with your account number (format: A-12345678)
python list-devices.py A-12345678
```

The script will display all devices associated with your account:

```
Found 2 device(s):

ID:   abc123-def456-ghi789
Name: My Electric Vehicle
Type: EV_CHARGER
------------------------------------------------------------
ID:   xyz789-uvw456-rst123
Name: Home Battery
Type: BATTERY
------------------------------------------------------------

To use a device, set OCTOPUS_DEVICE_ID to one of the IDs above in your .env file
```

Copy the ID of your device and set it as `OCTOPUS_DEVICE_ID` in your `.env` file.

### Sunsynk Device ID

Log into your Sunsynk account at [sunsynk.net](https://www.sunsynk.net) and navigate to your inverter settings to find your device ID.

## Development Setup

1. Install UV package manager (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Install dependencies:
```bash
uv sync
```

3. Run the application:
```bash
uv run octosynk
```

## Deployment with Docker

Pre-built Docker images are automatically published to GitHub Container Registry on every release.

### Initial Setup

1. Download the docker-compose.yml:
```bash
curl -O https://raw.githubusercontent.com/jmcharter/Octosynk/main/docker-compose.yml
```

2. Create your `.env` file with all required configuration (see Configuration section above)

3. Start the services:
```bash
docker-compose up -d
```

The application will now run automatically every 5 minutes via the Ofelia scheduler.

### Setting Up Healthchecks.io (Optional)

1. Create a free account at [healthchecks.io](https://healthchecks.io)
2. Create a new check with:
   - **Name**: Octosynk
   - **Schedule**: Every 5 minutes (or `*/5 * * * *` in cron format)
   - **Grace time**: 2 minutes (allows for occasional delays)
3. Copy the UUID from the check URL (e.g., `https://hc-ping.com/YOUR-UUID-HERE`)
4. Add `HEALTHCHECK_UUID=YOUR-UUID-HERE` to your `.env` file
5. Restart the container: `docker-compose restart octosynk`

You'll now receive alerts via email/SMS if the service stops running.

### Setting Up Home Assistant Integration (Optional)

Octosynk supports MQTT integration for Home Assistant, allowing you to control and monitor the sync process from your smart home dashboard.

#### Prerequisites
- MQTT broker running (e.g., Mosquitto)
- Home Assistant connected to the same MQTT broker

#### Configuration Steps

1. Add MQTT configuration to your `.env` file:
```bash
MQTT_BROKER=homeassistant.local  # or your broker's IP
MQTT_PORT=1883
MQTT_USERNAME=your_mqtt_username  # if authentication is enabled
MQTT_PASSWORD=your_mqtt_password
MQTT_TOPIC_PREFIX=octosynk
```

2. Restart the container:
```bash
docker-compose restart octosynk
```

3. Add the following to your Home Assistant `configuration.yaml`:

```yaml
mqtt:
  switch:
    - name: "Octosynk Auto-Sync"
      unique_id: octosynk_auto_sync
      command_topic: "octosynk/enabled"
      state_topic: "octosynk/enabled"
      payload_on: "ON"
      payload_off: "OFF"
      icon: mdi:solar-power

  sensor:
    - name: "Octosynk Last Sync"
      unique_id: octosynk_last_sync
      state_topic: "octosynk/last_sync"
      device_class: timestamp
      icon: mdi:clock-check

    - name: "Octosynk Active Slots"
      unique_id: octosynk_active_slots
      state_topic: "octosynk/active_slots"
      unit_of_measurement: "slots"
      icon: mdi:calendar-clock

    - name: "Octosynk Next Dispatch"
      unique_id: octosynk_next_dispatch
      state_topic: "octosynk/next_dispatch"
      device_class: timestamp
      icon: mdi:clock-start
```

4. Restart Home Assistant or reload the MQTT integration

You'll now have:
- A switch to enable/disable automatic syncing
- Sensors showing last sync time, active charging slots, and next dispatch time

### Managing the Deployment

View logs:
```bash
# All services
docker-compose logs -f

# Just octosynk
docker-compose logs -f octosynk

# Just scheduler
docker-compose logs -f ofelia
```

Stop the services:
```bash
docker-compose down
```

Restart after configuration changes:
```bash
docker-compose restart
```

Update to latest version:
```bash
docker-compose pull
docker-compose up -d
```

## Customizing the Schedule

The default schedule runs every 5 minutes. To change this, edit `docker-compose.yml`:

```yaml
ofelia.job-exec.octosynk-sync.schedule: "@every 10m"  # Every 10 minutes
# OR
ofelia.job-exec.octosynk-sync.schedule: "0 */6 * * *"  # Every 6 hours
```

See [Ofelia documentation](https://github.com/mcuadros/ofelia) for schedule syntax.

## Troubleshooting

### Application not running
```bash
docker-compose ps  # Check service status
docker-compose logs octosynk  # Check for errors
```

### Authentication failures
- Verify your API keys and credentials in `.env`
- Check that device IDs are correct
- Ensure Sunsynk password doesn't contain special characters that need escaping

### No healthcheck pings
- Verify `HEALTHCHECK_UUID` is set correctly
- Check logs for healthcheck warnings
- Ensure container has internet access
