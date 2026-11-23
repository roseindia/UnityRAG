"""Create the first Platform Super Admin (wrapper around `python -m app.cli create-platform-admin`).

    python scripts/create_admin.py --email admin@example.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.argv = [sys.argv[0], "create-platform-admin", *sys.argv[1:]]
from app.cli import main  # noqa: E402

main()
