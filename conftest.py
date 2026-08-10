"""Makes the project root importable from tests.

`python -m pytest` adds the working directory to sys.path; bare `pytest` does
not. A conftest.py at the root covers older pytest versions that ignore the
`pythonpath` setting in pytest.ini, so both invocations behave identically.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
