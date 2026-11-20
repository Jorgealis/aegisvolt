"""Exporta el esquema GraphQL (SDL) a services/graphql-gateway/schema.graphql.

python scripts/export_schema.py           # escribe el archivo
python scripts/export_schema.py --check   # CI: falla si el archivo no está al día
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services" / "common"), str(ROOT / "services" / "graphql-gateway")]

from graphql_gateway.schema import schema  # noqa: E402

TARGET = ROOT / "services" / "graphql-gateway" / "schema.graphql"


def main() -> None:
    sdl = schema.as_str() + "\n"
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != sdl:
            raise SystemExit("schema.graphql desactualizado: ejecuta python scripts/export_schema.py")
        print("schema.graphql al día")
        return
    TARGET.write_text(sdl, encoding="utf-8", newline="\n")
    print(f"escrito {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
