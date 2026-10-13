"""Mark every test under tests/integration/ as an integration test.

pytest.ini deselects the ``integration`` marker by default, so a bare
``pytest`` run stays fast. Applying the marker here covers new files
automatically; explicit ``pytestmark`` or per-test markers stay valid.
"""

from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        if INTEGRATION_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)
