"""Pytest configuration for the blob-service suite.

Living at the repository root, this file makes pytest put the root on
sys.path, so `import config` and `import services.*` resolve the same way
they do when the app runs. Without it, pytest only adds tests/ and every
import of application code fails with ModuleNotFoundError.

It also supplies the settings config.py requires. Configuration is
fail-closed by design — importing config with nothing set raises RuntimeError
rather than falling back to a default credential — so the suite needs a
baseline. Everything here is obviously fake; tests that care about a
particular value override it with monkeypatch.
"""

import os

_TEST_DEFAULTS = {
    "AWS_ACCESS_KEY_ID": "test-access-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret-key",
    "POSTGRES_USER": "test-user",
    "POSTGRES_PASSWORD": "test-password",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "test-db",
    # Keep the S3 client from reaching out to a gateway during import.
    "PHASICON_DISABLE_S3_INIT": "1",
}

for _name, _value in _TEST_DEFAULTS.items():
    os.environ.setdefault(_name, _value)
