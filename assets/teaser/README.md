# Teaser assets

Scripts and intermediate artifacts used to generate the images in the top-level
[README](../README.md) preview section. Everything here is self-contained and can
be regenerated from scratch; nothing in this folder is required by the pipeline
itself.

## 1. A longer calibration run

[`params_teaser.yml`](params_teaser.yml) is a copy of the project's `params.yml`
(human species, `IH_powerLaw_stressBased` model) with the sampler settings bumped
for a smoother, better-converged chain:

| setting  | default (`params.yml`) | teaser |
|----------|------------------------|--------|
| nwalkers | 50                     | 100    |
| nburn    | 250                    | 2500   |
| nsteps   | 500                    | 5000   |

Run with:

```
nextflow run main.nf --config_file assets/teaser/params_teaser.yml -profile local
```

(log kept at `nextflow_run.log`.) Nextflow assigns each run a random session
UUID (see `.nextflow.log`, "Session UUID" -- it is *not* reproducible or
choosable in advance), which `main.nf`'s `_workflowMeta` uses as the
`bundle_name` suffix. So once `BUNDLE_OUTPUTS` and `GENERATE_REPORT` complete,
the run's full bundle (`mcmc_idata.nc`, `corner_plot.png`, `report.pdf`,
`diagnostics/`, ...) lands under
`outputs/human_IH_powerLaw_stressBased_<session-id>/` -- find `<session-id>`
either in the Nextflow log or by listing `outputs/` for the newest
`human_IH_powerLaw_stressBased_*` directory. Copy that bundle here so the
scripts below (sections 2 and 3) have a fixed input to point at, e.g.:

```
cp -r outputs/human_IH_powerLaw_stressBased_<session-id> assets/teaser/
```

## 2. Report page grid

[`scripts/make_pdf_stack.py`](scripts/make_pdf_stack.py) renders each page of a
report PDF to PNG (`pdftoppm`) and composites the 4 pages as a 2x2 grid --
page 1/2 on top, page 3/4 below, the bottom row shifted right by
`ROW2_OFFSET_FRAC` (~12% of a tile's width) -- each with a drop shadow, on a
solid white canvas (a transparent one renders as black in some viewers, e.g.
GitHub dark mode).

Each page is trimmed to its own content instead of a fixed crop fraction:
`crop_to_content` finds the lowest non-white pixel and cuts just below it (plus
`CONTENT_PAD`). The page-number footer sits right at the bottom of every page,
so it's excluded from that search first (`FOOTER_EXCLUDE_PX`) -- otherwise it
alone would drag the detected content down to nearly the full page height on
every page.

Pages have very different amounts of content (page 1 is a short cover, page 2's
corner-plot grid + full parameter table is the tallest), so `crop_to_content`
alone gives four differently sized tiles -- a ragged, mismatched-looking grid.
`pad_to_height` then pads every tile (white, below) up to the height of the
*tallest* page, so all four end up the same size without ever cropping real
content. Padding tiles to a common height, plus the bottom row's rightward
shift, generally leaves the tile grid wider than it is tall; rather than force
that into a square by cropping or distorting anything, `build_grid` instead
pads out whichever axis (almost always the vertical one) falls short with
extra, evenly-split margin, so the final canvas is exactly square around a
centered, undistorted grid.

```
python assets/teaser/scripts/make_pdf_stack.py \
  assets/teaser/human_IH_powerLaw_stressBased_<session-id>/report.pdf \
  -o assets/teaser/report_stack.png
```

## 3. Calibration evolution animation

[`scripts/make_calibration_evolution.py`](scripts/make_calibration_evolution.py)
reads `mcmc_idata.nc` and renders a wide banner GIF where, for an increasing
number of draws:

- **left** (square): the joint corner plot (`corner`) over `A`, `alpha`, `beta`,
  with `show_titles=True` (median +/- quantiles, matching
  `mcmc/calibrate_emcee.py`'s own call) and axis ranges fixed to the min/max of
  the *post-burn-in* trace -- corner's own default range when given no explicit
  one -- so the final frame lands close to the actual `corner_plot.png` the
  workflow produces.
- **right** (square, one row per parameter): per-walker raw draws, then
  per-walker KDE next to it — the same two plot types as
  `diagnostics/run_diagnostics.py`'s trace figure (colored by chain with the
  same 8-hue cycle), just with the column order flipped so the draws sit next
  to the corner plot and the KDE trails off on the far right. No burn-in
  marker. The KDE panel's y-axis is fixed to each parameter's converged peak
  density (`compute_kde_ylims`, from the *final* chain) so it doesn't rescale
  (and visually jitter) frame to frame; early, noisy KDEs from very few draws
  just clip against that ceiling.

Axis ranges are fixed throughout so only the samples move, not the frame; the
trace/KDE figure also uses fixed subplot margins (`fig.subplots_adjust`, not
`tight_layout`) since `tight_layout`'s spacing depends on rendered tick-label
content and shifted slightly frame to frame, making the panel appear to resize
across the animation.

Frame *placement* (`frame_schedule`) packs extra density into the early
`EARLY_DRAWS_FRAC` of draws (`EARLY_FRAMES_FRAC` of the frame budget) -- that's
where the distribution is still visibly moving, the later chain is flat and
converged and needs far fewer frames to represent. Frame *duration*
(`frame_durations`) is proportional to how many draws each frame advanced over
the previous one, so playback reveals the chain at a constant "draws per
second" rather than visibly accelerating as the geometric spacing's jumps grow;
the final, fully-drawn frame then holds for `PAUSE_MS` before the GIF loops.

```
python assets/teaser/scripts/make_calibration_evolution.py \
  assets/teaser/human_IH_powerLaw_stressBased_<session-id>/mcmc_idata.nc \
  assets/teaser/human_IH_powerLaw_stressBased_<session-id>/params.yml \
  -o assets/teaser/calibration_evolution.gif --n-frames 60
```

Both scripts were run with the `mcmc` conda environment's Python (has `corner`,
`arviz`, `Pillow`), independent of the pipeline's own conda envs.
