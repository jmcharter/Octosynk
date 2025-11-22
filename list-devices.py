#!/usr/bin/env python3
"""List Octopus Energy devices for an account.

Usage:
    python list-devices.py <account_number>

Example:
    python list-devices.py A-12345678
"""

import os
import sys
import structlog
from octosynk.config import Config
from octosynk.octopus import GraphQLClient

logger = structlog.stdlib.get_logger(__name__)


def main():
    if len(sys.argv) != 2:
        print("Usage: python list-devices.py <account_number>")
        print("Example: python list-devices.py A-12345678")
        sys.exit(1)

    account_number = sys.argv[1]

    # Get API key from environment
    api_key = os.environ.get("OCTOPUS_API_KEY")
    if not api_key:
        print("Error: OCTOPUS_API_KEY environment variable is required")
        print("Set it in your .env file or export it: export OCTOPUS_API_KEY=your_key")
        sys.exit(1)

    # Create a minimal config for the GraphQL client
    api_url = os.environ.get("OCTOPUS_API_URL", "https://api.octopus.energy/v1/graphql/")

    # We need a Config object, but most fields aren't needed for this query
    # Create a minimal config with dummy values for required fields
    from datetime import time
    config = Config(
        octopus_api_key=api_key,
        octopus_device_id="",  # Not needed for device listing
        octopus_api_url=api_url,
        sunsynk_auth_url="",
        sunsynk_api_url="",
        sunsynk_username="",
        sunsynk_password="",
        sunsynk_device_id="",
        off_peak_start_time=time(0, 0),
        off_peak_end_time=time(0, 0),
    )

    try:
        # Create client and authenticate
        client = GraphQLClient(config=config)
        client.authenticate()

        # Query devices
        print(f"\nQuerying devices for account: {account_number}")
        print("=" * 60)
        devices = client.query_devices(account_number)

        if not devices:
            print("No devices found for this account.")
            return

        # Print device information
        print(f"\nFound {len(devices)} device(s):\n")
        for device in devices:
            device_id = device.get("id", "N/A")
            device_name = device.get("name", "N/A")
            device_type = device.get("deviceType", "N/A")

            print(f"ID:   {device_id}")
            print(f"Name: {device_name}")
            print(f"Type: {device_type}")
            print("-" * 60)

        print(f"\nTo use a device, set OCTOPUS_DEVICE_ID to one of the IDs above in your .env file")

    except Exception as e:
        logger.exception("Failed to query devices")
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
