"""Write the API's OpenAPI spec to a file (used to generate the Angular client types)."""

import json
import sys
import tempfile
from pathlib import Path

from openscope.api.app import create_app
from openscope.api.settings import Settings

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
with tempfile.TemporaryDirectory() as d:
    spec = create_app(Settings(db_url=f"sqlite:///{d}/spec.db")).openapi()
out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {out}")
