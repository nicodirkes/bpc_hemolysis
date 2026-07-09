import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from fpdf import FPDF

RHAT_EXCELLENT = 1.01
RHAT_GOOD      = 1.10
ESS_EXCELLENT  = 400
ESS_ACCEPTABLE = 100

# Ink hierarchy (light surface) -- text always wears these, never a series/status
# color, so status hues stay legible as a distinct signal.
INK_PRIMARY   = (11, 11, 11)
INK_SECONDARY = (82, 81, 78)
INK_MUTED     = (137, 135, 129)
HAIRLINE      = (225, 224, 217)
BASELINE      = (195, 194, 183)

# Fixed status palette (good/warning/critical) -- reserved meaning, never reused
# for series identity. Muted rather than saturated so the hero color bars read
# as a calm strip of color, not an alarm.
STATUS_EXCELLENT = (58, 140, 87)    # #3a8c57 "good"
STATUS_GOOD      = (196, 145, 45)   # #c4912d "warning"
STATUS_POOR      = (185, 74, 74)    # #b94a4a "critical"

PAGE_MARGIN_MM = 15
FONT = "Helvetica"


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a PDF report for an MCMC calibration run.")
    parser.add_argument("--bundle-dir", type=Path, required=True,
                        help="Path to the bundle output directory produced by BUNDLE_OUTPUTS.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output PDF path. Defaults to report.pdf in CWD.")
    return parser.parse_args()


def parse_params(params_path: Path) -> dict:
    with open(params_path) as f:
        return yaml.safe_load(f)


# Shared quality rank, worst to best -- lets R-hat and ESS (which use different
# middle-tier wording) be combined into one per-parameter verdict by rank alone.
RANK_POOR, RANK_MID, RANK_EXCELLENT = 0, 1, 2
UNIFIED_QUALITY = {
    RANK_EXCELLENT: ("Excellent", STATUS_EXCELLENT),
    RANK_MID:       ("Good",      STATUS_GOOD),
    RANK_POOR:      ("Poor",      STATUS_POOR),
}


def rhat_label(value: float) -> tuple:
    if value < RHAT_EXCELLENT:
        return "Excellent", STATUS_EXCELLENT, RANK_EXCELLENT
    elif value < RHAT_GOOD:
        return "Good", STATUS_GOOD, RANK_MID
    return "Poor", STATUS_POOR, RANK_POOR


def ess_label(value: float) -> tuple:
    if value > ESS_EXCELLENT:
        return "Excellent", STATUS_EXCELLENT, RANK_EXCELLENT
    elif value > ESS_ACCEPTABLE:
        return "Acceptable", STATUS_GOOD, RANK_MID
    return "Poor", STATUS_POOR, RANK_POOR


def mode_rank(ranks: list) -> int:
    """Most common rank; ties broken toward the better (higher) rank."""
    counts = {r: ranks.count(r) for r in set(ranks)}
    best_count = max(counts.values())
    return max(r for r, c in counts.items() if c == best_count)


class MCMCReport(FPDF):
    def __init__(self, title: str, meta: str):
        super().__init__()
        self._title = title
        self._meta = meta
        self.set_margins(PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM)
        self.set_auto_page_break(auto=True, margin=PAGE_MARGIN_MM)

    def header(self):
        self.set_font(FONT, "", 8)
        self.set_text_color(*INK_MUTED)
        self.cell(0, 5, self._title, align="L")
        self.set_x(-70)
        self.cell(55, 5, self._meta, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*HAIRLINE)
        self.set_line_width(0.2)
        y = self.get_y() + 1
        self.line(PAGE_MARGIN_MM, y, self.w - PAGE_MARGIN_MM, y)
        self.set_y(y + 5)
        self.set_text_color(*INK_PRIMARY)

    def footer(self):
        self.set_y(-12)
        self.set_font(FONT, "", 8)
        self.set_text_color(*INK_MUTED)
        self.cell(0, 8, f"{self.page_no()}", align="C")
        self.set_text_color(*INK_PRIMARY)

    def section_title(self, text: str):
        self.set_font(FONT, "B", 15)
        self.set_text_color(*INK_PRIMARY)
        self.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*HAIRLINE)
        self.set_line_width(0.3)
        y = self.get_y() + 1
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_y(y + 5)

    def subsection_title(self, text: str):
        self.set_font(FONT, "B", 10)
        self.set_text_color(*INK_MUTED)
        self.cell(0, 6, text.upper(), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_text_color(*INK_PRIMARY)

    def body_text(self, text: str):
        self.set_font(FONT, "", 9.5)
        self.set_text_color(*INK_SECONDARY)
        self.multi_cell(0, 5.5, text)
        self.set_text_color(*INK_PRIMARY)
        self.ln(2)

    def embed_image(self, img_path: Path, caption: str, w_mm: float = 160):
        x = (self.w - w_mm) / 2
        self.image(str(img_path), x=x, w=w_mm)
        self.set_font(FONT, "I", 9)
        self.set_text_color(*INK_SECONDARY)
        self.cell(0, 6, caption, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*INK_PRIMARY)
        self.ln(4)


def draw_hairline_table(pdf: MCMCReport, headers: list, col_widths: list, rows: list, row_h: float = 8):
    """
    Borderless table: bold muted uppercase header over a baseline rule, then
    rows separated by hairlines instead of a full cell grid.

    rows : list of list of (text, align, color_or_None, bold)
    """
    pdf.set_font(FONT, "B", 8)
    pdf.set_text_color(*INK_MUTED)
    for h, w in zip(headers, col_widths):
        pdf.cell(w, 6, h.upper(), align="L")
    pdf.ln(6)

    pdf.set_draw_color(*BASELINE)
    pdf.set_line_width(0.3)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.l_margin + sum(col_widths), y)
    pdf.ln(1)

    for row in rows:
        for (text, align, color, bold), w in zip(row, col_widths):
            pdf.set_font(FONT, "B" if bold else "", 9.5)
            pdf.set_text_color(*(color if color else INK_PRIMARY))
            pdf.cell(w, row_h, str(text), align=align)
        pdf.ln(row_h)
        pdf.set_draw_color(*HAIRLINE)
        pdf.set_line_width(0.2)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.l_margin + sum(col_widths), y)

    pdf.set_text_color(*INK_PRIMARY)
    pdf.ln(3)


def draw_segment_bar(pdf: MCMCReport, x: float, y: float, w: float, h: float, colors: list):
    """One equal-width filled rect per entry in `colors`, drawn left to right in order."""
    seg_w = w / len(colors)
    for i, color in enumerate(colors):
        pdf.set_fill_color(*color)
        pdf.rect(x + i * seg_w, y, seg_w, h, style="F")


def add_hero(pdf: MCMCReport, cfg: dict, diag_csv_path: Path, generated_at: str, session_id: str):
    pdf.add_page()

    pdf.set_font(FONT, "B", 22)
    pdf.set_text_color(*INK_PRIMARY)
    pdf.cell(0, 11, "Calibration Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(FONT, "", 13)
    pdf.set_text_color(*INK_SECONDARY)
    pdf.cell(0, 7, f"{cfg['species'].capitalize()} - {cfg['model']['name']}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*INK_MUTED)
    pdf.cell(0, 6, f"Generated {generated_at} - Session {session_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK_PRIMARY)
    pdf.ln(6)

    df = pd.read_csv(diag_csv_path)

    # Per-parameter verdicts, in table row order -- these feed both the
    # headline (worst-case, or mode for Quality) and each tile's color bar,
    # which shows the per-parameter breakdown behind that headline.
    rhat_colors, ess_colors, combined_colors, combined_ranks = [], [], [], []
    for _, row in df.iterrows():
        _, rhat_color, rhat_rank = rhat_label(float(row["r_hat"]))
        _, ess_bulk_color, ess_bulk_rank = ess_label(float(row["ess_bulk"]))
        _, ess_tail_color, ess_tail_rank = ess_label(float(row["ess_tail"]))
        ess_rank = min(ess_bulk_rank, ess_tail_rank)
        ess_color = ess_bulk_color if ess_bulk_rank <= ess_tail_rank else ess_tail_color

        rhat_colors.append(rhat_color)
        ess_colors.append(ess_color)

        combined_rank = min(rhat_rank, ess_rank)
        combined_ranks.append(combined_rank)
        combined_colors.append(UNIFIED_QUALITY[combined_rank][1])

    worst_rhat = float(df["r_hat"].max())
    min_ess = float(df[["ess_bulk", "ess_tail"]].min().min())
    _, rhat_color, _ = rhat_label(worst_rhat)
    _, ess_color, _  = ess_label(min_ess)

    # Quality headline is the most common per-parameter verdict (ties broken
    # toward the better rank), not the worst case -- Worst R-hat and Min ESS
    # already surface the bottleneck, so Quality reads as "what's typical".
    quality_text, quality_color = UNIFIED_QUALITY[mode_rank(combined_ranks)]

    tiles = [
        ("Quality",     quality_text,         quality_color, combined_colors),
        ("Worst R-hat", f"{worst_rhat:.2f}",  rhat_color,    rhat_colors),
        ("Min ESS",     f"{min_ess:.0f}",     ess_color,     ess_colors),
    ]
    content_w = pdf.w - 2 * PAGE_MARGIN_MM
    tile_w = content_w / len(tiles)
    bar_w = tile_w - 6
    bar_h = 2.2
    y0 = pdf.get_y()
    for i, (label, value, color, colors) in enumerate(tiles):
        x = PAGE_MARGIN_MM + i * tile_w
        pdf.set_xy(x, y0)
        pdf.set_font(FONT, "B", 20)
        pdf.set_text_color(*color)
        pdf.cell(tile_w, 10, value, align="L")
        pdf.set_xy(x, y0 + 10)
        pdf.set_font(FONT, "", 8)
        pdf.set_text_color(*INK_MUTED)
        pdf.cell(tile_w, 5, label.upper(), align="L")
        draw_segment_bar(pdf, x, y0 + 15.5, bar_w, bar_h, colors)

    pdf.set_xy(PAGE_MARGIN_MM, y0 + 21)
    pdf.set_text_color(*INK_PRIMARY)
    pdf.set_draw_color(*HAIRLINE)
    pdf.set_line_width(0.2)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 6)


def add_run_info(pdf: MCMCReport, cfg: dict):
    pdf.section_title("Run Configuration")

    cal = cfg["calibration"]
    model = cfg["model"]

    config_rows = [
        ("Species",           cfg["species"]),
        ("Model",             model["name"]),
        ("Control variables", ", ".join(model["control_variables"])),
        ("Likelihood",        cal["likelihood"]),
        ("MCMC walkers",      str(cal["nwalkers"])),
        ("Burn-in steps",     str(cal["nburn"])),
        ("Production steps",  str(cal["nsteps"] - cal["nburn"])),
        ("Calibrate noise",   "Yes" if cal.get("calibrate_noise") else "No"),
    ]
    label_w = 55
    row_h = 6.5
    for label, value in config_rows:
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*INK_MUTED)
        pdf.cell(label_w, row_h, label, align="L")
        pdf.set_font(FONT, "", 10.5)
        pdf.set_text_color(*INK_PRIMARY)
        pdf.cell(0, row_h, str(value), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.subsection_title("Calibrated Parameters")
    headers = ["Parameter", "Distribution", "Bound / Location", "Bound / Scale"]
    col_widths = [45, 45, 45, 45]
    rows = []
    for prior in cal["priors"]:
        dist = prior["distribution"]
        attr = dist["attribute"]
        if dist["type"] == "uniform":
            b1, b2 = str(attr["lower_bound"]), str(attr["upper_bound"])
        else:
            b1, b2 = str(attr.get("location", "")), str(attr.get("scale", ""))
        rows.append([
            (prior["name"],          "L", None, True),
            (dist["type"].capitalize(), "L", None, False),
            (b1, "R", None, False),
            (b2, "R", None, False),
        ])
    draw_hairline_table(pdf, headers, col_widths, rows)


def add_diagnostics_section(pdf: MCMCReport, bundle_dir: Path, cfg: dict):
    diag_dir = bundle_dir / "diagnostics"
    nwalkers = cfg["calibration"]["nwalkers"]

    pdf.add_page()
    pdf.section_title("MCMC Diagnostics")

    pdf.embed_image(img_path=diag_dir / "corner_plot.png",
                     caption="Figure 1 - Pairwise posterior corner plot.",
                     w_mm=150)

    pdf.set_font(FONT, "I", 9)
    pdf.set_text_color(*INK_SECONDARY)
    pdf.cell(0, 5, f"Table 1 - Convergence diagnostics (post burn-in, {nwalkers} walkers).",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK_PRIMARY)
    pdf.ln(2)
    add_diagnostics_table(pdf, diag_dir / "convergence_diagnostics.csv")
    pdf.body_text(
        "R-hat thresholds: < 1.01 = Excellent, 1.01-1.10 = Good, >= 1.10 = Poor (Vehtari et al., 2021).\n"
        "ESS thresholds: > 400 = Excellent, 101-400 = Acceptable, <= 100 = Poor (Vehtari et al., 2021)."
    )

    pdf.embed_image(img_path=diag_dir / "trace.png",
                     caption="Figure 2 - Trace plots. Left: posterior density (full chain); right: sample traces per walker.",
                     w_mm=160)
    pdf.embed_image(img_path=diag_dir / "autocorr.png",
                     caption="Figure 3 - Autocorrelation by lag for each parameter.",
                     w_mm=160)


def add_diagnostics_table(pdf: MCMCReport, csv_path: Path):
    df = pd.read_csv(csv_path)

    headers = ["Parameter", "Mean", "SD", "ESS bulk", "ESS tail", "R-hat", "ESS quality", "R-hat quality"]
    col_widths = [25, 20, 20, 21, 21, 20, 26, 27]

    rows = []
    for _, row in df.iterrows():
        ess_bulk = float(row["ess_bulk"])
        ess_tail = float(row["ess_tail"])
        rhat     = float(row["r_hat"])

        ess_bulk_text, ess_bulk_status, _ = ess_label(ess_bulk)
        ess_tail_text, ess_tail_status, _ = ess_label(ess_tail)
        rhat_text,     rhat_status,     _ = rhat_label(rhat)

        # ESS quality uses the worse of bulk/tail
        worse_is_bulk = ess_bulk <= ess_tail
        ess_quality_text   = ess_bulk_text if worse_is_bulk else ess_tail_text
        ess_quality_status = ess_bulk_status if worse_is_bulk else ess_tail_status

        rows.append([
            (str(row["parameter"]),        "L", None, False),
            (f"{float(row['mean']):.4f}",  "R", None, False),
            (f"{float(row['sd']):.4f}",    "R", None, False),
            (f"{ess_bulk:.0f}",            "R", None, False),
            (f"{ess_tail:.0f}",            "R", None, False),
            (f"{rhat:.2f}",                "R", None, False),
            (ess_quality_text,             "C", ess_quality_status, True),
            (rhat_text,                    "C", rhat_status, True),
        ])

    draw_hairline_table(pdf, headers, col_widths, rows)


def main():
    args = parse_args()
    bundle_dir = args.bundle_dir.resolve()
    output_path = args.output if args.output else Path("report.pdf")

    cfg = parse_params(bundle_dir / "params.yml")
    now = datetime.now()
    generated_at = f"{now.day} {now:%b %Y, %H:%M}"
    session_id = bundle_dir.name.split("_")[-1]
    running_title = f"BPC_Hemolysis // {cfg['species'].capitalize()} // {cfg['model']['name']}"

    pdf = MCMCReport(title=running_title, meta=generated_at)
    add_hero(pdf, cfg, bundle_dir / "diagnostics" / "convergence_diagnostics.csv", generated_at, session_id)
    add_run_info(pdf, cfg)
    add_diagnostics_section(pdf, bundle_dir, cfg)

    pdf.output(str(output_path))
    print(f"Report written to: {output_path}")


if __name__ == "__main__":
    main()
