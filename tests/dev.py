"""Example dev script - run generate_example_json."""

import os

from poster2json.generate import generate_example_json

EXAMPLE_DATA = {"title": "Dev example", "version": "0.1.0"}


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "example_output.json")
    generate_example_json(EXAMPLE_DATA, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
