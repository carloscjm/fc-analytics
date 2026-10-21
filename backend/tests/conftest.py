"""Os testes gravam o SQLite numa pasta temporária, nunca em backend/data."""

import os
import tempfile

os.environ.setdefault("FCA_DATA_DIR", tempfile.mkdtemp(prefix="fca-test-"))
os.environ.setdefault("FCA_INSIGHTS_PUMP", "0")
os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:9")  # porta fechada: nada de Ollama de verdade nos testes
