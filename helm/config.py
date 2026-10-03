import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERP_URL = os.getenv("ERP_URL", "http://127.0.0.1:8001")
INVOICE_DIR = Path(os.getenv("INVOICE_DIR", ROOT / "data" / "invoices"))
ARTIFACTS = Path(os.getenv("ARTIFACTS_DIR", ROOT / "artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
HEADED = os.getenv("HELM_HEADED", "0") == "1"
SLOW_MO = int(os.getenv("HELM_SLOW_MO", "0"))
DEFAULT_AUTHORITY = float(os.getenv("DEFAULT_AUTHORITY", "2000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")
CHANNEL = os.getenv("HELM_CHANNEL", "")
