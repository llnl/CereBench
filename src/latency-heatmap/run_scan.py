import argparse
import csv
import subprocess
from pathlib import Path


def run_cmd(cmd):
    return subprocess.check_output(cmd, text=True)


def miget_text(image, map_file, symbol):
    cmd = ["miget", f"image={image}", f"map={map_file}", f"symbol={symbol}", "text"]
    return run_cmd(cmd)


def parse_hex_words(text):
    vals = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for tok in line.split():
            vals.append(int(tok, 16))
    return vals


def read_1d_xp_from_core(image, map_file, symbol):
    txt = miget_text(image, map_file, symbol)
    vals = parse_hex_words(txt)
    if not vals:
        raise RuntimeError(f"no data parsed for {symbol}, raw text was:\n{txt}")
    return vals


def read_u16_file(path):
    data = Path(path).read_bytes()
    if len(data) % 2 != 0:
        raise RuntimeError(f"{path} size is not a multiple of 2 bytes")
    vals = []
    for i in range(0, len(data), 2):
        vals.append(int.from_bytes(data[i:i + 2], "little", signed=False))
    return vals


def find_hw_file(hwdir, symbol):
    hwdir = Path(hwdir)

    candidates = sorted(set(hwdir.rglob(f"*_{symbol}.bin")))
    if not candidates:
        candidates = sorted(set(hwdir.rglob(f"{symbol}.bin")))

    if not candidates:
        raise RuntimeError(f"could not find fetched file for symbol {symbol} in {hwdir}")

    return candidates[-1]


def read_1d_xp_from_hwdir(hwdir, symbol):
    path = find_hw_file(hwdir, symbol)
    return read_u16_file(path)


def u16_delta(stop, start):
    return (stop - start) & 0xFFFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core")
    ap.add_argument("--hwdir")
    ap.add_argument("--map")
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    using_core = args.core is not None
    using_hwdir = args.hwdir is not None

    if using_core == using_hwdir:
        raise RuntimeError("provide exactly one of --core or --hwdir")

    if using_core and not args.map:
        raise RuntimeError("--map is required when using --core")

    if using_core:
        read_1d = lambda symbol: read_1d_xp_from_core(args.core, args.map, symbol)
    else:
        read_1d = lambda symbol: read_1d_xp_from_hwdir(args.hwdir, symbol)

    target_x = read_1d("center.target_x")
    target_y = read_1d("center.target_y")
    reply_x = read_1d("center.reply_x")
    reply_y = read_1d("center.reply_y")
    reply_seq = read_1d("center.reply_seq")
    count = read_1d("center.count")[0]
    done = read_1d("center.done")[0]
    t_start = read_1d("center.t_start")
    t_stop = read_1d("center.t_stop")

    n = min(
        count,
        len(target_x),
        len(target_y),
        len(reply_x),
        len(reply_y),
        len(reply_seq),
        len(t_start),
        len(t_stop),
    )

    rows = []
    for i in range(n):
        start_u16 = t_start[i] & 0xFFFF
        stop_u16 = t_stop[i] & 0xFFFF
        rtt = u16_delta(stop_u16, start_u16)

        rows.append({
            "probe_index": i,
            "target_x": target_x[i],
            "target_y": target_y[i],
            "reply_x": reply_x[i],
            "reply_y": reply_y[i],
            "reply_seq": reply_seq[i],
            "start_u16": start_u16,
            "stop_u16": stop_u16,
            "rtt_cycles": rtt,
            "matched_reply": int(reply_seq[i] == i),
            "done_flag": done,
            "count": count,
        })

    out = Path(args.csv)
    fieldnames = [
        "probe_index",
        "target_x",
        "target_y",
        "reply_x",
        "reply_y",
        "reply_seq",
        "start_u16",
        "stop_u16",
        "rtt_cycles",
        "matched_reply",
        "done_flag",
        "count",
    ]

    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {out}")
    print(f"done={done} count={count} rows={len(rows)}")


if __name__ == "__main__":
    main()
