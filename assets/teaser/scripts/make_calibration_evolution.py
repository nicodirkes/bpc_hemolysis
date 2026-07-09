#!/usr/bin/env python3
"""Render a GIF of an MCMC chain's traces and marginal posteriors evolving as
draws accumulate, paired with the joint corner plot on the left."""

import argparse
import io
from pathlib import Path

import arviz as az
import corner
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import yaml
from PIL import Image

N_FRAMES_DEFAULT = 50
TOTAL_GROWTH_MS = 5500  # total playback time spent revealing the chain, before the pause
MIN_FRAME_MS = 40
MAX_FRAME_MS = 220
PAUSE_MS = 1400  # how long the final, fully-drawn frame holds before the GIF loops
EARLY_DRAWS_FRAC = 0.1   # fraction of total draws considered the "vivid", still-moving region
EARLY_FRAMES_FRAC = 0.6  # fraction of all frames spent covering that early region
CORNER_COLOR = "#333333"
KDE_YLIM_HEADROOM = 1.15

# Same per-chain palette as diagnostics/run_diagnostics.py -- chain identity is
# meaningless, so the 8-hue cycle repeating across nwalkers is intentional.
CHAIN_COLORS = ['#2a78d6', '#1baf7a', '#eda100', '#008300',
                '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
CHAIN_ALPHA = 0.5
MIN_DRAWS_FOR_KDE = 5

TRACE_SUBPLOT_SIZE = (3.75, 2.5)  # (width, height) inches -- 2 cols x 3 rows renders ~square


def load_prior_bounds(params_yaml: Path, params: list[str]) -> list[tuple]:
    cfg = yaml.safe_load(params_yaml.read_text())
    bounds = {}
    for prior in cfg["calibration"]["priors"]:
        attr = prior["distribution"]["attribute"]
        if "lower_bound" in attr and "upper_bound" in attr:
            bounds[prior["name"]] = (attr["lower_bound"], attr["upper_bound"])
    return [bounds[p] for p in params]


def load_chain(idata_path: Path, params: list[str]) -> np.ndarray:
    ds = xr.open_dataset(idata_path, group="posterior")
    # (nwalkers, ndraws, nparams) -- transpose explicitly, dims are not guaranteed ordered.
    return np.stack([ds[p].transpose("chain", "draw").values for p in params], axis=-1)


def compute_corner_ranges(chain: np.ndarray, nburn: int) -> list[tuple]:
    """Match report/mcmc's corner_plot.png axis limits: mcmc/calibrate_emcee.py
    calls corner.corner(trace) with no explicit `range`, and corner's default
    is exactly (x.min(), x.max()) of whatever samples it's given -- here, the
    post-burn-in trace. Using this (instead of the full prior bounds) as a
    fixed range for every frame means the last frame lands close to what the
    actual workflow produces."""
    post_burnin = chain[:, nburn:, :]
    return [(post_burnin[:, :, i].min(), post_burnin[:, :, i].max()) for i in range(chain.shape[-1])]


def fig_to_image(fig, dpi=110) -> Image.Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGBA")
    img.load()
    return img


def render_corner_frame(samples: np.ndarray, params: list[str], ranges) -> Image.Image:
    fig = corner.corner(
        samples,
        labels=params,
        range=ranges,
        color=CORNER_COLOR,
        plot_datapoints=True,
        data_kwargs={"alpha": 0.25, "ms": 1.5},
        hist_kwargs={"color": CORNER_COLOR},
        levels=(0.39, 0.86),
        smooth=0.8,
        show_titles=True,
    )
    return fig_to_image(fig)


def compute_kde_ylims(chain: np.ndarray) -> list[float]:
    """Fixed y-limit per parameter for the KDE panel, from the peak density of
    each walker's *final* (most-converged) chain. Early frames with few draws
    can spike well above this -- that's fine, it just clips against the ceiling
    instead of making the axis rescale (and thus visually jitter) every frame."""
    nparams = chain.shape[-1]
    ymax = []
    for i in range(nparams):
        peaks = [az.kde(chain[c, :, i])[1].max() for c in range(chain.shape[0])]
        ymax.append(max(peaks) * KDE_YLIM_HEADROOM)
    return ymax


def render_trace_frame(chain: np.ndarray, t: int, params: list[str], ranges, kde_ylims) -> Image.Image:
    """Left column: per-chain raw draws. Right column: per-chain KDE of the
    parameter (same idea as diagnostics/run_diagnostics.py's trace plot, column
    order flipped so draws sit next to the corner plot). Figure geometry (size,
    margins) is fixed regardless of `t` so frames composite into the GIF
    without any drift/jitter."""
    ndraws_total = chain.shape[1]
    nwalkers = chain.shape[0]
    w, h = TRACE_SUBPLOT_SIZE
    fig, axes = plt.subplots(len(params), 2, figsize=(2 * w, len(params) * h))

    for i, name in enumerate(params):
        ax_trace, ax_kde = axes[i]
        for c in range(nwalkers):
            color = CHAIN_COLORS[c % len(CHAIN_COLORS)]
            chain_vals = chain[c, :t, i]
            ax_trace.plot(np.arange(t), chain_vals, color=color, alpha=CHAIN_ALPHA, linewidth=0.8)
            if t >= MIN_DRAWS_FOR_KDE:
                grid, pdf = az.kde(chain_vals)
                ax_kde.plot(grid, pdf, color=color, alpha=CHAIN_ALPHA, linewidth=1.0)

        ax_trace.set_xlim(0, ndraws_total)
        ax_trace.set_ylim(*ranges[i])
        ax_trace.set_ylabel(name)
        ax_kde.set_xlim(*ranges[i])
        ax_kde.set_ylim(0, kde_ylims[i])

    axes[-1, 0].set_xlabel("Draw")
    axes[-1, 1].set_xlabel("Density")
    # Fixed margins instead of tight_layout: tight_layout's spacing depends on
    # rendered tick-label content, which changes slightly frame to frame and
    # made the panel appear to resize across the animation.
    fig.subplots_adjust(left=0.11, right=0.98, top=0.95, bottom=0.10, hspace=0.35, wspace=0.25)
    return fig_to_image(fig)


def compose_frame(corner_img: Image.Image, trace_img: Image.Image) -> Image.Image:
    h = max(corner_img.height, trace_img.height)

    def resize_to_h(img):
        w = int(img.width * h / img.height)
        return img.resize((w, h), Image.LANCZOS)

    corner_img, trace_img = resize_to_h(corner_img), resize_to_h(trace_img)
    pad = 24
    canvas = Image.new("RGBA", (corner_img.width + trace_img.width + pad, h), (255, 255, 255, 255))
    canvas.paste(corner_img, (0, 0), corner_img)
    canvas.paste(trace_img, (corner_img.width + pad, 0), trace_img)
    return canvas


def frame_schedule(ndraws_total: int, n_frames: int) -> list[int]:
    """Geometrically spaced draw counts, with extra density packed into the
    early `EARLY_DRAWS_FRAC` of draws -- that's the "vivid" part where the
    distribution is still visibly moving, so it gets `EARLY_FRAMES_FRAC` of
    the frame budget instead of its plain share of the log-range."""
    split = max(2, int(ndraws_total * EARLY_DRAWS_FRAC))
    n_early = max(2, int(round(n_frames * EARLY_FRAMES_FRAC)))
    n_late = max(2, n_frames - n_early)

    early = np.geomspace(max(2, ndraws_total // 200), split, n_early)
    late = np.geomspace(split, ndraws_total, n_late)
    raw = np.unique(np.round(np.concatenate([early, late])).astype(int))
    return raw.tolist()


def frame_durations(ts: list[int]) -> list[int]:
    """Per-frame display time proportional to how many draws that frame added
    over the previous one, so the chain reveals at a constant "draws per
    second" instead of visibly accelerating as `frame_schedule`'s geometric
    spacing produces ever-larger jumps between frames."""
    deltas = np.diff([0] + ts).astype(float)
    ms = deltas / deltas.sum() * TOTAL_GROWTH_MS
    return np.clip(ms, MIN_FRAME_MS, MAX_FRAME_MS).round().astype(int).tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idata", type=Path, help="Path to mcmc_idata.nc")
    parser.add_argument("params_yaml", type=Path, help="params.yml used for the run (for prior bounds)")
    parser.add_argument("-o", "--output", type=Path, default=Path("assets/teaser/calibration_evolution.gif"))
    parser.add_argument("--params", nargs="+", default=["A", "alpha", "beta"])
    parser.add_argument("--n-frames", type=int, default=N_FRAMES_DEFAULT)
    args = parser.parse_args()

    cfg = yaml.safe_load(args.params_yaml.read_text())
    nburn = cfg["calibration"]["nburn"]

    chain = load_chain(args.idata, args.params)
    ranges = load_prior_bounds(args.params_yaml, args.params)
    corner_ranges = compute_corner_ranges(chain, nburn)
    ndraws_total = chain.shape[1]
    kde_ylims = compute_kde_ylims(chain)

    ts = frame_schedule(ndraws_total, args.n_frames)
    durations = frame_durations(ts)

    frames = []
    for t in ts:
        samples = chain[:, :t, :].reshape(-1, len(args.params))
        corner_img = render_corner_frame(samples, args.params, corner_ranges)
        trace_img = render_trace_frame(chain, t, args.params, ranges, kde_ylims)
        frames.append(compose_frame(corner_img, trace_img))
        print(f"rendered frame t={t}/{ndraws_total}")

    durations[-1] = PAUSE_MS  # hold on the fully-drawn chain before looping

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].convert("RGB").save(
        args.output,
        save_all=True,
        append_images=[f.convert("RGB") for f in frames[1:]],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Saved {args.output} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
