"""Production overlay: security and error logging."""

from .base import *  # noqa: F403,F401

DEBUG = False
ALLOWED_HOSTS = ["your-domain.com"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
LOGGING = build_logging_config(  # noqa: F405
    BASE_DIR,  # noqa: F405
    enabled=ERROR_LOGGING_ENABLED,  # noqa: F405
    debug=False,
)

SECRET_KEY = "YourSecretKey"    # Replace with your own secret key