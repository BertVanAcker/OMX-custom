from pathlib import Path
import sys


EXAMPLES = Path(__file__).resolve().parents[1]
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

from _shared import run_example  # noqa: E402


def main() -> int:
    return run_example(
        "gripper",
        ["home", "min", "home"],
    )


if __name__ == "__main__":
    raise SystemExit(main())
