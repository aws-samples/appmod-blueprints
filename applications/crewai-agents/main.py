"""CrewAI agent runner — dispatches to crew definitions by name."""
import os
import sys
import json
import importlib


def main():
    crew_name = os.environ.get("CREW_NAME", "cluster-health")
    crew_input = os.environ.get("CREW_INPUT", "{}")
    output_path = os.environ.get("OUTPUT_PATH", "/tmp/output/result.md")

    try:
        inputs = json.loads(crew_input)
    except json.JSONDecodeError:
        inputs = {"raw": crew_input}

    module = importlib.import_module(f"crews.{crew_name.replace('-', '_')}")
    crew = module.build_crew()

    print(f"Running crew: {crew_name}")
    result = crew.kickoff(inputs=inputs)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(result.raw)

    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
