import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter


# poster-friendly defaults
plt.style.use("seaborn-v0_8-whitegrid")
plt.rcParams.update({
    "font.size": 20,
    "axes.titlesize": 24,
    "axes.labelsize": 22,
    "xtick.labelsize": 18,
    "ytick.labelsize": 18,
    "legend.fontsize": 18,
    "figure.titlesize": 26,
})


def load_and_filter(csv_path):
    df = pd.read_csv(csv_path)

    required = ["matched_reply", "done_flag", "target_x", "target_y", "rtt_cycles"]
    for col in required:
        if col not in df.columns:
            raise RuntimeError(f"missing required column: {col}")

    good = df[(df["matched_reply"] == 1) & (df["done_flag"] == 1)].copy()

    if "is_padding" in good.columns:
        good = good[good["is_padding"] == 0].copy()

    return df, good


def determine_latency_label(unit_name, startup_adjusted=False):
    if unit_name == "cycles":
        label = "Round-trip latency (cycles)"
    elif unit_name == "ns":
        label = "Round-trip latency (ns)"
    elif unit_name == "us":
        label = "Round-trip latency (us)"
    else:
        label = f"Round-trip latency ({unit_name})"

    if startup_adjusted:
        label = label.replace(")", ", startup-adjusted)")
    return label


def convert_units(df, source_col, output_unit="cycles", freq_ghz=0.85, cycle_time_ns=None):
    if output_unit == "cycles":
        out_col = "latency_plot_units"
        df[out_col] = df[source_col].astype(float)
        return df, out_col, "cycles", None

    if cycle_time_ns is None:
        if freq_ghz is None or freq_ghz <= 0:
            raise RuntimeError("time conversion requested, but frequency or cycle time is invalid")
        cycle_time_ns = 1.0 / freq_ghz

    ns_values = df[source_col].astype(float) * cycle_time_ns

    out_col = "latency_plot_units"
    if output_unit == "ns":
        df[out_col] = ns_values
        return df, out_col, "ns", cycle_time_ns

    if output_unit == "us":
        df[out_col] = ns_values / 1000.0
        return df, out_col, "us", cycle_time_ns

    raise RuntimeError(f"unsupported output unit: {output_unit}")


def estimate_startup_value(good, latency_col, mode="none", startup_value=None):
    if mode == "none":
        return 0.0

    if mode == "fixed":
        if startup_value is None:
            raise RuntimeError("--startup-mode fixed requires --startup-value")
        return float(startup_value)

    vals = good[latency_col].to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]

    if len(vals) == 0:
        raise RuntimeError("cannot estimate startup from empty latency data")

    if mode == "min":
        return float(np.min(vals))

    if mode == "median":
        return float(np.median(vals))

    if mode == "zero-manhattan-median":
        if "manhattan_dist" not in good.columns:
            raise RuntimeError("startup-mode zero-manhattan-median requires manhattan_dist column")
        part = good[good["manhattan_dist"] == 0]
        if len(part) == 0:
            raise RuntimeError("no rows with manhattan_dist == 0 found")
        return float(np.median(part[latency_col]))

    if mode == "zero-chebyshev-median":
        if "chebyshev_dist" not in good.columns:
            raise RuntimeError("startup-mode zero-chebyshev-median requires chebyshev_dist column")
        part = good[good["chebyshev_dist"] == 0]
        if len(part) == 0:
            raise RuntimeError("no rows with chebyshev_dist == 0 found")
        return float(np.median(part[latency_col]))

    raise RuntimeError(f"unknown startup mode: {mode}")


def apply_startup_subtraction(good, latency_col, startup_mode="none", startup_value=None):
    baseline = estimate_startup_value(good, latency_col, startup_mode, startup_value)
    adjusted_col = f"{latency_col}_startup_adjusted"
    good[adjusted_col] = good[latency_col].astype(float) - baseline
    return good, adjusted_col, baseline


def make_pivot(good, value_col):
    pivot = good.pivot_table(
        index="target_y",
        columns="target_x",
        values=value_col,
        aggfunc="median",
    ).sort_index(axis=0).sort_index(axis=1)
    return pivot


def save_heatmap_from_pivot(pivot, out_png, title, cbar_label, cmap="viridis", vmin=None, vmax=None):
    data = pivot.to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(16, 13), constrained_layout=True)
    im = ax.imshow(
        data,
        origin="lower",
        aspect="equal",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )

    cbar = fig.colorbar(im, ax=ax, pad=0.02, fraction=0.046)
    cbar.set_label(cbar_label, fontsize=22)
    cbar.ax.tick_params(labelsize=18)

    ax.set_xlabel("Target x-coordinate", labelpad=10)
    ax.set_ylabel("Target y-coordinate", labelpad=10)
    ax.set_title(title, pad=15, fontweight="bold")

    if data.shape[1] > 0:
        x_ticks = np.arange(0, data.shape[1], max(1, data.shape[1] // 10))
        ax.set_xticks(x_ticks)
    if data.shape[0] > 0:
        y_ticks = np.arange(0, data.shape[0], max(1, data.shape[0] // 10))
        ax.set_yticks(y_ticks)

    ax.grid(False)

    plt.savefig(out_png, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_png}")


def save_heatmap(good, out_png, value_col, title, cbar_label):
    pivot = make_pivot(good, value_col)
    data = pivot.to_numpy(dtype=float)
    finite = data[np.isfinite(data)]

    vmin = np.nanpercentile(finite, 5) if len(finite) else None
    vmax = np.nanpercentile(finite, 95) if len(finite) else None

    save_heatmap_from_pivot(
        pivot,
        out_png,
        title=title,
        cbar_label=cbar_label,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
    )


def save_step_plot(good, out_png, latency_col, latency_label, dist_col, title):
    if dist_col not in good.columns:
        print(f"skipping {out_png}, missing column: {dist_col}")
        return

    summary = (
        good.groupby(dist_col)[latency_col]
        .median()
        .reset_index()
        .sort_values(dist_col)
    )

    if len(summary) == 0:
        print(f"skipping {out_png}, no summary data")
        return

    fig, ax = plt.subplots(figsize=(14, 8), constrained_layout=True)
    ax.step(summary[dist_col], summary[latency_col], where="mid", linewidth=3.0, color="tab:blue")
    ax.scatter(summary[dist_col], summary[latency_col], s=60, color="tab:blue", zorder=3)

    ax.set_xlabel(dist_col.replace("_", " ").title())
    ax.set_ylabel(latency_label)
    ax.set_title(title, fontweight="bold", pad=12)
    ax.grid(True, alpha=0.3)

    plt.savefig(out_png, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_png}")


def save_direction_step_plot(good, out_png, latency_col, latency_label, dist_col="manhattan_dist"):
    if dist_col not in good.columns or "direction_class" not in good.columns:
        print(f"skipping {out_png}, missing direction_class or {dist_col}")
        return

    fig, ax = plt.subplots(figsize=(14, 8), constrained_layout=True)

    colors = {
        "horizontal": "tab:blue",
        "vertical": "tab:orange",
        "diagonal": "tab:green",
        "other": "tab:red",
    }

    found_any = False
    for label in ["horizontal", "vertical", "diagonal", "other"]:
        part = good[good["direction_class"] == label]
        if len(part) == 0:
            continue

        summary = (
            part.groupby(dist_col)[latency_col]
            .median()
            .reset_index()
            .sort_values(dist_col)
        )
        if len(summary) == 0:
            continue

        ax.step(
            summary[dist_col],
            summary[latency_col],
            where="mid",
            label=label,
            linewidth=3.0,
            color=colors.get(label, None),
        )
        ax.scatter(summary[dist_col], summary[latency_col], s=50, color=colors.get(label, None))
        found_any = True

    if not found_any:
        print(f"no direction-class data available for {out_png}")
        plt.close()
        return

    ax.set_xlabel(dist_col.replace("_", " ").title())
    ax.set_ylabel(latency_label)
    ax.set_title("Median round-trip latency versus Manhattan distance by direction class", fontweight="bold", pad=12)
    ax.grid(True, alpha=0.3)
    ax.legend(frameon=True)

    plt.savefig(out_png, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_png}")


def save_axis_line_plots(good, latency_col, latency_label, cx, cy, out_prefix):
    horizontal = good[good["target_y"] == cy].copy().sort_values("target_x")
    vertical = good[good["target_x"] == cx].copy().sort_values("target_y")

    main_diag = good[(good["target_x"] - cx) == (good["target_y"] - cy)].copy()
    anti_diag = good[(good["target_x"] - cx) == -(good["target_y"] - cy)].copy()

    if len(horizontal) > 0:
        fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
        ax.plot(horizontal["target_x"], horizontal[latency_col], marker="o", linewidth=3.0)
        ax.set_xlabel("Target x-coordinate")
        ax.set_ylabel(latency_label)
        ax.set_title(f"Median round-trip latency along row y = {cy}", fontweight="bold", pad=12)
        ax.grid(True, alpha=0.3)

        out_png = f"{out_prefix}_horizontal_line.png"
        plt.savefig(out_png, dpi=250, bbox_inches="tight")
        plt.close()
        print(f"wrote {out_png}")

    if len(vertical) > 0:
        fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
        ax.plot(vertical["target_y"], vertical[latency_col], marker="o", linewidth=3.0)
        ax.set_xlabel("Target y-coordinate")
        ax.set_ylabel(latency_label)
        ax.set_title(f"Median round-trip latency along column x = {cx}", fontweight="bold", pad=12)
        ax.grid(True, alpha=0.3)

        out_png = f"{out_prefix}_vertical_line.png"
        plt.savefig(out_png, dpi=250, bbox_inches="tight")
        plt.close()
        print(f"wrote {out_png}")

    if len(main_diag) > 0:
        main_diag["diag_offset"] = main_diag["target_x"] - cx
        main_diag = main_diag.sort_values("diag_offset")

        fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
        ax.plot(main_diag["diag_offset"], main_diag[latency_col], marker="o", linewidth=3.0)
        ax.set_xlabel(f"Main diagonal offset from ({cx}, {cy})")
        ax.set_ylabel(latency_label)
        ax.set_title(f"Median round-trip latency along main diagonal through ({cx}, {cy})", fontweight="bold", pad=12)
        ax.grid(True, alpha=0.3)

        out_png = f"{out_prefix}_diagonal_main_line.png"
        plt.savefig(out_png, dpi=250, bbox_inches="tight")
        plt.close()
        print(f"wrote {out_png}")

    if len(anti_diag) > 0:
        anti_diag["diag_offset"] = anti_diag["target_x"] - cx
        anti_diag = anti_diag.sort_values("diag_offset")

        fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
        ax.plot(anti_diag["diag_offset"], anti_diag[latency_col], marker="o", linewidth=3.0)
        ax.set_xlabel(f"Anti-diagonal offset from ({cx}, {cy})")
        ax.set_ylabel(latency_label)
        ax.set_title(f"Median round-trip latency along anti-diagonal through ({cx}, {cy})", fontweight="bold", pad=12)
        ax.grid(True, alpha=0.3)

        out_png = f"{out_prefix}_diagonal_anti_line.png"
        plt.savefig(out_png, dpi=250, bbox_inches="tight")
        plt.close()
        print(f"wrote {out_png}")


def save_histogram(good, latency_col, latency_label, out_png, bins=60, title=None):
    vals = good[latency_col].to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]

    if len(vals) == 0:
        print(f"skipping {out_png}, no finite values")
        return

    fig, ax = plt.subplots(figsize=(14, 8), constrained_layout=True)
    ax.hist(vals, bins=bins, color="tab:blue", alpha=0.85, edgecolor="black", linewidth=0.5)

    ax.set_xlabel(latency_label)
    ax.set_ylabel("Count")
    ax.set_title(title or "Distribution of round-trip latency measurements", fontweight="bold", pad=12)
    ax.grid(True, axis="y", alpha=0.3)

    plt.savefig(out_png, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_png}")


def save_summary_csv(good, latency_col, out_csv):
    needed = ["manhattan_dist", "direction_class"]
    missing = [c for c in needed if c not in good.columns]
    if missing:
        print(f"skipping {out_csv}, missing columns: {missing}")
        return

    summary = (
        good.groupby(["manhattan_dist", "direction_class"])[latency_col]
        .agg(["count", "min", "median", "max", "mean"])
        .reset_index()
        .sort_values(["direction_class", "manhattan_dist"])
    )
    summary.to_csv(out_csv, index=False)
    print(f"wrote {out_csv}")


def compare_neighbor_jumps(pivot):
    data = pivot.to_numpy(dtype=float)

    h_diff = data[:, 1:] - data[:, :-1]
    v_diff = data[1:, :] - data[:-1, :]

    h_abs = np.abs(h_diff)
    v_abs = np.abs(v_diff)

    print("\nNeighbor jump comparison:")
    print(f"  horizontal mean absolute jump: {np.nanmean(h_abs):.3f}")
    print(f"  vertical   mean absolute jump: {np.nanmean(v_abs):.3f}")
    print(f"  horizontal median absolute jump: {np.nanmedian(h_abs):.3f}")
    print(f"  vertical   median absolute jump: {np.nanmedian(v_abs):.3f}")

    return h_diff, v_diff, h_abs, v_abs


def plot_jump_comparison(h_abs, v_abs, out_png, latency_label):
    h_vals = h_abs.flatten()
    v_vals = v_abs.flatten()

    h_vals = h_vals[np.isfinite(h_vals)]
    v_vals = v_vals[np.isfinite(v_vals)]

    if len(h_vals) == 0 or len(v_vals) == 0:
        print(f"skipping {out_png}, no finite neighbor jump data")
        return

    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)

    ax.boxplot(
        [h_vals, v_vals],
        tick_labels=["Horizontal neighbors", "Vertical neighbors"],
        showfliers=False,
    )

    ax.set_ylabel(f"Absolute difference in {latency_label.lower()}")
    ax.set_title("Comparison of absolute nearest-neighbor latency differences", fontweight="bold", pad=12)
    ax.grid(True, axis="y", alpha=0.3)

    plt.savefig(out_png, dpi=250, bbox_inches="tight")
    plt.close()
    print(f"wrote {out_png}")


def save_difference_maps(pivot, outdir, prefix, latency_label):
    data = pivot.to_numpy(dtype=float)

    dx = np.full_like(data, np.nan)
    dy = np.full_like(data, np.nan)

    dx[:, 1:] = data[:, 1:] - data[:, :-1]
    dy[1:, :] = data[1:, :] - data[:-1, :]

    finite_dx = dx[np.isfinite(dx)]
    finite_dy = dy[np.isfinite(dy)]
    diff_vals = np.concatenate([finite_dx, finite_dy]) if (len(finite_dx) + len(finite_dy)) > 0 else np.array([])
    diff_lim = np.nanpercentile(np.abs(diff_vals), 95) if len(diff_vals) > 0 else None

    dx_pivot = pd.DataFrame(dx, index=pivot.index, columns=pivot.columns)
    dy_pivot = pd.DataFrame(dy, index=pivot.index, columns=pivot.columns)

    save_heatmap_from_pivot(
        dx_pivot,
        os.path.join(outdir, f"{prefix}_horizontal_diff.png"),
        "Horizontal nearest-neighbor latency difference",
        f"Difference in {latency_label.lower()}",
        cmap="coolwarm",
        vmin=-diff_lim if diff_lim is not None else None,
        vmax=diff_lim if diff_lim is not None else None,
    )

    save_heatmap_from_pivot(
        dy_pivot,
        os.path.join(outdir, f"{prefix}_vertical_diff.png"),
        "Vertical nearest-neighbor latency difference",
        f"Difference in {latency_label.lower()}",
        cmap="coolwarm",
        vmin=-diff_lim if diff_lim is not None else None,
        vmax=diff_lim if diff_lim is not None else None,
    )

    gx = np.zeros_like(data)
    gy = np.zeros_like(data)
    gx[:, 1:] = data[:, 1:] - data[:, :-1]
    gy[1:, :] = data[1:, :] - data[:-1, :]
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)

    grad_pivot = pd.DataFrame(grad_mag, index=pivot.index, columns=pivot.columns)
    save_heatmap_from_pivot(
        grad_pivot,
        os.path.join(outdir, f"{prefix}_gradient_magnitude.png"),
        "Spatial gradient magnitude of median round-trip latency",
        f"Gradient magnitude in {latency_label.lower()}",
        cmap="magma",
    )

    filled = np.array(data, copy=True)
    med = np.nanmedian(filled) if np.any(np.isfinite(filled)) else 0.0
    filled[~np.isfinite(filled)] = med

    smooth = gaussian_filter(filled, sigma=2)
    residual = data - smooth

    finite_res = residual[np.isfinite(residual)]
    res_lim = np.nanpercentile(np.abs(finite_res), 95) if len(finite_res) > 0 else None

    residual_pivot = pd.DataFrame(residual, index=pivot.index, columns=pivot.columns)
    save_heatmap_from_pivot(
        residual_pivot,
        os.path.join(outdir, f"{prefix}_residual.png"),
        "Residual latency after subtracting a smooth spatial background",
        f"Residual in {latency_label.lower()}",
        cmap="coolwarm",
        vmin=-res_lim if res_lim is not None else None,
        vmax=res_lim if res_lim is not None else None,
    )

    return dx, dy, grad_mag, residual


def save_direction_scores(pivot, outdir, prefix):
    data = pivot.to_numpy(dtype=float)

    h_diff = data[:, 1:] - data[:, :-1]
    v_diff = data[1:, :] - data[:-1, :]

    h_abs = np.abs(h_diff)
    v_abs = np.abs(v_diff)

    row_score = np.nanmean(v_abs, axis=1)
    col_score = np.nanmean(h_abs, axis=0)

    row_df = pd.DataFrame({
        "row": np.arange(len(row_score)),
        "mean_abs_vertical_jump": row_score,
    }).sort_values("mean_abs_vertical_jump", ascending=False)

    col_df = pd.DataFrame({
        "col": np.arange(len(col_score)),
        "mean_abs_horizontal_jump": col_score,
    }).sort_values("mean_abs_horizontal_jump", ascending=False)

    row_csv = os.path.join(outdir, f"{prefix}_top_rows.csv")
    col_csv = os.path.join(outdir, f"{prefix}_top_cols.csv")
    row_df.to_csv(row_csv, index=False)
    col_df.to_csv(col_csv, index=False)

    print(f"wrote {row_csv}")
    print(f"wrote {col_csv}")

    print("\nTop suspicious rows by mean absolute vertical neighbor jump:")
    print(row_df.head(10).to_string(index=False))

    print("\nTop suspicious columns by mean absolute horizontal neighbor jump:")
    print(col_df.head(10).to_string(index=False))


def align_pivots_for_diff(pivot_a, pivot_b):
    all_rows = sorted(set(pivot_a.index).union(set(pivot_b.index)))
    all_cols = sorted(set(pivot_a.columns).union(set(pivot_b.columns)))

    a = pivot_a.reindex(index=all_rows, columns=all_cols)
    b = pivot_b.reindex(index=all_rows, columns=all_cols)
    return a, b


def save_run_diff(current_good, baseline_good, latency_col, latency_label, outdir, prefix):
    current_pivot = make_pivot(current_good, latency_col)
    baseline_pivot = make_pivot(baseline_good, latency_col)

    current_pivot, baseline_pivot = align_pivots_for_diff(current_pivot, baseline_pivot)
    diff = current_pivot - baseline_pivot

    diff_vals = diff.to_numpy(dtype=float)
    finite = diff_vals[np.isfinite(diff_vals)]
    lim = np.nanpercentile(np.abs(finite), 95) if len(finite) else None

    out_png = os.path.join(outdir, f"{prefix}_run_diff_heatmap.png")
    save_heatmap_from_pivot(
        diff,
        out_png,
        "Difference in median round-trip latency between runs",
        f"Difference in {latency_label.lower()}",
        cmap="coolwarm",
        vmin=-lim if lim is not None else None,
        vmax=lim if lim is not None else None,
    )

    summary = pd.DataFrame({
        "metric": [
            "mean_diff",
            "median_diff",
            "min_diff",
            "max_diff",
            "mean_abs_diff",
            "median_abs_diff",
            "num_finite_cells",
        ],
        "value": [
            float(np.nanmean(finite)) if len(finite) else np.nan,
            float(np.nanmedian(finite)) if len(finite) else np.nan,
            float(np.nanmin(finite)) if len(finite) else np.nan,
            float(np.nanmax(finite)) if len(finite) else np.nan,
            float(np.nanmean(np.abs(finite))) if len(finite) else np.nan,
            float(np.nanmedian(np.abs(finite))) if len(finite) else np.nan,
            int(len(finite)),
        ]
    })

    summary_csv = os.path.join(outdir, f"{prefix}_run_diff_summary.csv")
    summary.to_csv(summary_csv, index=False)
    print(f"wrote {summary_csv}")

    print("\nRun-to-run difference summary:")
    print(summary.to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description="Unified latency plotting and wall-analysis tool")

    ap.add_argument("csv", help="input CSV, typically all_rtt.csv")
    ap.add_argument("--baseline-csv", help="optional baseline CSV for run-to-run diff")
    ap.add_argument("--cx", type=int, required=True, help="reference x-coordinate for line plots")
    ap.add_argument("--cy", type=int, required=True, help="reference y-coordinate for line plots")
    ap.add_argument("--outdir", default="plots", help="output directory")
    ap.add_argument("--prefix", default="latency", help="filename prefix")

    ap.add_argument(
        "--startup-mode",
        default="zero-manhattan-median",
        choices=["none", "min", "median", "zero-manhattan-median", "zero-chebyshev-median", "fixed"],
        help="method used to estimate startup latency before subtraction",
    )
    ap.add_argument("--startup-value", type=float, help="fixed startup value for --startup-mode fixed")

    ap.add_argument(
        "--units",
        default="cycles",
        choices=["cycles", "ns", "us"],
        help="output units for plots and summaries",
    )
    ap.add_argument("--freq-ghz", type=float, default=0.85, help="clock frequency in GHz, default is 0.85")
    ap.add_argument("--cycle-time-ns", type=float, help="optional cycle time in ns, overrides frequency")
    ap.add_argument("--hist-bins", type=int, default=60, help="number of histogram bins")

    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    raw, good = load_and_filter(args.csv)

    good, raw_latency_col, unit_name, cycle_time_ns = convert_units(
        good,
        source_col="rtt_cycles",
        output_unit=args.units,
        freq_ghz=args.freq_ghz,
        cycle_time_ns=args.cycle_time_ns,
    )

    good, latency_col, startup_baseline = apply_startup_subtraction(
        good,
        raw_latency_col,
        startup_mode=args.startup_mode,
        startup_value=args.startup_value,
    )

    startup_adjusted = args.startup_mode != "none"
    latency_label = determine_latency_label(unit_name, startup_adjusted=startup_adjusted)

    print("plot input summary:")
    print(f"  raw rows: {len(raw)}")
    print(f"  filtered rows: {len(good)}")
    print(f"  output units: {unit_name}")
    if cycle_time_ns is not None:
        print(f"  cycle time used for conversion: {cycle_time_ns:.9f} ns/cycle")
    elif args.units != "cycles":
        print(f"  cycle time used for conversion: {1.0 / args.freq_ghz:.9f} ns/cycle")
    print(f"  startup subtraction mode: {args.startup_mode}")
    print(f"  startup value subtracted: {startup_baseline:.6f}")

    heatmap_png = os.path.join(args.outdir, f"{args.prefix}_heatmap.png")
    step_manhattan_png = os.path.join(args.outdir, f"{args.prefix}_step_manhattan.png")
    step_chebyshev_png = os.path.join(args.outdir, f"{args.prefix}_step_chebyshev.png")
    step_direction_png = os.path.join(args.outdir, f"{args.prefix}_step_by_direction.png")
    summary_csv = os.path.join(args.outdir, f"{args.prefix}_summary_by_distance.csv")
    axis_prefix = os.path.join(args.outdir, args.prefix)
    hist_png = os.path.join(args.outdir, f"{args.prefix}_histogram.png")
    jump_compare_png = os.path.join(args.outdir, f"{args.prefix}_jump_compare.png")

    save_heatmap(
        good,
        heatmap_png,
        value_col=latency_col,
        title="Spatial map of median round-trip latency",
        cbar_label=latency_label,
    )

    save_step_plot(
        good,
        step_manhattan_png,
        latency_col=latency_col,
        latency_label=latency_label,
        dist_col="manhattan_dist",
        title="Median round-trip latency versus Manhattan distance",
    )

    save_step_plot(
        good,
        step_chebyshev_png,
        latency_col=latency_col,
        latency_label=latency_label,
        dist_col="chebyshev_dist",
        title="Median round-trip latency versus Chebyshev distance",
    )

    save_direction_step_plot(
        good,
        step_direction_png,
        latency_col=latency_col,
        latency_label=latency_label,
        dist_col="manhattan_dist",
    )

    save_axis_line_plots(
        good,
        latency_col=latency_col,
        latency_label=latency_label,
        cx=args.cx,
        cy=args.cy,
        out_prefix=axis_prefix,
    )

    save_summary_csv(good, latency_col=latency_col, out_csv=summary_csv)

    hist_title = "Histogram of startup-adjusted round-trip latency" if startup_adjusted else "Histogram of round-trip latency"
    save_histogram(
        good,
        latency_col=latency_col,
        latency_label=latency_label,
        out_png=hist_png,
        bins=args.hist_bins,
        title=hist_title,
    )

    pivot = make_pivot(good, latency_col)
    _, _, h_abs, v_abs = compare_neighbor_jumps(pivot)
    plot_jump_comparison(h_abs, v_abs, jump_compare_png, latency_label)
    save_difference_maps(pivot, args.outdir, args.prefix, latency_label)
    save_direction_scores(pivot, args.outdir, args.prefix)

    if args.baseline_csv:
        _, baseline_good = load_and_filter(args.baseline_csv)

        baseline_good, baseline_raw_latency_col, _, _ = convert_units(
            baseline_good,
            source_col="rtt_cycles",
            output_unit=args.units,
            freq_ghz=args.freq_ghz,
            cycle_time_ns=args.cycle_time_ns,
        )

        baseline_good, baseline_latency_col, baseline_startup = apply_startup_subtraction(
            baseline_good,
            baseline_raw_latency_col,
            startup_mode=args.startup_mode,
            startup_value=args.startup_value,
        )

        print("\nbaseline run summary:")
        print(f"  filtered rows: {len(baseline_good)}")
        print(f"  startup value subtracted: {baseline_startup:.6f}")

        save_run_diff(
            current_good=good,
            baseline_good=baseline_good,
            latency_col=latency_col,
            latency_label=latency_label,
            outdir=args.outdir,
            prefix=args.prefix,
        )


if __name__ == "__main__":
    main()
