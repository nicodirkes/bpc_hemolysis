import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import arviz as az
import corner
import numpy as np
import pandas as pd
import yaml
from scipy.signal import find_peaks

# az.kde/az.autocorr keep changing shape across arviz releases; the underlying
# array_stats module is more stable.
from arviz_stats.base.array import array_stats as _array_stats

# ---------------------------------------------------------------------------
# Global matplotlib defaults
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

N_BINS = 36
MAX_AUTOCORR_LAG = 100
RHAT_THRESHOLD = 1.01
SAVE_DPI = 200

# Matches corner's default show_titles quantiles ([0.16, 0.5, 0.84], i.e. the
# median with a ~68% interval) -- kept as one constant so the posterior
# summary table and the corner plot titles never drift apart.
SUMMARY_QUANTILES = [0.16, 0.5, 0.84]

# A KDE peak counts as a separate mode only if it stands at least this
# fraction of the tallest peak's height above its neighboring valleys --
# filters out small wiggles from KDE estimation noise, not real bimodality.
MODALITY_PROMINENCE_FRAC = 0.05

TRACE_COLOR = '#8cc5e3'

# Validated 8-hue categorical palette (fixed order, CVD-safe adjacency) used to
# color individual MCMC chains. Chain identity itself is meaningless (walker #17
# vs #3 carries no information), so beyond 8 chains the palette repeats rather
# than generating new hues -- keeps chains visually distinct without an
# unbounded rainbow.
CHAIN_COLORS = ['#2a78d6', '#1baf7a', '#eda100', '#008300',
                 '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
CHAIN_ALPHA = 0.65

# Per-subplot sizes (width, height) in inches.
# Trace rows are wide and short (time series needs horizontal space).
# Autocorr is near-square (symmetric lag axis).
# Posteriors are wider than tall (histogram).
TRACE_SUBPLOT_SIZE = (5.0, 2.5)
AUTOCORR_SUBPLOT_SIZE = (3.5, 3.0)
POSTERIOR_SUBPLOT_SIZE = (5.0, 4.0)


def run_quantitative_diagnostics(idata, param_labels, output_dir=None):
    """
    Write R-hat and ESS convergence diagnostics to a CSV file.

    Parameters
    ----------
    idata : arviz.InferenceData
    param_labels : dict
        Maps parameter names to display labels used as the CSV row index.
    output_dir : str or Path, optional
        Directory for convergence_diagnostics.csv. Defaults to current directory.
    """
    param_names = list(param_labels)
    summary = az.summary(idata, var_names=param_names, round_to=None)
    display = summary[["ess_bulk", "ess_tail", "r_hat"]].copy()
    display["converged"] = display["r_hat"].apply(
        lambda x: "PASS" if x <= RHAT_THRESHOLD else "FAIL"
    )

    # Use human-readable display labels as the row index
    display.index = [param_labels[p] for p in display.index]
    display.index.name = "parameter"

    out = Path(output_dir) if output_dir is not None else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "convergence_diagnostics.csv"
    display.to_csv(csv_path, float_format="%.6g")


def _count_modes(samples: np.ndarray) -> int:
    """Number of KDE peaks with prominence at least MODALITY_PROMINENCE_FRAC
    of the tallest peak -- small enough to catch genuine bimodality, large
    enough to ignore KDE estimation noise."""
    _grid, pdf, _bw = _array_stats.kde(samples)
    peaks, _props = find_peaks(pdf, prominence=MODALITY_PROMINENCE_FRAC * pdf.max())
    return max(1, len(peaks))


def run_posterior_summary(idata, param_labels, output_dir=None):
    """
    Write a posterior summary CSV: median, the same 68% quantile interval
    corner's plot titles use (SUMMARY_QUANTILES), and a KDE-based modality
    check -- kept in its own table (rather than folded into
    convergence_diagnostics.csv) so it reads as "what the posterior looks
    like" next to the priors table, separate from convergence diagnostics.

    Parameters
    ----------
    idata : arviz.InferenceData
    param_labels : dict
        Maps parameter names to display labels used as the CSV row index.
    output_dir : str or Path, optional
        Directory for posterior_summary.csv. Defaults to current directory.
    """
    param_names = list(param_labels)
    samples = az.extract(idata, var_names=param_names, combined=True)

    rows = []
    for param in param_names:
        vals = samples[param].values
        q16, median, q84 = np.quantile(vals, SUMMARY_QUANTILES)
        n_modes = _count_modes(vals)
        rows.append({
            "parameter": param_labels[param],
            "median": median,
            "q16": q16,
            "q84": q84,
            "modality": "Unimodal" if n_modes <= 1 else "Multimodal",
        })

    out = Path(output_dir) if output_dir is not None else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "posterior_summary.csv"
    pd.DataFrame(rows).set_index("parameter").to_csv(csv_path, float_format="%.6g")


def _make_subplot_grid(n_params, n_cols, subplot_size):
    """Create a subplot grid scaled by per-subplot size. Returns flattened axes."""
    n_cols = min(n_cols, n_params)
    n_rows = int(np.ceil(n_params / n_cols))
    figsize = (n_cols * subplot_size[0], n_rows * subplot_size[1])
    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    axes_flat = np.array(axes).flatten()
    for ax in axes_flat[n_params:]:
        ax.axis('off')
    return fig, axes_flat, n_rows, n_cols


def _save_figure(fig, output_dir, filename):
    plt.tight_layout()
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_dir / filename, dpi=SAVE_DPI, bbox_inches='tight')


def _plot_trace(idata, param_labels, output_dir, nburn=0, filename='trace.png', mark_burnin=False):
    """
    Trace plot: left panel is the per-chain KDE, right panel is the raw draws.

    mark_burnin=False (default): KDE and traces use the full chain -- burn-in
        behavior stays visible (used for trace.png).
    mark_burnin=True: KDE uses only draws after `nburn` (matching what the
        quantitative summary reports on), the trace panel still shows the full
        chain, and a vertical line marks the burn-in cutoff (used for
        trace_postburnin.png).
    """
    param_names = list(param_labels)
    n_params = len(param_names)

    w, h = TRACE_SUBPLOT_SIZE
    fig, axes = plt.subplots(n_params, 2, figsize=(2 * w, n_params * h))
    if n_params == 1:
        axes = axes.reshape(1, -1)

    posterior = az.extract(idata, var_names=param_names, combined=False)
    for i, (param, label) in enumerate(param_labels.items()):
        da = posterior[param]
        draws = da['draw'].values

        for c in range(da.sizes['chain']):
            color = CHAIN_COLORS[c % len(CHAIN_COLORS)]
            chain_vals = da.isel(chain=c).values
            kde_vals = chain_vals[nburn:] if mark_burnin else chain_vals
            grid, pdf, _bw = _array_stats.kde(kde_vals)
            axes[i, 0].plot(grid, pdf, color=color, alpha=CHAIN_ALPHA, linewidth=1.0)
            axes[i, 1].plot(draws, chain_vals, color=color, alpha=CHAIN_ALPHA, linewidth=0.8)

        if mark_burnin and nburn:
            axes[i, 1].axvline(nburn, color='dimgray', linestyle='--', linewidth=1.0, alpha=0.8)

        axes[i, 0].set_ylabel(label)

    if mark_burnin and nburn:
        axes[0, 1].text(nburn, axes[0, 1].get_ylim()[1], ' burn-in', color='dimgray',
                         fontsize=8, ha='left', va='top')

    axes[-1, 0].set_xlabel('Density')
    axes[-1, 1].set_xlabel('Draw')
    _save_figure(fig, output_dir, filename)


def _autocorr(idata, param, max_lag):
    """Per-chain autocorrelation averaged across chains."""
    chains = idata.posterior[param].transpose('chain', 'draw').values
    return np.mean([_array_stats.autocorr(c)[:max_lag + 1] for c in chains], axis=0)


def _plot_autocorr(idata, param_labels, output_dir):
    param_names = list(param_labels)
    n_params = len(param_names)
    fig, axes_flat, _, n_cols = _make_subplot_grid(n_params, n_cols=3,
                                                   subplot_size=AUTOCORR_SUBPLOT_SIZE)

    # Bottom-most filled subplot per column (the grid can be ragged when
    # n_params isn't a multiple of n_cols, so that's not always the last row).
    last_idx_per_col = {idx % n_cols: idx for idx in range(n_params)}

    lags = np.arange(MAX_AUTOCORR_LAG + 1)
    for idx, (param, label) in enumerate(param_labels.items()):
        ax = axes_flat[idx]
        acf = _autocorr(idata, param, MAX_AUTOCORR_LAG)

        ax.vlines(lags, 0, acf, color=TRACE_COLOR)
        ax.axhline(0, color='dimgray', linestyle='--', linewidth=0.5, alpha=0.5)
        ax.set_ylim(-0.1, 1.05)
        ax.text(0.5, 1.02, label, transform=ax.transAxes, fontsize=10,
                verticalalignment='bottom', horizontalalignment='center')
        if idx % n_cols == 0:
            ax.set_ylabel('Autocorrelation')
        if idx == last_idx_per_col[idx % n_cols]:
            ax.set_xlabel('Lag')

    _save_figure(fig, output_dir, 'autocorr.png')


def _plot_posteriors(idata, param_labels, output_dir):
    param_names = list(param_labels)
    n_params = len(param_names)
    fig, axes_flat, _, _ = _make_subplot_grid(n_params, n_cols=2,
                                              subplot_size=POSTERIOR_SUBPLOT_SIZE)

    for idx, (param, label) in enumerate(param_labels.items()):
        ax = axes_flat[idx]
        ax.hist(idata.posterior[param].values.flatten(),
                bins=N_BINS, color=TRACE_COLOR, edgecolor='none')
        ax.set_xlabel(label)
        ax.set_ylabel('Frequency')

    _save_figure(fig, output_dir, 'posteriors.png')


def _plot_corner(idata, param_labels, output_dir):
    """Pairwise posterior corner plot (post burn-in draws only)."""
    param_names = list(param_labels)
    samples = az.extract(idata, var_names=param_names, combined=True)
    data = np.column_stack([samples[p].values for p in param_names])
    labels = [param_labels[p] for p in param_names]

    fig = corner.corner(data, labels=labels, show_titles=True)
    _save_figure(fig, output_dir, 'corner_plot.png')


def run_diagnostics(idata, param_labels=None, output_dir=None, nburn=0):
    """
    Create MCMC diagnostics. Qualitative plots and Quantitative metrics

    Parameters
    ----------
    idata : arviz.InferenceData
    param_labels : dict, optional
        Maps parameter names to display labels.
        Example: mu and xi
    output_dir : str or Path, optional
        Directory to save figures/tables. Filenames are fixed:
        trace.png, trace_postburnin.png, autocorr.png, posteriors.png,
        corner_plot.png, convergence_diagnostics.csv, posterior_summary.csv.
    nburn : int, optional
        Leading draws discarded as burn-in for the quantitative summary
        (convergence_diagnostics.csv) and for trace_postburnin.png's KDE
        panel. trace.png always shows the full chain so burn-in behavior
        stays visible there.
    """
    if param_labels is None:
        param_labels = {p: p for p in idata.posterior.data_vars}

    out = Path(output_dir) if output_dir is not None else None

    post_burnin = idata.isel(draw=slice(nburn, None)) if nburn else idata

    _plot_trace(idata, param_labels, out)
    _plot_trace(idata, param_labels, out, nburn=nburn, filename='trace_postburnin.png', mark_burnin=True)
    _plot_autocorr(idata, param_labels, out)
    _plot_posteriors(idata, param_labels, out)
    _plot_corner(post_burnin, param_labels, out)

    run_quantitative_diagnostics(post_burnin, param_labels, out)
    run_posterior_summary(post_burnin, param_labels, out)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MCMC diagnostics on a NetCDF inference data file.")
    parser.add_argument("--idata-path", type=Path, help="Path to the .nc InferenceData file.")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="Directory to write outputs (default: current directory).")
    parser.add_argument("--config", type=Path, default=None,
                        help="YAML config file to read calibration.nburn from (draws discarded as "
                             "burn-in for the convergence summary only). No trimming if omitted.")
    args = parser.parse_args()

    nburn = 0
    if args.config is not None:
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        nburn = cfg["calibration"]["nburn"]

    idata = az.from_netcdf(args.idata_path)
    run_diagnostics(idata, output_dir=args.output_dir, nburn=nburn)