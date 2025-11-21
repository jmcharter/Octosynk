import base64
import hashlib
import time

import requests
import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = structlog.stdlib.get_logger(__name__)


class SunsynkAPIError(Exception): ...


class AuthenticationError(SunsynkAPIError): ...


class Authenticator:
    """Handles Sunsynk API authentication with RSA encryption."""

    def __init__(self, username: str, password: str, timeout: float = 30):
        self.username = username
        self.password = password
        self._timeout = timeout
        self._access_token = None
        self._public_key_cache = None

    def _sign_public_key_request(self, nonce: int, source: str = "sunsynk") -> str:
        """Sign the public key request using the known salt."""
        payload = f"nonce={nonce}&source={source}POWER_VIEW"
        return hashlib.md5(payload.encode()).hexdigest()

    def _fetch_public_key(self, source: str = "sunsynk") -> str:
        """Fetch the RSA public key from the dynamic endpoint."""
        if self._public_key_cache:
            return self._public_key_cache

        nonce = int(time.time() * 1000)  # milliseconds
        sign = self._sign_public_key_request(nonce, source)

        url = f"https://api.sunsynk.net/anonymous/publicKey?nonce={nonce}&source={source}&sign={sign}"

        try:
            response = requests.get(url, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()

            # Check for success based on 'success' field in the response
            if not data.get("success", False):
                raise SunsynkAPIError(f"Failed to fetch public key: {data}")

            public_key_pem = data.get("data")
            if not public_key_pem:
                raise SunsynkAPIError(f"Public key not found in response: {data}")

            # Wrap the key in proper PEM format if it's just the base64 part
            if not public_key_pem.startswith("-----BEGIN PUBLIC KEY-----"):
                public_key_pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_pem}\n-----END PUBLIC KEY-----"

            # Cache the key for subsequent requests
            self._public_key_cache = public_key_pem
            return public_key_pem

        except requests.RequestException as e:
            raise SunsynkAPIError(f"Network error fetching public key: {e}") from e

    def _encrypt_password(self, password: str) -> str:
        """Encrypt password using the dynamically fetched RSA public key."""
        public_key_pem = self._fetch_public_key()

        # Load the public key
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode(),
            backend=default_backend(),
        )

        # Ensure it's an RSA key before attempting encryption
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise SunsynkAPIError(f"Expected RSA public key, got {type(public_key).__name__}")

        # Use the RSA public key's encrypt method with proper padding
        encrypted = public_key.encrypt(
            password.encode("utf-8"),
            padding.PKCS1v15(),  # This is the correct padding for RSA
        )
        return base64.b64encode(encrypted).decode("utf-8")

    def authenticate(self) -> str:
        """Authenticate and return access token."""
        encrypted_password = self._encrypt_password(self.password)

        payload = {
            "username": self.username,
            "password": encrypted_password,
            "grant_type": "password",
            "client_id": "csp-web",
            "source": "sunsynk",
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.sunsynk.net",
            "Referer": "https://www.sunsynk.net/",
        }

        try:
            response = requests.post(
                "https://api.sunsynk.net/oauth/token/new",
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            logger.error("Authentication error", status=e.response.status_code)
            raise AuthenticationError("Invalid username or password") from e
        except requests.RequestException as e:
            raise SunsynkAPIError(f"Network error during auth: {e}") from e

        data = response.json()
        auth_data = data.get("data", {})
        if "access_token" not in auth_data:
            raise SunsynkAPIError(f"Unexpected auth response: {data}")

        self._access_token = auth_data.get("access_token")
        return self._access_token

    def get_token(self) -> str | None:
        """Get the current access token, authenticating if necessary."""
        if not self._access_token:
            return self.authenticate()
        return self._access_token

    def clear_token(self):
        """Clear the existing access token"""
        self._access_token = None
