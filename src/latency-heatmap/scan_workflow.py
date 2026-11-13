import argparse
import csv
import math
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


FULL_FETCH_SYMBOLS = [
    "center.target_x",
    "center.target_y",
    "center.reply_x",
    "center.reply_y",
    "center.reply_seq",
    "center.reply_dbg_row",
    "center.t_start",
    "center.t_stop",
    "center.done",
    "center.count",
    "center.send_count",
    "center.last_sent_x",
    "center.last_sent_y",
]

DONE_POLL_SYMBOLS = [
    "center.done",
    "center.count",
]

DEBUG_SYMBOLS = [
    "center.done",
    "center.count",
    "center.send_count",
    "center.last_sent_x",
    "center.last_sent_y",
    "center.reply_dbg_row",
]


class TeeLogger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a", encoding="utf-8")

    def log(self, msg=""):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


def run_logged(cmd, logger, env=None, cwd=None, check=True):
    logger.log("+ " + " ".join(str(x) for x in cmd))
    p = subprocess.Popen(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=cwd,
        bufsize=1,
    )
    lines = []
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip("\n")
        lines.append(line)
        logger.log(line)
    rc = p.wait()
    if check and rc != 0:
        raise subprocess.CalledProcessError(rc, [str(x) for x in cmd])
    return rc, "\n".join(lines)


def csenv(server):
    env = os.environ.copy()
    if server:
        env["CSRTSERV"] = server
    return env


def clean_dir(path):
    p = Path(path)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def write_targets(xs, ys):
    np.asarray(xs, dtype=np.int16).tofile("targets_x.bin")
    np.asarray(ys, dtype=np.int16).tofile("targets_y.bin")


def row_targets(w, h, cx, cy, nprobe, exclude_edge_columns=False):
    xs = [
        x for x in range(w)
        if x != cx and (not exclude_edge_columns or (x != 0 and x != w - 1))
    ]
    if not xs:
        raise RuntimeError("row_targets has no valid targets")
    reps = (nprobe + len(xs) - 1) // len(xs)
    xs = (xs * reps)[:nprobe]
    ys = [cy] * nprobe
    return list(zip(xs, ys))


def column_targets(w, h, cx, cy, nprobe, exclude_edge_columns=False):
    if exclude_edge_columns and (cx == 0 or cx == w - 1):
        raise RuntimeError("column_targets invalid because center column is excluded")
    ys = [y for y in range(h) if y != cy]
    if not ys:
        raise RuntimeError("column_targets has no valid targets")
    reps = (nprobe + len(ys) - 1) // len(ys)
    ys = (ys * reps)[:nprobe]
    xs = [cx] * nprobe
    return list(zip(xs, ys))


def full_targets(w, h, cx, cy, exclude_edge_columns=False):
    x_start = 1 if exclude_edge_columns else 0
    x_stop = w - 1 if exclude_edge_columns else w
    pts = []
    for y in range(h):
        for x in range(x_start, x_stop):
            if x == cx and y == cy:
                continue
            pts.append((x, y))
    return pts


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield i // n, seq[i:i + n]


def classify_direction(dx, dy):
    if dy == 0:
        return "horizontal"
    if dx == 0:
        return "vertical"
    if abs(dx) == abs(dy):
        return "diagonal"
    return "other"


def merge_csvs(csv_files, out_csv):
    dfs = [pd.read_csv(path) for path in csv_files]
    if not dfs:
        raise RuntimeError("no CSV files to merge")
    all_df = pd.concat(dfs, ignore_index=True)
    all_df.to_csv(out_csv, index=False)
    return len(all_df)


def validate_merged_csv(path):
    df = pd.read_csv(path)
    return {
        "rows": len(df),
        "matched_reply_all": bool((df["matched_reply"] == 1).all()) if "matched_reply" in df.columns else None,
        "done_flag_all": bool((df["done_flag"] == 1).all()) if "done_flag" in df.columns else None,
        "padding_rows": int((df["is_padding"] == 1).sum()) if "is_padding" in df.columns else None,
        "real_rows": int((df["is_padding"] == 0).sum()) if "is_padding" in df.columns else None,
    }


def make_wse_job_name(args, run_timestamp, batch_id):
    base = args.wse_job if args.wse_job else "latency-test-run"
    return f"{base}-{run_timestamp}-b{batch_id:06d}"


def find_symbol_file(out_dir, job_name, region, symbol):
    out_dir = Path(out_dir)

    exact = out_dir / f"{job_name}_{region}_{symbol}.bin"
    if exact.exists():
        return exact

    matches = sorted(out_dir.glob(f"{job_name}_{region}_{symbol}.bin"))
    if matches:
        return matches[-1]

    matches = sorted(out_dir.rglob(f"{job_name}_{region}_{symbol}.bin"))
    if matches:
        return matches[-1]

    matches = sorted(out_dir.glob(f"*_{symbol}.bin"))
    if matches:
        return matches[-1]

    matches = sorted(out_dir.rglob(f"*_{symbol}.bin"))
    if matches:
        return matches[-1]

    return None


def read_symbol_value(out_dir, job_name, region, symbol):
    p = find_symbol_file(out_dir, job_name, region, symbol)
    if p is None or not p.exists():
        return None
    b = p.read_bytes()
    if len(b) == 0:
        return None
    if len(b) == 1:
        return int.from_bytes(b[:1], "little", signed=True)
    return int.from_bytes(b[:2], "little", signed=True)


def fetch_symbol(job_name, mapfile, symbol, out_dir, server, logger, region="main_compute"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"fetch_{symbol.replace('.', '_')}.zip"

    if zip_path.exists():
        logger.log(f"removing stale zip {zip_path}")
        zip_path.unlink()

    abs_zip_path = zip_path.resolve()
    logger.log(f"fetch_symbol symbol={symbol}")
    logger.log(f"fetch_symbol out_dir={out_dir.resolve()}")
    logger.log(f"fetch_symbol zip_path={abs_zip_path}")

    cmd = [
        "csclient", "job",
        "-bn", job_name,
        "-r", region,
        #"pause",
        f"fetch=symbol={symbol} savepath={abs_zip_path} map={mapfile}",
    ]

    rc, output = run_logged(cmd, logger, env=csenv(server), check=False)

    logger.log(f"fetch_symbol rc={rc}")
    if output:
        logger.log(f"fetch_symbol output begin for {symbol}")
        for line in output.splitlines():
            logger.log(f"fetch_symbol stdout {line}")
        logger.log(f"fetch_symbol output end for {symbol}")

    if rc != 0:
        raise RuntimeError(f"fetch command failed for {symbol} with rc={rc}")

    if not zip_path.exists():
        logger.log(f"fetch_symbol zip was not created for {symbol}")
        logger.log(f"contents of {out_dir.resolve()}:")
        for p in sorted(out_dir.glob("*")):
            try:
                size = p.stat().st_size
            except Exception:
                size = "unknown"
            logger.log(f"  {p.name} size={size}")
        raise RuntimeError(
            f"fetch for {symbol} did not produce zip file at {abs_zip_path}"
        )

    try:
        zip_size = zip_path.stat().st_size
    except Exception:
        zip_size = "unknown"

    logger.log(f"fetch_symbol zip exists for {symbol}, size={zip_size}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        logger.log(f"fetch_symbol zip members for {symbol}: {members}")
        zf.extractall(out_dir)

    zip_path.unlink(missing_ok=True)
    logger.log(f"fetch_symbol completed for {symbol}")


def fetch_symbols(job_name, mapfile, symbols, out_dir, server, logger, region="main_compute"):
    for symbol in symbols:
        logger.log(f"Fetching {symbol} from WSE")
        fetch_symbol(job_name, mapfile, symbol, out_dir, server, logger, region=region)


def maybe_sleep_before_fetch(args, logger):
    if args.sleep_before_fetch_s and args.sleep_before_fetch_s > 0:
        logger.log(f"sleeping {args.sleep_before_fetch_s} seconds before first fetch")
        time.sleep(args.sleep_before_fetch_s)


def fetch_done_once(job_name, mapfile, out_dir, server, logger, region="main_compute"):
    logger.log("fetching done/count once")
    fetch_symbols(job_name, mapfile, DONE_POLL_SYMBOLS, out_dir, server, logger, region=region)

    done_val = read_symbol_value(out_dir, job_name, region, "center.done")
    count_val = read_symbol_value(out_dir, job_name, region, "center.count")

    logger.log(f"single fetch center.done={done_val} center.count={count_val}")
    return done_val, count_val


def wait_for_done(
    job_name,
    mapfile,
    out_dir,
    server,
    logger,
    timeout_s=300,
    poll_s=2,
    region="main_compute",
    initial_sleep_s=0,
):
    start = time.time()
    last_done = None
    last_count = None

    if initial_sleep_s and initial_sleep_s > 0:
        logger.log(f"wait_for_done initial sleep {initial_sleep_s} seconds")
        time.sleep(initial_sleep_s)

    while time.time() - start < timeout_s:
        fetch_symbols(job_name, mapfile, DONE_POLL_SYMBOLS, out_dir, server, logger, region=region)

        done_val = read_symbol_value(out_dir, job_name, region, "center.done")
        count_val = read_symbol_value(out_dir, job_name, region, "center.count")
        last_done = done_val
        last_count = count_val

        logger.log(f"poll center.done={done_val} center.count={count_val}")

        if done_val == 1:
            return True, done_val, count_val

        time.sleep(poll_s)

    return False, last_done, last_count


def get_diag_values(out_dir, job_name, region="main_compute"):
    return {
        "done": read_symbol_value(out_dir, job_name, region, "center.done"),
        "count": read_symbol_value(out_dir, job_name, region, "center.count"),
        "send_count": read_symbol_value(out_dir, job_name, region, "center.send_count"),
        "last_sent_x": read_symbol_value(out_dir, job_name, region, "center.last_sent_x"),
        "last_sent_y": read_symbol_value(out_dir, job_name, region, "center.last_sent_y"),
    }


def enrich_batch_csv(
    batch_csv_path,
    out_csv_path,
    batch_id,
    batch_points,
    written_points,
    cx,
    cy,
    global_start_index,
):
    df = pd.read_csv(batch_csv_path)

    real_count = len(batch_points)
    written_count = len(written_points)

    if len(df) == 0:
        raise RuntimeError(f"empty CSV for batch {batch_id}")

    if len(df) != written_count:
        raise RuntimeError(
            f"CSV row count mismatch for batch {batch_id}: "
            f"csv_rows={len(df)} written_count={written_count}"
        )

    is_padding = np.array(
        [1 if i >= real_count else 0 for i in range(written_count)],
        dtype=np.int8,
    )

    real_probe_index = np.array(
        [global_start_index + i if i < real_count else -1 for i in range(written_count)],
        dtype=np.int64,
    )

    df["batch_id"] = batch_id
    df["batch_real_count"] = real_count
    df["batch_written_count"] = written_count
    df["is_padding"] = is_padding
    df["is_real"] = 1 - is_padding
    df["real_probe_index"] = real_probe_index

    df["dx"] = df["target_x"] - cx
    df["dy"] = df["target_y"] - cy
    df["manhattan_dist"] = df["dx"].abs() + df["dy"].abs()
    df["chebyshev_dist"] = df[["dx", "dy"]].abs().max(axis=1)
    df["direction_class"] = [
        classify_direction(dx, dy) for dx, dy in zip(df["dx"], df["dy"])
    ]

    df.to_csv(out_csv_path, index=False)
    return {
        "rows": len(df),
        "real_count": real_count,
        "written_count": written_count,
    }


def save_snapshot(src_dir, dst_dir):
    src = Path(src_dir)
    dst = Path(dst_dir)
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def write_batch_summary(path, rows):
    fieldnames = [
        "batch_id",
        "status",
        "reason",
        "job_name",
        "real_targets",
        "written_targets",
        "raw_csv",
        "enriched_csv",
        "log_path",
        "timed_out",
        "done",
        "count",
        "send_count",
        "last_sent_x",
        "last_sent_y",
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def run_wse_batch(batch_id, make_vars, args, run_timestamp, run_dir, main_logger):
    region = "main_compute"
    batch_job_name = make_wse_job_name(args, run_timestamp, batch_id)
    batch_log_path = Path(run_dir) / "logs" / f"batch_{batch_id:06d}.log"
    batch_logger = TeeLogger(batch_log_path)

    batch_logger.log(f"batch {batch_id} WSE_JOB={batch_job_name}")
    batch_logger.log(f"batch {batch_id} mapfile={args.mapfile}")

    clean_dir("out_hw")

    wse_vars = list(make_vars)
    wse_vars.append(f"WSE_JOB={batch_job_name}")
    if args.wse_server:
        wse_vars.append(f"WSE_SERVER={args.wse_server}")

    diag = {
        "job_name": batch_job_name,
        "log_path": str(batch_log_path),
        "timed_out": 0,
        "done": None,
        "count": None,
        "send_count": None,
        "last_sent_x": None,
        "last_sent_y": None,
    }

    try:
        run_logged(["make", "wse-run"] + wse_vars, batch_logger, check=True)

        maybe_sleep_before_fetch(args, batch_logger)

        if args.skip_done_poll:
            batch_logger.log("skipping wait_for_done due to --skip-done-poll")

            done_val = None
            count_val = None

            if args.fetch_done_only_first:
                done_val, count_val = fetch_done_once(
                    job_name=batch_job_name,
                    mapfile=args.mapfile,
                    out_dir="out_hw",
                    server=args.wse_server,
                    logger=batch_logger,
                    region=region,
                )
                diag["done"] = done_val
                diag["count"] = count_val

                if done_val != 1:
                    diag["timed_out"] = 1
                    batch_logger.log(
                        f"job not done before full fetch, done={done_val} count={count_val}"
                    )
                    try:
                        fetch_symbols(
                            batch_job_name,
                            args.mapfile,
                            DEBUG_SYMBOLS,
                            "out_hw",
                            args.wse_server,
                            batch_logger,
                            region=region,
                        )
                    except Exception as e:
                        batch_logger.log(f"debug fetch failed: {e}")

                    diag.update(get_diag_values("out_hw", batch_job_name, region=region))
                    batch_logger.log(
                        f"diag after incomplete run done={diag['done']} count={diag['count']} "
                        f"send_count={diag['send_count']} "
                        f"last_sent_x={diag['last_sent_x']} last_sent_y={diag['last_sent_y']}"
                    )

                    save_snapshot(
                        "out_hw",
                        Path(run_dir) / "diag" / f"batch_{batch_id:06d}" / "out_hw",
                    )

                    raise RuntimeError(
                        f"job not done before full fetch, done={diag['done']} count={diag['count']}"
                    )

            fetch_symbols(
                batch_job_name,
                args.mapfile,
                FULL_FETCH_SYMBOLS,
                "out_hw",
                args.wse_server,
                batch_logger,
                region=region,
            )

        else:
            ok, done_val, count_val = wait_for_done(
                job_name=batch_job_name,
                mapfile=args.mapfile,
                out_dir="out_hw",
                server=args.wse_server,
                logger=batch_logger,
                timeout_s=args.done_timeout_s,
                poll_s=args.done_poll_s,
                region=region,
                initial_sleep_s=args.done_initial_sleep_s,
            )

            diag["done"] = done_val
            diag["count"] = count_val

            if not ok:
                diag["timed_out"] = 1
                batch_logger.log("timeout waiting for center.done==1, fetching debug symbols")
                try:
                    fetch_symbols(
                        batch_job_name,
                        args.mapfile,
                        DEBUG_SYMBOLS,
                        "out_hw",
                        args.wse_server,
                        batch_logger,
                        region=region,
                    )
                except Exception as e:
                    batch_logger.log(f"debug fetch failed: {e}")

                diag.update(get_diag_values("out_hw", batch_job_name, region=region))
                batch_logger.log(
                    f"diag after timeout done={diag['done']} count={diag['count']} "
                    f"send_count={diag['send_count']} "
                    f"last_sent_x={diag['last_sent_x']} last_sent_y={diag['last_sent_y']}"
                )

                save_snapshot(
                    "out_hw",
                    Path(run_dir) / "diag" / f"batch_{batch_id:06d}" / "out_hw",
                )

                raise RuntimeError(
                    f"timeout waiting for done, last done={diag['done']} count={diag['count']}"
                )

            fetch_symbols(
                batch_job_name,
                args.mapfile,
                FULL_FETCH_SYMBOLS,
                "out_hw",
                args.wse_server,
                batch_logger,
                region=region,
            )

        diag.update(get_diag_values("out_hw", batch_job_name, region=region))

        save_snapshot(
            "out_hw",
            Path(run_dir) / "diag" / f"batch_{batch_id:06d}" / "out_hw",
        )

        run_logged(
            ["python3", "run_scan.py", "--csv", "rtt.csv", "--hwdir", "out_hw"],
            batch_logger,
            check=True,
        )

        return diag

    finally:
        if args.cancel_after:
            try:
                run_logged(
                    ["csclient", "bundle", "-bn", batch_job_name, "--cancel"],
                    batch_logger,
                    env=csenv(args.wse_server),
                    check=False,
                )
            except Exception:
                pass

        batch_logger.close()
        main_logger.log(f"batch {batch_id} log written to {batch_log_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--h", type=int, required=True)
    ap.add_argument("--cx", type=int, required=True)
    ap.add_argument("--cy", type=int, required=True)
    ap.add_argument("--nprobe", type=int, required=True)
    ap.add_argument("--nwarmup", type=int, default=16)
    ap.add_argument("--mode", choices=["row", "column", "full"], default="full")
    ap.add_argument("--sim-cycles", type=int, default=50000)
    ap.add_argument("--exclude-edge-columns", action="store_true")
    ap.add_argument("--outdir", default="batches")
    ap.add_argument("--merged-csv", default="all_rtt.csv")
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--exec-mode", choices=["sim", "wse"], default="sim")
    ap.add_argument("--wse-job", default=None)
    ap.add_argument("--wse-server", default="http://localhost:8080")
    ap.add_argument("--cancel-after", action="store_true")
    ap.add_argument("--done-timeout-s", type=int, default=180)
    ap.add_argument("--done-poll-s", type=int, default=2)
    ap.add_argument("--done-initial-sleep-s", type=float, default=0.0)
    ap.add_argument("--sleep-before-fetch-s", type=float, default=0.0)
    ap.add_argument("--skip-done-poll", action="store_true")
    ap.add_argument("--fetch-done-only-first", action="store_true")
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument("--run-root", default="runs")
    ap.add_argument("--mapfile", default="latency-test.map")
    args = ap.parse_args()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.run_root) / run_timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    main_logger = TeeLogger(run_dir / "scan_workflow.log")
    main_logger.log(f"run_timestamp={run_timestamp}")
    main_logger.log(f"args={vars(args)}")

    outdir = Path(args.outdir)

    if not args.no_clean:
        main_logger.log("running make clean")
        run_logged(["make", "clean"], main_logger, check=True)
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
    else:
        outdir.mkdir(parents=True, exist_ok=True)
        main_logger.log("skipping make clean due to --no-clean")

    if args.mode == "row":
        batches = [(
            0,
            row_targets(
                args.w, args.h, args.cx, args.cy, args.nprobe, args.exclude_edge_columns
            ),
        )]
    elif args.mode == "column":
        batches = [(
            0,
            column_targets(
                args.w, args.h, args.cx, args.cy, args.nprobe, args.exclude_edge_columns
            ),
        )]
    else:
        pts = full_targets(args.w, args.h, args.cx, args.cy, args.exclude_edge_columns)
        total = len(pts)
        nbatches = math.ceil(total / args.nprobe)
        main_logger.log(f"total valid targets={total}")
        main_logger.log(f"batch size={args.nprobe}")
        main_logger.log(f"number of batches={nbatches}")
        batches = list(chunked(pts, args.nprobe))

    csv_files = []
    batch_summary_rows = []
    global_real_index = 0

    for batch_id, batch in batches:
        main_logger.log(f"starting batch {batch_id}")

        xs = [p[0] for p in batch]
        ys = [p[1] for p in batch]
        real_count = len(xs)

        if real_count == 0:
            msg = f"batch {batch_id} is empty"
            main_logger.log(msg)
            row = {
                "batch_id": batch_id,
                "status": "failed",
                "reason": msg,
                "job_name": "",
                "real_targets": 0,
                "written_targets": 0,
                "raw_csv": "",
                "enriched_csv": "",
                "log_path": "",
                "timed_out": 0,
                "done": "",
                "count": "",
                "send_count": "",
                "last_sent_x": "",
                "last_sent_y": "",
            }
            batch_summary_rows.append(row)
            if args.fail_fast:
                write_batch_summary(Path(run_dir) / "batch_summary.csv", batch_summary_rows)
                main_logger.close()
                raise RuntimeError(msg)
            continue

        written_points = list(batch)
        while len(xs) < args.nprobe:
            xs.append(xs[-1])
            ys.append(ys[-1])
            written_points.append((xs[-1], ys[-1]))

        write_targets(xs, ys)
        main_logger.log(f"wrote targets for batch {batch_id}, real={real_count}, written={len(xs)}")

        make_vars = [
            f"W={args.w}",
            f"H={args.h}",
            f"CX={args.cx}",
            f"CY={args.cy}",
            f"NPROBE={args.nprobe}",
            f"NWARMUP={args.nwarmup}",
            f"SIM_CYCLES={args.sim_cycles}",
        ]

        raw_batch_csv = outdir / f"batch_{batch_id:06d}_raw.csv"
        enriched_batch_csv = outdir / f"batch_{batch_id:06d}.csv"

        summary = {
            "batch_id": batch_id,
            "status": "failed",
            "reason": "",
            "job_name": "",
            "real_targets": real_count,
            "written_targets": len(xs),
            "raw_csv": str(raw_batch_csv),
            "enriched_csv": str(enriched_batch_csv),
            "log_path": "",
            "timed_out": 0,
            "done": "",
            "count": "",
            "send_count": "",
            "last_sent_x": "",
            "last_sent_y": "",
        }

        try:
            if args.exec_mode == "sim":
                run_logged(["make", "sim"] + make_vars, main_logger, check=True)
                run_logged(["make", "csv"] + make_vars, main_logger, check=True)
            else:
                diag = run_wse_batch(batch_id, make_vars, args, run_timestamp, run_dir, main_logger)
                summary.update(diag)

            if not Path("rtt.csv").exists():
                raise RuntimeError("rtt.csv was not produced")

            shutil.copyfile("rtt.csv", raw_batch_csv)

            stats = enrich_batch_csv(
                batch_csv_path=raw_batch_csv,
                out_csv_path=enriched_batch_csv,
                batch_id=batch_id,
                batch_points=batch,
                written_points=written_points,
                cx=args.cx,
                cy=args.cy,
                global_start_index=global_real_index,
            )

            summary["status"] = "ok"
            summary["reason"] = ""
            csv_files.append(str(enriched_batch_csv))
            global_real_index += real_count

            main_logger.log(
                f"batch {batch_id} complete, rows={stats['rows']} real={stats['real_count']} written={stats['written_count']}"
            )

        except Exception as e:
            summary["status"] = "failed"
            summary["reason"] = str(e)
            main_logger.log(f"batch {batch_id} failed: {e}")

            if Path("rtt.csv").exists():
                try:
                    shutil.copyfile("rtt.csv", raw_batch_csv)
                except Exception:
                    pass

            batch_summary_rows.append(summary)

            if args.fail_fast:
                write_batch_summary(Path(run_dir) / "batch_summary.csv", batch_summary_rows)
                main_logger.close()
                raise

            continue

        batch_summary_rows.append(summary)

    write_batch_summary(Path(run_dir) / "batch_summary.csv", batch_summary_rows)

    ok_batches = [r for r in batch_summary_rows if r["status"] == "ok"]
    failed_batches = [r for r in batch_summary_rows if r["status"] != "ok"]

    main_logger.log(f"successful batches={len(ok_batches)}")
    main_logger.log(f"failed batches={len(failed_batches)}")

    if csv_files:
        merged_rows = merge_csvs(csv_files, args.merged_csv)
        main_logger.log(f"wrote merged CSV {args.merged_csv}, rows={merged_rows}")
        try:
            summary = validate_merged_csv(args.merged_csv)
            for k, v in summary.items():
                main_logger.log(f"merge summary {k}={v}")
        except Exception as e:
            main_logger.log(f"merged CSV validation failed: {e}")
    else:
        main_logger.log("no successful batch CSVs found, merged CSV not written")

    main_logger.log(f"run artifacts saved under {run_dir}")
    main_logger.close()


if __name__ == "__main__":
    main()
