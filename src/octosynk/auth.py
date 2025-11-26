import base64
import hashlib
import time

import requests
import structlog
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = structlog.stdlib.get_logger(__name__)


class SunsynkAPIError(Exception): ...


class RetryableSunsynkError(SunsynkAPIError):
    """Raised for transient errors that should be retried"""

    pass


class AuthenticationError(SunsynkAPIError): ...


class Authenticator:
    """Handles Sunsynk API authentication with RSA encryption."""

    def __init__(self, username: str, password: str, timeout: float = 30):
        self.username = username
        self.password = password
        self._timeout = timeout
        self._access_token = None
        self._public_key_cache = None
        self._raw_public_key_cache = None  # Store raw key before PEM formatting

    def _sign_public_key_request(self, nonce: int, source: str = "sunsynk") -> str:
        """Sign the public key request using the known salt."""
        payload = f"nonce={nonce}&source={source}POWER_VIEW"
        return hashlib.md5(payload.encode()).hexdigest()

    def _sign_auth_request(self, nonce: int, public_key_prefix: str, source: str = "sunsynk") -> str:
        """Sign the authentication request using the public key prefix.

        Args:
            nonce: Timestamp in milliseconds
            public_key_prefix: First 10 characters of the public key
            source: Source identifier (default: "sunsynk")

        Returns:
            MD5 hash of "nonce={nonce}&source={source}{public_key_prefix}"
        """
        payload = f"nonce={nonce}&source={source}{public_key_prefix}"
        return hashlib.md5(payload.encode()).hexdigest()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RetryableSunsynkError, requests.ConnectionError)),
        reraise=True,
    )
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

            raw_public_key = data.get("data")
            if not raw_public_key:
                raise SunsynkAPIError(f"Public key not found in response: {data}")

            # Store the raw key before formatting (needed for signing)
            self._raw_public_key_cache = raw_public_key

            # Wrap the key in proper PEM format if it's just the base64 part
            public_key_pem = raw_public_key
            if not public_key_pem.startswith("-----BEGIN PUBLIC KEY-----"):
                public_key_pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_pem}\n-----END PUBLIC KEY-----"

            # Cache the formatted key for subsequent requests
            self._public_key_cache = public_key_pem
            return public_key_pem

        except requests.Timeout:
            logger.warning("Timeout fetching public key, will retry")
            raise RetryableSunsynkError("Timeout fetching public key")
        except requests.HTTPError as e:
            if e.response.status_code >= 500:
                logger.warning("Server error fetching public key, will retry", status_code=e.response.status_code)
                raise RetryableSunsynkError(f"HTTP server error: {e.response.status_code}")
            else:
                raise SunsynkAPIError(f"HTTP error fetching public key: {e.response.status_code}") from e
        except requests.RequestException as e:
            logger.warning("Network error fetching public key, will retry")
            raise RetryableSunsynkError(f"Network error fetching public key: {e}") from e

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RetryableSunsynkError, requests.ConnectionError)),
        reraise=True,
    )
    def authenticate(self) -> str:
        """Authenticate and return access token."""
        # Fetch the public key first
        public_key_pem = self._fetch_public_key()

        # Encrypt the password using the public key
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode(),
            backend=default_backend(),
        )
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise SunsynkAPIError(f"Expected RSA public key, got {type(public_key).__name__}")

        encrypted = public_key.encrypt(
            self.password.encode("utf-8"),
            padding.PKCS1v15(),
        )
        encrypted_password = base64.b64encode(encrypted).decode("utf-8")

        # Generate nonce and signature for the authentication request
        # The sign uses the first 10 characters of the RAW public key (before PEM formatting)!
        nonce = int(time.time() * 1000)  # milliseconds
        source = "sunsynk"
        public_key_prefix = self._raw_public_key_cache[:10]  # First 10 characters of raw key
        sign = self._sign_auth_request(nonce, public_key_prefix, source)

        logger.debug(
            "Auth request details",
            nonce=nonce,
            public_key_prefix=public_key_prefix,
            sign=sign,
        )

        payload = {
            "sign": sign,
            "nonce": nonce,
            "username": self.username,
            "password": encrypted_password,
            "grant_type": "password",
            "client_id": "csp-web",
            "source": source,
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
        except requests.Timeout:
            logger.warning("Authentication timeout, will retry")
            raise RetryableSunsynkError("Authentication timeout")
        except requests.HTTPError as e:
            # Don't retry auth errors (4xx) except for rate limiting (429)
            if e.response.status_code >= 500:
                logger.warning("Server error during authentication, will retry", status_code=e.response.status_code)
                raise RetryableSunsynkError(f"HTTP server error: {e.response.status_code}")
            elif e.response.status_code == 429:
                logger.warning("Rate limited, will retry")
                raise RetryableSunsynkError("Rate limited")
            else:
                logger.error("Authentication error", status=e.response.status_code)
                raise AuthenticationError("Invalid username or password") from e
        except requests.RequestException as e:
            logger.warning("Network error during auth, will retry")
            raise RetryableSunsynkError(f"Network error during auth: {e}") from e

        data = response.json()

        # Check for success based on 'success' field in the response
        if not data.get("success", False):
            logger.error("Authentication failed", response=data)
            raise AuthenticationError(f"Authentication failed: {data.get('msg', 'Unknown error')}")

        auth_data = data.get("data") or {}
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
