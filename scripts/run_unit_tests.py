"""Запуск unit-тестов всех сервисов (каждый сервис — в отдельном процессе pytest).

    python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r tests/requirements.txt
    python scripts/run_unit_tests.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "libs" / "common"] + sorted(p for p in (ROOT / "services").iterdir() if (p / "tests").is_dir())

failed = []
for target in TARGETS:
    print(f"\n===== {target.name} =====", flush=True)
    code = subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "tests"], cwd=target)
    if code != 0:
        failed.append(target.name)

print("\n" + ("Все тесты прошли." if not failed else f"Упали: {', '.join(failed)}"))
sys.exit(1 if failed else 0)
