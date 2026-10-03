"""Start MiniLedger (:8001) and HelmOps (:8000) together. Ctrl-C stops both."""
import subprocess, sys, time
procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", m, "--port", p])
         for m, p in (("erp.app:app", "8001"), ("helm.server:app", "8000"))]
print("\nHelmOps dashboard: http://127.0.0.1:8000\nMiniLedger ERP:   http://127.0.0.1:8001/bills\n")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    for p in procs:
        p.terminate()
