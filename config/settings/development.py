from .base import *  # noqa: F403,F401

DEBUG = True
LOGGING = build_logging_config(  # noqa: F405
    BASE_DIR,  # noqa: F405
    enabled=ERROR_LOGGING_ENABLED,  # noqa: F405
    debug=True,
)
