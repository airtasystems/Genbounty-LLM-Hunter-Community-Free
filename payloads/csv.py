"""
CSV payload generator. Custom content (paste) or generated dummy data.
Uses stdlib csv; optional Faker for realistic dummy data.
"""
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from payloads.config import get_output_dir
from payloads._utils import resolve_output_path

# Dummy data: simple fallbacks when Faker is not available
_WORDS = ("alpha", "beta", "gamma", "delta", "item", "user", "test", "data", "sample", "row", "col", "value", "foo", "bar", "baz")
_NAMES = ("Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Henry", "Ivy", "Jack")


def _generate_cell(column: Dict[str, Any], row_index: int, use_faker: bool) -> str:
    """Generate one cell value for dummy data. column has 'name' and 'type'."""
    col_type = (column.get("type") or "text").strip().lower()
    seed = hash((column.get("name", ""), row_index)) % (2**32)
    rng = random.Random(seed)

    if use_faker:
        try:
            from faker import Faker
            fake = Faker()
            if hasattr(fake, "seed_instance"):
                fake.seed_instance(seed)
            if col_type in ("email", "mail"):
                return fake.email()
            if col_type in ("name", "full_name", "person"):
                return fake.name()
            if col_type in ("date", "date_of_birth", "dob"):
                return fake.date_between(start_date="-5y", end_date="today").isoformat()
            if col_type == "address":
                return fake.address().replace("\n", ", ")[:80]
            if col_type == "phone":
                return fake.phone_number()
        except ImportError:
            use_faker = False

    # Fallback without Faker
    if col_type in ("integer", "int", "id", "number"):
        return str(rng.randint(1, 99999))
    if col_type in ("float", "decimal", "amount"):
        return f"{rng.uniform(0.01, 9999.99):.2f}"
    if col_type in ("date", "date_of_birth", "dob"):
        d = datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 3650))
        return d.strftime("%Y-%m-%d")
    if col_type in ("email", "mail"):
        u = rng.choice(_NAMES).lower() + str(rng.randint(1, 999))
        return f"{u}@example.com"
    if col_type in ("name", "full_name", "person"):
        return rng.choice(_NAMES) + " " + rng.choice(_NAMES)
    # text or default
    n = rng.randint(1, 4)
    return " ".join(rng.choices(_WORDS, k=n))


def _parse_columns(columns_spec: Optional[Union[str, List]]) -> List[Dict[str, Any]]:
    """
    Parse columns from API: comma-separated names, or "name:type,name:type", or list of dicts.
    Returns list of {"name": str, "type": str}.
    """
    if columns_spec is None:
        return [{"name": "id", "type": "integer"}, {"name": "value", "type": "text"}]
    if isinstance(columns_spec, list):
        out = []
        for c in columns_spec:
            if isinstance(c, dict):
                out.append({"name": str(c.get("name", "col")).strip() or "col", "type": str(c.get("type", "text")).strip() or "text"})
            else:
                out.append({"name": str(c).strip() or "col", "type": "text"})
        return out if out else [{"name": "id", "type": "integer"}, {"name": "value", "type": "text"}]
    s = str(columns_spec).strip()
    if not s:
        return [{"name": "id", "type": "integer"}, {"name": "value", "type": "text"}]
    out = []
    for part in s.split(","):
        part = part.strip()
        if ":" in part:
            name, col_type = part.split(":", 1)
            out.append({"name": name.strip() or "col", "type": col_type.strip() or "text"})
        else:
            out.append({"name": part or "col", "type": "text"})
    return out if out else [{"name": "id", "type": "integer"}, {"name": "value", "type": "text"}]


def create_csv(
    content: Optional[str] = None,
    columns: Optional[Union[str, List]] = None,
    num_rows: int = 10,
    filename: Optional[str] = None,
    subdir: str = "docs",
    use_faker: bool = True,
) -> Path:
    """
    Create a CSV file. Either use custom content (raw CSV text) or generate dummy data.

    - content: if provided, written as-is (first line can be header). UTF-8.
    - columns: used only when content is None. Comma-separated "name" or "name:type".
      Types: text, integer, float, date, email, name. Default column set if empty.
    - num_rows: number of data rows to generate (ignored if content is provided). Capped at 10000.
    - use_faker: if True, use Faker for email/name/date when available.

    Returns absolute path to the created file.
    """
    base = get_output_dir()
    path = resolve_output_path(filename, subdir, "csv", base)
    num_rows = max(0, min(10000, int(num_rows)))

    if content is not None and content.strip():
        path.write_text(content.strip(), encoding="utf-8")
        return path.resolve()

    col_list = _parse_columns(columns)
    header = [c["name"] for c in col_list]
    rows = [header]
    for i in range(num_rows):
        rows.append([_generate_cell(c, i, use_faker) for c in col_list])

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return path.resolve()
