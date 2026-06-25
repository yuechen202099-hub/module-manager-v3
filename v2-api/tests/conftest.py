import os


# API regression tests use the deterministic in-memory/local JSON simulator.
# PostgreSQL cutover is verified by dedicated migration/repository gates; using
# a persistent developer PostgreSQL database here makes test results depend on
# local history.
os.environ["STATE_BACKEND"] = "json"


def pytest_configure(config):
    try:
        from app.core.config import settings
    except ModuleNotFoundError:
        return
    settings.state_backend = "json"
