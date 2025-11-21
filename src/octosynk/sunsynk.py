from octosynk.config import Config
import requests


class Client:
    base_url: str
    token: str | None

    def __init__(self, config: Config):
        self.base_url = config.sunsynk_api_url
        self.auth_url = config.sunsynk_auth_url

    def get_token(self):
        pass
