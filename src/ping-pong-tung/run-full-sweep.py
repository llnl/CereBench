#!/usr/bin/env python3

import csv
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(".").resolve()
TEST_RC = ROOT / "test.rc"
CSV_OUT = ROOT / "perf_results.csv"

HARNESS_LINE_RE = re.compile(
    r"""
    ^\s*
    (?P<harness_name>\S+)
    \s*:\s*
    (?:
        (?P<wallclock>\d+:\d+\.\d+)\s+
        (?P<status>PASS|FAIL|UNKNOWN)\s+
        (?P<test_index>\d+)\s*
        \[
            (?P<bracket_content>[^\]]*)
        \]
    |
        Command\s+exited\s+with\s+non-zero\s+status\s+(?P<exit_status>\d+)\s+
        (?P<fail_wallclock>\d+:\d+\.\d+)\s+
        (?P<fail_status>FAIL|UNKNOWN)\s+
        (?P<fail_test_index>\d+)\s*
        \[
            (?P<fail_bracket_content>[^\]]*)
        \]
    )
    \s*$
    """,
    re.VERBOSE,
)

KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def parse_test_rc(path: Path):
    tests = []
    with path.open() as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            suite = parts[0]
            params = {}
            for token in parts[1:]:
                if "=" in token:
                    k, v = token.split("=", 1)
                    params[k] = v

            tests.append(
                {
                    "test_index": len(tests) + 1,
                    "suite": suite,
                    "raw_line": line,
                    "source_lineno": lineno,
                    "ARCH": params.get("ARCH"),
                    "tensor_size": to_int(params.get("tensor_size")),
                    "DIST": to_int(params.get("DIST")),
                    "NUM_MSGS": to_int(params.get("NUM_MSGS")),
                }
            )
    return tests


def to_int(x):
    if x is None or x == "":
        return None
    try:
        return int(x)
    except ValueError:
        return None


def run_make_test(test_index: int):
    cmd = ["make", "wafer-run", f"TEST={test_index}"]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    combined = ""
    if proc.stdout:
        combined += proc.stdout
    if proc.stderr:
        combined += ("\n" if combined else "") + proc.stderr
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "combined": combined,
        "cmd": " ".join(cmd),
    }


def parse_harness_output(text: str):
    info = {
        "harness_name": None,
        "harness_status": None,
        "harness_wallclock": None,
        "summary_test_index": None,
        "summary_exit_status": None,
        "summary_ARCH": None,
        "summary_tensor_size": None,
        "summary_DIST": None,
        "summary_NUM_MSGS": None,
        "raw_harness_line": None,
    }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines):
        m = HARNESS_LINE_RE.match(line)
        if not m:
            continue

        info["raw_harness_line"] = line
        info["harness_name"] = m.group("harness_name")

        if m.group("status"):
            info["harness_status"] = m.group("status")
            info["harness_wallclock"] = m.group("wallclock")
            info["summary_test_index"] = to_int(m.group("test_index"))
            bracket = m.group("bracket_content") or ""
        else:
            info["harness_status"] = m.group("fail_status")
            info["harness_wallclock"] = m.group("fail_wallclock")
            info["summary_test_index"] = to_int(m.group("fail_test_index"))
            info["summary_exit_status"] = to_int(m.group("exit_status"))
            bracket = m.group("fail_bracket_content") or ""

        kv = dict(KV_RE.findall(bracket))
        info["summary_ARCH"] = kv.get("ARCH")
        info["summary_tensor_size"] = to_int(kv.get("tensor_size"))
        info["summary_DIST"] = to_int(kv.get("DIST"))
        info["summary_NUM_MSGS"] = to_int(kv.get("NUM_MSGS"))
        break

    return info


def load_json_if_exists(path: Path):
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return None


def read_text_if_exists(path: Path):
    if not path.exists():
        return None
    try:
        return path.read_text(errors="replace")
    except Exception:
        return None


def parse_sim_log(path: Path):
    text = read_text_if_exists(path)
    result = {
        "sim_log_path": str(path) if path.exists() else None,
        "router_clean": None,
        "log_stop_idle": None,
        "log_cycle_count": None,
        "log_idle_ce_cycles": None,
        "log_idle_wavelet_cycles": None,
    }
    if text is None:
        return result

    result["router_clean"] = "All router state is clean." in text
    result["log_stop_idle"] = "Stopped due to idleness" in text

    m = re.search(r"cycles=(\d+)", text)
    if m:
        result["log_cycle_count"] = int(m.group(1))

    m = re.search(
        r"(\d+)\s+cycles since an instruction was executed,\s+(\d+)\s+cycles since a wavelet landed",
        text,
    )
    if m:
        result["log_idle_ce_cycles"] = int(m.group(1))
        result["log_idle_wavelet_cycles"] = int(m.group(2))

    return result


def parse_make_log(path: Path):
    text = read_text_if_exists(path)
    result = {
        "make_log_path": str(path) if path.exists() else None,
        "make_empty_arch": None,
        "make_empty_tensor_size": None,
        "make_empty_DIST": None,
        "make_empty_NUM_MSGS": None,
        "make_source_not_specified": None,
        "make_invalid_terms": None,
        "make_failure_snippet": None,
    }
    if text is None:
        return result

    result["make_empty_arch"] = " arch= " in f" {text} " or " arch=\n" in text or " arch= set=" in text or "arch=" in text and "verbose arch=" in text
    result["make_empty_tensor_size"] = "set=tensor_size=" in text
    result["make_empty_DIST"] = "set=DIST=" in text
    result["make_empty_NUM_MSGS"] = "set=NUM_MSGS=" in text
    result["make_source_not_specified"] = "Command-line error: 'source' not specified" in text
    result["make_invalid_terms"] = "invalid command-line terms" in text

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if "Command-line error" in s or "Error" in s or "invalid command-line terms" in s:
            result["make_failure_snippet"] = s
            break

    return result

def classify_failure(row):
    if row["returncode"] == 0:
        return "pass"

    if row["harness_status"] == "PASS":
        return "pass"

    if row["cycle_count"] == row["cycle_limit"] and row["cycle_count"] is not None:
        return "timeout"

    if row["sim_stats_path"] and row["returncode"] != 0:
        return "post_sim_fail"

    if row["make_empty_tensor_size"] or row["make_empty_DIST"] or row["make_empty_NUM_MSGS"] or row["make_empty_arch"]:
        return "setup_empty_vars"

    if row["make_source_not_specified"]:
        return "paint_cmdline_fail"

    if row["returncode"] != 0 and not row["sim_stats_path"]:
        return "early_build_fail"

    return "unknown_fail"

def classify_failure(row):
        if row["returncode"] == 0:
                    return "pass"
                
                    if row["harness_status"] == "PASS":
                                return "pass"
                            
                                if row["cycle_count"] == row["cycle_limit"] and row["cycle_count"] is not None:
                                            return "timeout"
                                        
                                            if row["sim_stats_path"] and row["returncode"] != 0:
                                                        return "post_sim_fail"
                                                    
                                                        if row["make_empty_tensor_size"] or row["make_empty_DIST"] or row["make_empty_NUM_MSGS"] or row["make_empty_arch"]:
                                                                    return "setup_empty_vars"
                                                                
                                                                    if row["make_source_not_specified"]:
                                                                                return "paint_cmdline_fail"
                                                                            
                                                                                if row["returncode"] != 0 and not row["sim_stats_path"]:
                                                                                            return "early_build_fail"
                                                                                        
                                                                                            return "unknown_fail"

def build_row(test_meta, run_info):
    idx = test_meta["test_index"]

    test_dir = ROOT / f"test-{idx}"
    sim_stats_path = test_dir / "sim_stats.json"
    sim_log_path = test_dir / "bench-sim.log"
    make_log_path = test_dir / "make-log"

    harness = parse_harness_output(run_info["combined"])
    sim_stats = load_json_if_exists(sim_stats_path)
    sim_log = parse_sim_log(sim_log_path)
    make_log = parse_make_log(make_log_path)

    cycle_limit = 20000

    row = {
        "test_index": idx,
        "suite": test_meta["suite"],
        "source_lineno": test_meta["source_lineno"],
        "raw_line": test_meta["raw_line"],
        "ARCH": test_meta["ARCH"],
        "tensor_size": test_meta["tensor_size"],
        "DIST": test_meta["DIST"],
        "NUM_MSGS": test_meta["NUM_MSGS"],
        "command": run_info["cmd"],
        "returncode": run_info["returncode"],

        "harness_name": harness["harness_name"],
        "harness_status": harness["harness_status"],
        "harness_wallclock": harness["harness_wallclock"],
        "raw_harness_line": harness["raw_harness_line"],

        "summary_test_index": harness["summary_test_index"],
        "summary_exit_status": harness["summary_exit_status"],
        "summary_ARCH": harness["summary_ARCH"],
        "summary_tensor_size": harness["summary_tensor_size"],
        "summary_DIST": harness["summary_DIST"],
        "summary_NUM_MSGS": harness["summary_NUM_MSGS"],

        "sim_stats_path": str(sim_stats_path) if sim_stats_path.exists() else None,
        "sim_log_path": sim_log["sim_log_path"],
        "make_log_path": make_log["make_log_path"],

        "cycle_count": sim_stats.get("cycle_count") if sim_stats else None,
        "cycles_per_second": sim_stats.get("cycles_per_second") if sim_stats else None,
        "idle_ce_cycles": sim_stats.get("idle_ce_cycles") if sim_stats else None,
        "idle_wavelet_cycles": sim_stats.get("idle_wavelet_cycles") if sim_stats else None,
        "init_time": sim_stats.get("init_time") if sim_stats else None,
        "sim_time": sim_stats.get("sim_time") if sim_stats else None,
        "total_time": sim_stats.get("total_time") if sim_stats else None,
        "sunset_count": sim_stats.get("sunset_count") if sim_stats else None,
        "sim_stop_cause": sim_stats.get("sim_stop_cause") if sim_stats else None,
        "fabric_x": sim_stats.get("fabric_x") if sim_stats else None,
        "fabric_y": sim_stats.get("fabric_y") if sim_stats else None,
        "tile_count": sim_stats.get("tile_count") if sim_stats else None,
        "simulated_tile_count": sim_stats.get("simulated_tile_count") if sim_stats else None,
        "hwtile_count": sim_stats.get("hwtile_count") if sim_stats else None,
        "iotile_count": sim_stats.get("iotile_count") if sim_stats else None,
        "nultile_count": sim_stats.get("nultile_count") if sim_stats else None,
        "threads": sim_stats.get("threads") if sim_stats else None,
        "nodes": sim_stats.get("nodes") if sim_stats else None,

        "router_clean": sim_log["router_clean"],
        "log_stop_idle": sim_log["log_stop_idle"],
        "log_cycle_count": sim_log["log_cycle_count"],
        "log_idle_ce_cycles": sim_log["log_idle_ce_cycles"],
        "log_idle_wavelet_cycles": sim_log["log_idle_wavelet_cycles"],

        "make_empty_arch": make_log["make_empty_arch"],
        "make_empty_tensor_size": make_log["make_empty_tensor_size"],
        "make_empty_DIST": make_log["make_empty_DIST"],
        "make_empty_NUM_MSGS": make_log["make_empty_NUM_MSGS"],
        "make_source_not_specified": make_log["make_source_not_specified"],
        "make_invalid_terms": make_log["make_invalid_terms"],
        "make_failure_snippet": make_log["make_failure_snippet"],

        "cycle_limit": cycle_limit,
    }

    dist = row["DIST"]
    tensor_size = row["tensor_size"]
    num_msgs = row["NUM_MSGS"]
    cycle_count = row["cycle_count"]
    idle_ce = row["idle_ce_cycles"]

    one_way_hops = None if dist is None else dist + 1
    round_trip_hops = None if one_way_hops is None else 2 * one_way_hops
    total_payload_words = None
    if tensor_size is not None and num_msgs is not None:
        total_payload_words = tensor_size * num_msgs

    fabric_word_hops = None
    if tensor_size is not None and num_msgs is not None and round_trip_hops is not None:
        fabric_word_hops = tensor_size * num_msgs * round_trip_hops

    useful_cycles_est = None
    if cycle_count is not None and idle_ce is not None:
        useful_cycles_est = cycle_count - idle_ce

    row.update(
        {
            "one_way_hops": one_way_hops,
            "round_trip_hops": round_trip_hops,
            "total_payload_words": total_payload_words,
            "fabric_word_hops": fabric_word_hops,
            "useful_cycles_est": useful_cycles_est,
            "timed_out": bool(cycle_count is not None and cycle_count >= cycle_limit),
            "cycles_per_msg": safe_div(cycle_count, num_msgs),
            "cycles_per_payload_word": safe_div(cycle_count, total_payload_words),
            "cycles_per_word_hop": safe_div(cycle_count, fabric_word_hops),
            "idle_fraction_est": safe_div(idle_ce, cycle_count),
        }
    )

    row["failure_class"] = classify_failure(row)
    if row["harness_status"] is None and row["returncode"] == 0:
        row["harness_status"] = "PASS"
        row["raw_harness_line"] = "direct sim-run completed successfully"
    if row["returncode"] == 0 or row["failure_class"] == "pass":
        row["correctness"] = "pass"
    elif row["failure_class"] == "timeout":
        row["correctness"] = "timeout_fail"
    elif row["failure_class"] in ("setup_empty_vars", "paint_cmdline_fail", "early_build_fail"):
        row["correctness"] = "build_fail"
    elif row["failure_class"] == "post_sim_fail":
        row["correctness"] = "post_sim_fail"
    else:
        row["correctness"] = "unknown"

    return row


def write_csv(rows, out_path: Path):
    if not rows:
        return

    fieldnames = [
        "test_index",
        "suite",
        "source_lineno",
        "raw_line",
        "ARCH",
        "tensor_size",
        "DIST",
        "NUM_MSGS",

        "command",
        "returncode",

        "harness_name",
        "harness_status",
        "harness_wallclock",
        "raw_harness_line",

        "summary_test_index",
        "summary_exit_status",
        "summary_ARCH",
        "summary_tensor_size",
        "summary_DIST",
        "summary_NUM_MSGS",

        "sim_stats_path",
        "sim_log_path",
        "make_log_path",

        "cycle_count",
        "cycles_per_second",
        "idle_ce_cycles",
        "idle_wavelet_cycles",
        "init_time",
        "sim_time",
        "total_time",
        "sunset_count",
        "sim_stop_cause",
        "fabric_x",
        "fabric_y",
        "tile_count",
        "simulated_tile_count",
        "hwtile_count",
        "iotile_count",
        "nultile_count",
        "threads",
        "nodes",

        "router_clean",
        "log_stop_idle",
        "log_cycle_count",
        "log_idle_ce_cycles",
        "log_idle_wavelet_cycles",

        "make_empty_arch",
        "make_empty_tensor_size",
        "make_empty_DIST",
        "make_empty_NUM_MSGS",
        "make_source_not_specified",
        "make_invalid_terms",
        "make_failure_snippet",

        "cycle_limit",
        "one_way_hops",
        "round_trip_hops",
        "total_payload_words",
        "fabric_word_hops",
        "useful_cycles_est",
        "timed_out",
        "cycles_per_msg",
        "cycles_per_payload_word",
        "cycles_per_word_hop",
        "idle_fraction_est",

        "failure_class",
        "correctness",
    ]

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    tests = parse_test_rc(TEST_RC)
    rows = []

    print(f"Found {len(tests)} tests in {TEST_RC}")

    for t in tests:
        idx = t["test_index"]
        print(f"[{idx}/{len(tests)}] Running TEST={idx} ...")
        run_info = run_make_test(idx)
        row = build_row(t, run_info)
        rows.append(row)

        print(
            f"  status={row['harness_status']} "
            f"returncode={row['returncode']} "
            f"cycle_count={row['cycle_count']} "
            f"failure_class={row['failure_class']}"
        )

    write_csv(rows, CSV_OUT)
    print(f"Wrote {CSV_OUT}")


if __name__ == "__main__":
    main()
