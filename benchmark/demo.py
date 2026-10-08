"""Live demo of steps 1-6 on one scenario.

    python -m benchmark.demo F01            # record ~30 s of live traffic, then diagnose
    python -m benchmark.demo F01 --reuse    # reuse the benchmark recording (no traffic)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.record import record
from benchmark.scenarios import by_id
from benchmark.workspace import fixed_copy
from sentinel.audit import AuditLog
from sentinel.pipeline import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    scenario = by_id(args.scenario)
    base = ROOT / "data" / "demo"
    recording_file = ROOT / "data" / "bench" / f"{scenario.id}-s0.json"
    if args.reuse and recording_file.exists():
        recording = json.loads(recording_file.read_text(encoding="utf-8"))
    else:
        print(f"[1] Running shared server, baseline traffic, then deploying: {scenario.title}")
        recording = record(scenario, base / scenario.id, base / f"{scenario.id}.json", baseline_s=15, incident_s=15)
    print(f"    deployment commits: {recording['deployment']}")
    audit_path = base / f"{scenario.id}-audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.unlink(missing_ok=True)
    fixed = fixed_copy(Path(recording["workspace"]), scenario, base / f"{scenario.id}-fixed")
    result = analyze(recording, AuditLog(audit_path), fixed_workspace=fixed, use_llm=not args.no_llm)
    if not result["incidents"]:
        print("[2] No incident detected. Recommended action: none")
        return
    incident = result["incidents"][0]
    print(f"[2] Incident {incident['id']} on {incident['service']}: {', '.join(incident['symptoms'])}")
    for signal in incident["signals"][:3]:
        print(f"      {signal['kind']} {signal['route'] or ''}: {signal['baseline']} -> {signal['observed']} (z={signal['z']})")
    print(f"[3-5] Top suspects (packet {result['packet_digest']}):")
    for suspect in result["suspects"][:3]:
        print(f"      {suspect['score']:.2f}  {suspect['chunk_id']}  {suspect['symbol']}")
        for reason in suspect["reasons"]:
            print(f"             - {reason}")
    if "llm" in result:
        print(f"      LLM ({result['llm']['model']}): {result['llm'].get('root_cause')}")
    print(f"      confidence {result['confidence']}, recommended action: {result['action']}")
    for name, test in result.get("tests", {}).items():
        faulty = (test.get("faulty") or {}).get("outcome")
        fixed_outcome = (test.get("fixed") or {}).get("outcome")
        print(f"[6] {name} test: faulty code -> {faulty}, fixed code -> {fixed_outcome}, confirming={test['confirming']}")
    print(f"Audit trail: {audit_path}")


if __name__ == "__main__":
    main()
