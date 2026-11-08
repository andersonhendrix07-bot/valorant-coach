"""Save one REAL match from the API as a test fixture (tests/fixtures/real_<match_id>.json).

    python scripts/save_fixture.py na <match_id>

Real fixtures are picked up automatically by tests/test_real_fixtures.py, which checks
invariants (KAST <= 100%, one first kill per round with kills, sides add up, ...) for every
player in the match. Large position arrays are dropped to keep the file small.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

from api_client import HenrikClient  # noqa: E402


def strip_positions(obj):
    if isinstance(obj, dict):
        return {k: strip_positions(v) for k, v in obj.items() if k != "player_locations"}
    if isinstance(obj, list):
        return [strip_positions(v) for v in obj]
    return obj


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    region, match_id = sys.argv[1], sys.argv[2]
    load_dotenv()
    match = HenrikClient(os.getenv("HENRIKDEV_API_KEY", "")).get_match(region, match_id)
    out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / f"real_{match_id}.json"
    out.write_text(json.dumps(strip_positions(match), indent=1))
    print("saved", out)


if __name__ == "__main__":
    main()
