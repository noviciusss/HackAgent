from __future__ import annotations

import argparse
import collections
from pathlib import Path

from audit.classify import classify_request
from audit.identity import resolve_identity
from audit.ingest import load_dataset
from audit.planner import build_steps
from audit.policy import assess_all
from audit.serialize import validate_output, write_output
from audit.state import reconstruct


def run(dataset_dir: str | Path, out_path: str | Path, requests_file: str | Path | None = None, enable_vision: bool = True) -> dict[str, int]:
    dataset = load_dataset(dataset_dir, requests_file, enable_vision=enable_vision)
    output_rows: list[dict[str, object]] = []
    counts: collections.Counter[str] = collections.Counter()
    for request in dataset.requests:
        if classify_request(request["request_text"]) == "NOT_APPLICABLE":
            status = "NOT_APPLICABLE"
            steps: list[dict[str, object]] = []
        else:
            identity = resolve_identity(dataset, request["email"], request["requested_at"])
            if identity is None:
                status = "INCOMPLETE"
                steps = []
            else:
                observations = reconstruct(dataset, identity, request["audit_at"], request)
                assessments = assess_all(observations, request.get("request_text", ""), request.get("audit_at"))
                status = "COMPLETE" if all(item.compliant for item in assessments) else "INCOMPLETE"
                steps = build_steps(assessments, status)
        counts[status] += 1
        output_rows.append({"case_id": request["case_id"], "deletion_status": status, "steps_json": steps})
    write_output(output_rows, out_path)
    row_count, errors = validate_output(out_path, [r["case_id"] for r in dataset.requests])
    if errors:
        raise RuntimeError("output validation failed: " + "; ".join(errors[:5]))
    print(f"loaded_requests={len(dataset.requests)} facts={len(dataset.facts)} output_rows={row_count}")
    print("statuses=" + ",".join(f"{key}:{counts[key]}" for key in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")))
    print(f"output={Path(out_path).resolve()}")
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    dataset_default = "dataset" if Path("dataset").is_dir() else "../dataset"
    out_default = "output.csv" if Path("dataset").is_dir() else "../output.csv"
    parser.add_argument("--dataset-dir", default=dataset_default)
    parser.add_argument("--out", default=out_default)
    parser.add_argument("--requests-file", default=None)
    parser.add_argument("--no-vision", action="store_true", help="Disable vision extraction")
    args = parser.parse_args()
    run(args.dataset_dir, args.out, args.requests_file, enable_vision=not args.no_vision)



if __name__ == "__main__":
    main()
