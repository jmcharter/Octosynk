from dataclasses import dataclass


@dataclass
class Config:
    octopus_api_key: str
    device_id: str
    graphql_base_url: str
