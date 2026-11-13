#!/usr/bin/env python3

import os
import math
import textwrap
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


def ensure_dirs():
    os.makedirs("plots", exist_ok=True)
    os.makedirs("tables", exist_ok=True)


def load_data(csv_path):
    df = pd.read_csv(csv_path)

    numeric_cols = [
        "tensor_size",
        "DIST",
        "NUM_MSGS",
        "cycle_count",
        "cycles_per_msg",
        "cycles_per_payload_word",
        "cycles_per_word_hop",
        "fabric_word_hops",
        "total_payload_words",
        "idle_fraction_est",
        "useful_cycles_est",
        "one_way_hops",
        "round_trip_hops",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "correctness" in df.columns:
        df = df[df["correctness"].fillna("").str.lower() == "pass"].copy()

    if "failure_class" in df.columns:
        df = df[df["failure_class"].fillna("").str.lower() == "pass"].copy()

    return df


def set_style():
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams["figure.figsize"] = (10, 6)
    plt.rcParams["axes.titlesize"] = 18
    plt.rcParams["axes.labelsize"] = 14
    plt.rcParams["legend.fontsize"] = 11
    plt.rcParams["xtick.labelsize"] = 12
    plt.rcParams["ytick.labelsize"] = 12


def save_table(df, path, title=None, float_cols=None, round_digits=3):
    out = df.copy()
    if float_cols is not None:
        for col in float_cols:
            if col in out.columns:
                out[col] = out[col].round(round_digits)
    out.to_csv(path, index=False)

    if title:
        print()
        print(title)
        print(out.to_string(index=False))

def plot_cycles_per_msg_vs_num_msgs(df):
    subset = df[
        (df["tensor_size"].isin([4, 8, 16])) &
        (df["DIST"].isin([0, 2, 8])) &
        (df["NUM_MSGS"].isin([1, 10, 100]))
    ].copy()

    if subset.empty:
        print("Skipping cycles_per_msg_vs_num_msgs plot, no matching data.")
        return

    g = sns.relplot(
        data=subset,
        x="NUM_MSGS",
        y="cycles_per_msg",
        hue="DIST",
        col="tensor_size",
        kind="line",
        marker="o",
        facet_kws={"sharey": True, "sharex": True},
        height=5,
        aspect=1.1,
        palette="deep",
    )

    g.set(xscale="log")
    g.set_axis_labels("NUM_MSGS", "Cycles per message")
    g.set_titles("tensor_size = {col_name}")
    g.fig.subplots_adjust(top=0.83)
    g.fig.suptitle("Ping-pong startup amortization")

    for ax in g.axes.flat:
        ax.grid(True, alpha=0.3)

    g.savefig("plots/cycles_per_msg_vs_num_msgs.png", dpi=220, bbox_inches="tight")
    plt.close(g.fig)

def plot_cycle_count_vs_fabric_word_hops(df):
    subset = df.copy()
    if subset.empty:
        print("Skipping cycle_count_vs_fabric_word_hops plot, no data.")
        return

    plt.figure(figsize=(10, 7))
    ax = sns.scatterplot(
        data=subset,
        x="fabric_word_hops",
        y="cycle_count",
        hue="DIST",
        style="tensor_size",
        size="NUM_MSGS",
        sizes=(70, 250),
        palette="viridis",
    )

    sns.regplot(
        data=subset,
        x="fabric_word_hops",
        y="cycle_count",
        scatter=False,
        ci=None,
        line_kws={"color": "black", "linewidth": 2, "alpha": 0.7},
    )

    ax.set_title("Runtime vs communication work")
    ax.set_xlabel("Fabric word hops")
    ax.set_ylabel("Cycle count")
    ax.grid(True, alpha=0.3)

    plt.savefig("plots/cycle_count_vs_fabric_word_hops.png", dpi=220, bbox_inches="tight")
    plt.close()


def plot_cycles_per_word_hop_vs_dist(df):
    subset = df[
        (df["NUM_MSGS"].isin([1, 10, 100])) &
        (df["tensor_size"].isin([1, 4, 8, 16]))
    ].copy()

    if subset.empty:
        print("Skipping cycles_per_word_hop_vs_dist plot, no matching data.")
        return

    plt.figure(figsize=(11, 7))
    ax = sns.lineplot(
        data=subset,
        x="DIST",
        y="cycles_per_word_hop",
        hue="tensor_size",
        style="NUM_MSGS",
        markers=True,
        dashes=False,
        linewidth=2.5,
        palette="tab10",
    )

    ax.set_title("Transport efficiency vs distance")
    ax.set_xlabel("Distance")
    ax.set_ylabel("Cycles per word hop")
    ax.grid(True, alpha=0.3)

    plt.savefig("plots/cycles_per_word_hop_vs_dist.png", dpi=220, bbox_inches="tight")
    plt.close()


def plot_idle_fraction_vs_num_msgs(df):
    subset = df[
        (df["tensor_size"].isin([4, 8, 16])) &
        (df["DIST"].isin([0, 2, 8])) &
        (df["NUM_MSGS"].isin([1, 10, 100]))
    ].copy()

    if subset.empty:
        print("Skipping idle_fraction_vs_num_msgs plot, no matching data.")
        return

    subset["series"] = subset.apply(
        lambda r: f"tensor={int(r['tensor_size'])}, dist={int(r['DIST'])}",
        axis=1
    )

    plt.figure(figsize=(11, 7))
    ax = sns.lineplot(
        data=subset,
        x="NUM_MSGS",
        y="idle_fraction_est",
        hue="series",
        marker="o",
        linewidth=2.5,
    )

    ax.set_xscale("log")
    ax.set_title("Estimated idle fraction vs message count")
    ax.set_xlabel("NUM_MSGS")
    ax.set_ylabel("Idle fraction estimate")
    ax.grid(True, alpha=0.3)

    plt.savefig("plots/idle_fraction_vs_num_msgs.png", dpi=220, bbox_inches="tight")
    plt.close()


def make_presentation_tables(df):
    float_cols = [
        "cycle_count",
        "cycles_per_msg",
        "cycles_per_payload_word",
        "cycles_per_word_hop",
        "fabric_word_hops",
        "idle_fraction_est",
    ]

    table1 = (
        df[df["tensor_size"] == 4]
        .loc[df["DIST"].isin([0, 2, 8]) & df["NUM_MSGS"].isin([1, 10, 100]),
             ["tensor_size", "DIST", "NUM_MSGS", "cycle_count", "cycles_per_msg",
              "fabric_word_hops", "cycles_per_word_hop", "idle_fraction_est"]]
        .sort_values(["DIST", "NUM_MSGS"])
        .reset_index(drop=True)
    )
    save_table(
        table1,
        "tables/table_tensor4_message_scaling.csv",
        title="Table 1, tensor_size = 4 scaling summary",
        float_cols=float_cols,
        round_digits=3,
    )

    table2 = (
        df[df["NUM_MSGS"] == 1]
        .loc[df["tensor_size"].isin([1, 4, 16]) & df["DIST"].isin([0, 2, 8]),
             ["tensor_size", "DIST", "NUM_MSGS", "cycle_count", "cycles_per_msg",
              "fabric_word_hops", "cycles_per_payload_word", "cycles_per_word_hop"]]
        .sort_values(["tensor_size", "DIST"])
        .reset_index(drop=True)
    )
    save_table(
        table2,
        "tables/table_single_message_distance_payload.csv",
        title="Table 2, single-message distance and payload summary",
        float_cols=float_cols,
        round_digits=3,
    )

    table3 = (
        df[df["NUM_MSGS"] == 100]
        .loc[df["tensor_size"].isin([4, 8]) & df["DIST"].isin([0, 1, 2, 6, 8]),
             ["tensor_size", "DIST", "NUM_MSGS", "cycle_count", "total_payload_words",
              "fabric_word_hops", "cycles_per_msg", "cycles_per_word_hop", "idle_fraction_est"]]
        .sort_values(["tensor_size", "DIST"])
        .reset_index(drop=True)
    )
    save_table(
        table3,
        "tables/table_high_volume_efficiency.csv",
        title="Table 3, high-volume efficiency summary",
        float_cols=float_cols,
        round_digits=3,
    )

    pivot = (
        df[df["tensor_size"].isin([4]) & df["DIST"].isin([0, 2, 8]) & df["NUM_MSGS"].isin([1, 10, 100])]
        .pivot_table(
            index="DIST",
            columns="NUM_MSGS",
            values="cycles_per_msg",
            aggfunc="first"
        )
        .reset_index()
    )
    pivot.columns.name = None
    pivot = pivot.rename(columns={1: "NUM_MSGS_1", 10: "NUM_MSGS_10", 100: "NUM_MSGS_100"})
    save_table(
        pivot,
        "tables/table_cycles_per_msg_pivot_tensor4.csv",
        title="Table 4, cycles per message pivot for tensor_size = 4",
        float_cols=["NUM_MSGS_1", "NUM_MSGS_10", "NUM_MSGS_100"],
        round_digits=3,
    )


def make_summary_stats(df):
    summary = pd.DataFrame({
        "metric": [
            "row_count",
            "min_cycle_count",
            "max_cycle_count",
            "min_cycles_per_msg",
            "max_cycles_per_msg",
            "min_idle_fraction_est",
            "max_idle_fraction_est",
        ],
        "value": [
            len(df),
            df["cycle_count"].min(),
            df["cycle_count"].max(),
            df["cycles_per_msg"].min(),
            df["cycles_per_msg"].max(),
            df["idle_fraction_est"].min(),
            df["idle_fraction_est"].max(),
        ]
    })

    save_table(
        summary,
        "tables/table_summary_stats.csv",
        title="Overall summary stats",
        float_cols=["value"],
        round_digits=6,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Plot ping-pong performance results")
    parser.add_argument(
        "--csv",
        default="perf_results.csv",
        help="Path to perf_results.csv"
    )
    args = parser.parse_args()

    ensure_dirs()
    set_style()

    df = load_data(args.csv)

    required = [
        "tensor_size",
        "DIST",
        "NUM_MSGS",
        "cycle_count",
        "cycles_per_msg",
        "fabric_word_hops",
        "cycles_per_word_hop",
        "idle_fraction_est",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    make_summary_stats(df)
    make_presentation_tables(df)

    plot_cycles_per_msg_vs_num_msgs(df)
    plot_cycle_count_vs_fabric_word_hops(df)
    plot_cycles_per_word_hop_vs_dist(df)
    plot_idle_fraction_vs_num_msgs(df)

    print()
    print("Done.")
    print("Plots written to: plots/")
    print("Tables written to: tables/")


if __name__ == "__main__":
    main()
