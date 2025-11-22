# Octosynk

Octosynk synchronizes Octopus Energy "Intelligent" tariff charging schedules with Sunsynk solar inverters, optimizing battery charging by combining regular off-peak rates with smart dispatch windows.

## Features

- Fetches planned dispatch times from Octopus Energy Intelligent API
- Merges dispatches with configured off-peak windows
- Generates optimized 6-slot charging schedule
- Updates Sunsynk inverter configuration automatically
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

### Initial Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd octosynk
```

2. Create your `.env` file with all required configuration (see Configuration section above)

3. Build and start the services:
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

Update to latest code:
```bash
git pull
docker-compose build
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
