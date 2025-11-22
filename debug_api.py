#!/usr/bin/env python3
import json
from octosynk.app import get_config
from octosynk.sunsynk import Client

config = get_config()
client = Client(config)
client.authenticate()

response = client._request("GET", "common/setting/2406164025/read")
data = response.json()

print("Full API response:")
print(json.dumps(data, indent=2))
