"""
Cross-experiment comparison for a calibration sweep.

Reads every bundle produced by BUNDLE_OUTPUTS under one sweep directory and
reduces the whole study to artefacts that answer "what did the modeling choices
actually change?":

  experiment_summary.csv  one row per run -- its sweep coordinates, the posterior
                          of every parameter, the convergence verdict, and the
                          predictive scores
  loo_comparison.csv      ELPD ranking, computed separately within each data mode
                          (see WHY_STRATIFIED below)
  sensitivity.csv         main effect of each sweep dimension on each parameter
  posterior_forest.png    every run's posterior interval per parameter, ordered
                          and coloured by one sweep dimension
  elpd_comparison.png     predictive performance with standard errors
  sensitivity.png         which choice moved which parameter, and by how much

Runs standalone on any directory of bundles:

    python compare_experiments.py --sweep-dir outputs/experiments/<run> \
                                  --output-dir comparison
"""

import argparse
import itertools
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
import arviz as az

# ---------------------------------------------------------------------------
# Why the ELPD ranking is stratified by data mode
# ---------------------------------------------------------------------------
# LOO/WAIC compare models by the density they assign to *the same observations*.
# The raw and averaged datasets are different observation sets -- 76 measurements
# versus 26 group means -- so their ELPDs live on different scales and must never
# be put in one ranking. Prior, likelihood and noise model all leave the
# observations untouched, so those three dimensions are directly comparable.
STRATIFY_BY = "data_mode"

# ---------------------------------------------------------------------------
# Style -- shared with diagnostics/run_diagnostics.py and report/generate_report.py
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#e5e5e5",
    "grid.linewidth": 0.6,
    "figure.dpi": 300,
})

# Same validated categorical palette as the diagnostics unit, in the same fixed
# order -- a hue means the same sweep level in every figure of the study.
CATEGORICAL_COLORS = ['#2a78d6', '#1baf7a', '#eda100', '#008300',
                      '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
INK_SECONDARY = '#525148'
INK_MUTED = '#898781'

SAVE_DPI = 200

# Share of the figure height reserved under the axes for a figure-level legend.
LEGEND_STRIP = 0.08

# Central and outer credible mass, matching the diagnostics unit's summary
# quantiles so the numbers in the two places never disagree.
INNER_QUANTILES = (0.16, 0.84)
OUTER_QUANTILES = (0.025, 0.975)

RHAT_THRESHOLD = 1.01
PARETO_K_THRESHOLD = 0.7

# The sweep coordinates, in the order they are reported.
DIMENSIONS = ["species", "model", "prior", "likelihood", "noise_model", "data_mode"]


# ---------------------------------------------------------------------------
# Reading one bundle
# ---------------------------------------------------------------------------

def noise_model_name(cal: dict) -> str:
    """Configs predating the `noise_model` key distinguished only guess vs. constant."""
    return cal.get("noise_model") or ("uniform" if cal.get("calibrate_noise") else "heuristic")


def prior_name(cal: dict) -> str:
    """One label for the run's prior family, or 'mixed' if it uses several."""
    types = {p["distribution"]["type"] for p in cal["priors"]}
    return next(iter(types)) if len(types) == 1 else "mixed"


def coordinates(cfg: dict) -> dict:
    cal = cfg["calibration"]
    return {
        "species": cfg["species"],
        "model": cfg["model"]["name"],
        "prior": prior_name(cal),
        "likelihood": cal.get("likelihood", "normal"),
        "noise_model": noise_model_name(cal),
        "data_mode": cfg.get("dataset", {}).get("mode", "raw"),
    }


def read_bundle(bundle_dir: Path) -> dict:
    """Everything the comparison needs from one run, or None if it is incomplete."""
    params_path = bundle_dir / "params.yml"
    idata_path = bundle_dir / "mcmc_idata.nc"
    if not params_path.exists() or not idata_path.exists():
        return None

    with open(params_path) as f:
        cfg = yaml.safe_load(f)

    record = {"bundle": bundle_dir.name, **coordinates(cfg)}
    cal = cfg["calibration"]
    nburn = cal["nburn"]

    idata = az.from_netcdf(idata_path)
    posterior = idata.posterior if hasattr(idata, "posterior") else idata["posterior"]
    post_burnin = posterior.isel(draw=slice(nburn, None))

    # --- posterior location and spread, per parameter
    for name in post_burnin.data_vars:
        values = np.asarray(post_burnin[name].values).reshape(-1)
        q_lo, q_hi = np.quantile(values, INNER_QUANTILES)
        o_lo, o_hi = np.quantile(values, OUTER_QUANTILES)
        record[f"{name}_median"] = float(np.median(values))
        record[f"{name}_q16"] = float(q_lo)
        record[f"{name}_q84"] = float(q_hi)
        record[f"{name}_q025"] = float(o_lo)
        record[f"{name}_q975"] = float(o_hi)
        # Posterior width relative to its own centre -- how sharply the run
        # identified the parameter, comparable across parameters of different scale.
        record[f"{name}_relwidth"] = float((q_hi - q_lo) / abs(np.median(values))) if np.median(values) else np.nan

    # --- convergence, from the diagnostics unit's own table where available
    diag_csv = bundle_dir / "diagnostics" / "convergence_diagnostics.csv"
    if diag_csv.exists():
        diag = pd.read_csv(diag_csv)
        record["max_rhat"] = float(diag["r_hat"].max())
        record["min_ess"] = float(diag[["ess_bulk", "ess_tail"]].min().min())
        record["converged"] = bool(record["max_rhat"] <= RHAT_THRESHOLD)

    record.update(predictive_scores(bundle_dir / "predictive_idata.nc"))
    return record


def predictive_scores(predictive_path: Path) -> dict:
    """
    ELPD (leave-one-out) plus two checks the ELPD cannot express on its own:
    how far the predictions sit from the data, and whether the predictive
    intervals are honest about their own width.
    """
    if not predictive_path.exists():
        return {}

    idata = az.from_netcdf(predictive_path)
    scores = {}

    with warnings.catch_warnings():
        # A high Pareto k is reported through the max_pareto_k column instead of
        # a warning stream that would repeat once per bundle.
        warnings.simplefilter("ignore")
        try:
            loo = az.loo(idata, pointwise=True)
            scores["elpd_loo"] = float(loo.elpd)
            scores["elpd_loo_se"] = float(loo.se)
            scores["p_loo"] = float(loo.p)
            pareto_k = np.asarray(loo.pareto_k.values)
            scores["max_pareto_k"] = float(np.max(pareto_k))
            scores["n_bad_pareto_k"] = int((pareto_k > PARETO_K_THRESHOLD).sum())
        except Exception as exc:  # a run whose likelihood never became finite
            print(f"  LOO unavailable for {predictive_path.parent.name}: {exc}")

    observed = np.asarray(idata["observed_data"]["fHb"].values).reshape(-1)
    predictive = np.asarray(idata["posterior_predictive"]["fHb"].values)
    draws = predictive.reshape(-1, predictive.shape[-1])

    # Posterior-mean fit. The predictive here is the model response without the
    # observation noise, so this is the residual of the calibrated model itself.
    mean_prediction = np.nanmean(draws, axis=0)
    scores["rmse"] = float(np.sqrt(np.nanmean((observed - mean_prediction) ** 2)))

    # Calibration of the parameter uncertainty: the share of measurements inside
    # the central 95% band of the model response. Well below 0.95 means the
    # posterior is over-confident about the response.
    lo, hi = np.nanquantile(draws, OUTER_QUANTILES, axis=0)
    scores["coverage_95"] = float(np.mean((observed >= lo) & (observed <= hi)))
    return scores


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def parameter_names(summary: pd.DataFrame) -> list:
    """Parameters that at least one run reported, in a stable order."""
    names = [c[: -len("_median")] for c in summary.columns if c.endswith("_median")]
    preferred = ["A", "alpha", "beta", "h", "k", "sigma", "sigma_rel"]
    ordered = [n for n in preferred if n in names]
    return ordered + [n for n in names if n not in ordered]


def sensitivity_table(summary: pd.DataFrame, parameters: list) -> pd.DataFrame:
    """
    Main effect of each sweep dimension on each parameter: how far the posterior
    median moves between the levels of that dimension, averaged over everything
    else. Reported in units of the parameter and relative to the run-to-run
    posterior width, so the size of a shift can be read against the uncertainty
    it has to compete with.
    """
    rows = []
    for dimension in DIMENSIONS:
        if dimension not in summary.columns:
            continue
        levels = summary[dimension].dropna().unique()
        if len(levels) < 2:
            continue
        for param in parameters:
            column = f"{param}_median"
            per_level = summary.groupby(dimension)[column].mean().dropna()
            if len(per_level) < 2:
                continue
            spread = float(per_level.max() - per_level.min())
            typical_width = float((summary[f"{param}_q84"] - summary[f"{param}_q16"]).median())
            rows.append({
                "dimension": dimension,
                "parameter": param,
                "range_of_medians": spread,
                "typical_posterior_width": typical_width,
                # > 1 means the choice moves the estimate further than one
                # posterior interval -- i.e. the choice matters more than the
                # uncertainty a single run reports.
                "effect_vs_uncertainty": spread / typical_width if typical_width else np.nan,
                "best_level": per_level.idxmax(),
                "worst_level": per_level.idxmin(),
            })
    return pd.DataFrame(rows).sort_values("effect_vs_uncertainty", ascending=False)


def loo_ranking(summary: pd.DataFrame) -> pd.DataFrame:
    """
    ELPD ranking within each stratum of comparable observations (see STRATIFY_BY).
    Differences are reported against the best run of the stratum, with the
    standard error of the difference -- a gap smaller than a few standard errors
    is not evidence of a better model.
    """
    if "elpd_loo" not in summary.columns:
        return pd.DataFrame()

    frames = []
    for stratum, group in summary.groupby(STRATIFY_BY):
        group = group.dropna(subset=["elpd_loo"]).sort_values("elpd_loo", ascending=False)
        if group.empty:
            continue
        best = group.iloc[0]
        # SE of a difference of two independent estimates; the runs share the
        # data, so this is an upper bound on the true standard error.
        se_diff = np.sqrt(group["elpd_loo_se"] ** 2 + float(best["elpd_loo_se"]) ** 2)
        frames.append(pd.DataFrame({
            STRATIFY_BY: stratum,
            "rank": np.arange(1, len(group) + 1),
            "prior": group["prior"].values,
            "likelihood": group["likelihood"].values,
            "noise_model": group["noise_model"].values,
            "elpd_loo": group["elpd_loo"].values,
            "elpd_loo_se": group["elpd_loo_se"].values,
            "d_elpd": (group["elpd_loo"] - float(best["elpd_loo"])).values,
            "d_elpd_se": se_diff.values,
            "max_pareto_k": group.get("max_pareto_k", pd.Series(np.nan, index=group.index)).values,
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _level_colors(levels) -> dict:
    return {level: CATEGORICAL_COLORS[i % len(CATEGORICAL_COLORS)]
            for i, level in enumerate(levels)}


def _run_label(row) -> str:
    return f"{row['prior'][:9]} | {row['likelihood']} | {row['noise_model']} | {row['data_mode']}"


def plot_posterior_forest(summary: pd.DataFrame, parameters: list, color_by: str,
                          output_dir: Path, filename="posterior_forest.png"):
    """
    One row per run, one panel per parameter: the posterior median with its 68%
    and 95% intervals. Runs are sorted by the colouring dimension so the levels
    of that choice form contiguous blocks -- if a choice matters, its block
    separates from the others along the axis.
    """
    parameters = [p for p in parameters if f"{p}_median" in summary.columns]
    if not parameters:
        return

    ordered = summary.sort_values([color_by] + [d for d in DIMENSIONS if d != color_by])
    levels = list(dict.fromkeys(ordered[color_by]))
    colors = _level_colors(levels)
    y = np.arange(len(ordered))[::-1]

    fig, axes = plt.subplots(1, len(parameters),
                             figsize=(3.4 * len(parameters) + 3.5, 0.34 * len(ordered) + 2.2),
                             sharey=True)
    axes = np.atleast_1d(axes)

    for ax, param in zip(axes, parameters):
        median = ordered[f"{param}_median"].values
        for i, (_, row) in enumerate(ordered.iterrows()):
            if np.isnan(median[i]):
                continue
            color = colors[row[color_by]]
            # Outer interval as a hairline, inner as the visually dominant bar,
            # so the eye reads the 68% mass first without losing the tails.
            ax.plot([row[f"{param}_q025"], row[f"{param}_q975"]], [y[i], y[i]],
                    color=color, linewidth=1.0, alpha=0.55, solid_capstyle="butt")
            ax.plot([row[f"{param}_q16"], row[f"{param}_q84"]], [y[i], y[i]],
                    color=color, linewidth=2.6, solid_capstyle="butt")
            ax.plot([median[i]], [y[i]], marker='o', markersize=4.5, color=color,
                    markeredgecolor='white', markeredgewidth=0.8, zorder=3)
        ax.set_xlabel(param)
        ax.grid(axis='y', visible=False)

    axes[0].set_yticks(y)
    axes[0].set_yticklabels([_run_label(row) for _, row in ordered.iterrows()],
                            fontsize=7, color=INK_SECONDARY)
    axes[0].tick_params(axis='y', length=0)

    fig.suptitle("Posterior median with 68% and 95% credible intervals, per run",
                 fontsize=12, y=1.0)

    handles = [plt.Line2D([], [], color=colors[level], linewidth=2.6, label=str(level))
               for level in levels]
    _legend_below(fig, handles, color_by.replace('_', ' '), min(len(levels), 4))
    _save(fig, output_dir, filename, tight=False)


def plot_elpd(summary: pd.DataFrame, output_dir: Path, filename="elpd_comparison.png"):
    """
    ELPD per run with its standard error, one panel per stratum of comparable
    observations. Higher is better; runs whose error bars overlap the best run's
    are not distinguishable by predictive performance.
    """
    if "elpd_loo" not in summary.columns or summary["elpd_loo"].isna().all():
        return

    strata = list(dict.fromkeys(summary[STRATIFY_BY]))
    fig, axes = plt.subplots(1, len(strata), figsize=(6.0 * len(strata), 6.0), squeeze=False)

    levels = list(dict.fromkeys(summary["noise_model"]))
    colors = _level_colors(levels)

    for ax, stratum in zip(axes[0], strata):
        group = (summary[summary[STRATIFY_BY] == stratum]
                 .dropna(subset=["elpd_loo"]).sort_values("elpd_loo"))
        if group.empty:
            ax.axis('off')
            continue
        y = np.arange(len(group))
        for i, (_, row) in enumerate(group.iterrows()):
            color = colors[row["noise_model"]]
            ax.errorbar(row["elpd_loo"], y[i], xerr=row["elpd_loo_se"], fmt='o',
                        markersize=5, color=color, ecolor=color, elinewidth=1.4,
                        capsize=0, markeredgecolor='white', markeredgewidth=0.8)
        best = group["elpd_loo"].max()
        ax.axvline(best, color=INK_MUTED, linestyle='--', linewidth=1.0, alpha=0.7)
        ax.set_yticks(y)
        ax.set_yticklabels([f"{r['prior'][:9]} | {r['likelihood']} | {r['noise_model']}"
                            for _, r in group.iterrows()], fontsize=7, color=INK_SECONDARY)
        ax.tick_params(axis='y', length=0)
        ax.grid(axis='y', visible=False)
        ax.set_xlabel("ELPD (leave-one-out)")
        ax.set_title(f"{STRATIFY_BY.replace('_', ' ')} = {stratum}", color=INK_SECONDARY)

    handles = [plt.Line2D([], [], color=colors[level], marker='o', linestyle='',
                          markersize=6, label=str(level)) for level in levels]
    _legend_below(fig, handles, "noise model", min(len(levels), 4))
    _save(fig, output_dir, filename, tight=False)


def plot_sensitivity(sensitivity: pd.DataFrame, output_dir: Path, filename="sensitivity.png"):
    """
    How far each modeling choice moves each parameter, in units of the posterior
    width a single run reports. Bars past 1 mark choices that matter more than
    the uncertainty the calibration itself quotes.
    """
    if sensitivity.empty:
        return

    parameters = list(dict.fromkeys(sensitivity["parameter"]))
    dimensions = list(dict.fromkeys(sensitivity["dimension"]))
    colors = _level_colors(dimensions)

    fig, ax = plt.subplots(figsize=(1.6 * len(parameters) + 4.0, 5.0))
    width = 0.8 / len(dimensions)
    x = np.arange(len(parameters))

    for j, dimension in enumerate(dimensions):
        subset = sensitivity[sensitivity["dimension"] == dimension].set_index("parameter")
        values = [subset["effect_vs_uncertainty"].get(p, np.nan) for p in parameters]
        # A 2px surface gap between adjacent bars keeps the groups legible.
        ax.bar(x + j * width - 0.4 + width / 2, values, width * 0.88,
               color=colors[dimension], label=dimension.replace('_', ' '))

    ax.axhline(1.0, color=INK_MUTED, linestyle='--', linewidth=1.0)
    ax.text(len(parameters) - 0.5, 1.02, 'one posterior width', fontsize=8,
            color=INK_MUTED, ha='right', va='bottom')
    ax.set_xticks(x)
    ax.set_xticklabels(parameters)
    ax.set_ylabel("shift in posterior median / posterior width")
    ax.set_xlabel("parameter")
    ax.grid(axis='x', visible=False)
    ax.legend(frameon=False, ncol=2, fontsize=9)
    ax.set_title("Effect of each modeling choice, against the uncertainty of one run",
                 color=INK_SECONDARY)
    _save(fig, output_dir, filename)


def _save(fig, output_dir: Path, filename: str, tight=True):
    output_dir.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.tight_layout()
    fig.savefig(output_dir / filename, dpi=SAVE_DPI, bbox_inches='tight')
    plt.close(fig)
    print(f"  wrote {output_dir / filename}")


def _legend_below(fig, handles, title, ncol):
    """Figure-level legend in a strip reserved under the axes. The layout runs
    first so the legend cannot land on top of the x-axis labels."""
    fig.tight_layout(rect=(0, LEGEND_STRIP, 1, 1))
    fig.legend(handles=handles, title=title, loc='lower center', ncol=ncol,
               frameon=False, bbox_to_anchor=(0.5, 0.0))


# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep-dir", type=Path, required=True,
                        help="Directory holding the per-experiment bundles.")
    parser.add_argument("--output-dir", type=Path, default=Path("comparison"),
                        help="Where to write the tables and figures.")
    parser.add_argument("--color-by", default="noise_model", choices=DIMENSIONS,
                        help="Sweep dimension that colours and orders the forest plot.")
    return parser.parse_args()


def main():
    args = parse_args()

    bundles = sorted(d for d in args.sweep_dir.iterdir()
                     if d.is_dir() and (d / "params.yml").exists())
    if not bundles:
        raise SystemExit(f"No bundles with a params.yml found under {args.sweep_dir}")

    print(f"Reading {len(bundles)} bundles from {args.sweep_dir}")
    records = [r for r in (read_bundle(b) for b in bundles) if r is not None]
    summary = pd.DataFrame(records)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "experiment_summary.csv"
    summary.to_csv(summary_path, index=False, float_format="%.6g")
    print(f"  wrote {summary_path}  ({len(summary)} runs)")

    parameters = parameter_names(summary)

    sensitivity = sensitivity_table(summary, parameters)
    sensitivity.to_csv(args.output_dir / "sensitivity.csv", index=False, float_format="%.6g")
    print(f"  wrote {args.output_dir / 'sensitivity.csv'}")

    ranking = loo_ranking(summary)
    if not ranking.empty:
        ranking.to_csv(args.output_dir / "loo_comparison.csv", index=False, float_format="%.6g")
        print(f"  wrote {args.output_dir / 'loo_comparison.csv'}")

    plot_posterior_forest(summary, parameters, args.color_by, args.output_dir)
    plot_elpd(summary, args.output_dir)
    plot_sensitivity(sensitivity, args.output_dir)

    # A short console verdict, so a sweep can be triaged without opening anything.
    if "converged" in summary.columns:
        failed = summary.loc[~summary["converged"].astype(bool), "bundle"]
        print(f"\nConvergence: {len(summary) - len(failed)}/{len(summary)} runs with max R-hat <= {RHAT_THRESHOLD}")
        for name in failed:
            print(f"  R-hat above threshold: {name}")
    if not sensitivity.empty:
        print("\nLargest effects (shift in posterior median / posterior width):")
        for _, row in sensitivity.head(5).iterrows():
            print(f"  {row['dimension']:>16} on {row['parameter']:<10} {row['effect_vs_uncertainty']:.2f}")


if __name__ == "__main__":
    main()
