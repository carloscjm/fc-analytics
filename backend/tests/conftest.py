"""Os testes gravam o SQLite numa pasta temporária, nunca em backend/data."""

import os
import tempfile

os.environ.setdefault("FCA_DATA_DIR", tempfile.mkdtemp(prefix="fca-test-"))
