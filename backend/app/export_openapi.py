"""Write the OpenAPI spec to a file (default: ../frontend/openapi.json). No DB required.

Usage: python -m app.export_openapi [output_path]
"""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    default = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
