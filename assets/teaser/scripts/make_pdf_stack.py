#!/usr/bin/env python3
"""Render the pages of a report PDF to PNG and composite them as a 2x2 grid
(page 1, 2 on top; page 3, 4 below, shifted right) with drop shadows."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

RENDER_DPI = 200
ROW2_OFFSET_FRAC = 0.12  # fraction of tile width the bottom row shifts right
GAP = 70                 # px between tiles, in both directions
MARGIN = 60
CONTENT_PAD = 60          # px kept below the last non-white content when trimming
WHITE_THRESHOLD = 250     # grayscale value above which a pixel counts as "blank"
FOOTER_EXCLUDE_PX = 130   # bottom band to ignore when searching for content (page-number footer lives here)
SHADOW_BLUR = 18
SHADOW_OFFSET = (10, 14)
SHADOW_OPACITY = 110  # 0-255
BORDER_WIDTH = 2
BORDER_COLOR = (210, 208, 200)


def render_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    prefix = out_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(RENDER_DPI), str(pdf_path), str(prefix)],
        check=True,
    )
    return sorted(out_dir.glob("page-*.png"))


def crop_to_content(img: Image.Image) -> Image.Image:
    """Trim trailing blank space instead of a fixed fraction: find the lowest
    non-white pixel and cut just below it (plus padding), so pages with more
    content keep more of it and mostly-blank pages don't drag the whole thing
    out. The page-number footer sits right at the bottom of every page, so it
    gets excluded from the search first -- otherwise it alone would drag the
    bbox down to nearly the full page height regardless of real content."""
    searchable = img.crop((0, 0, img.width, max(1, img.height - FOOTER_EXCLUDE_PX)))
    mask = searchable.convert("L").point(lambda p: 255 if p < WHITE_THRESHOLD else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return img
    lower = min(img.height, bbox[3] + CONTENT_PAD)
    return img.crop((0, 0, img.width, lower))


def pad_to_height(img: Image.Image, target_h: int) -> Image.Image:
    """Pad with white below to an exact height (never crops -- `target_h` is
    chosen as the tallest of the four pages, so every real page fits) so all
    four tiles become uniform -- a mix of tile sizes reads as a ragged,
    mismatched grid rather than the clean square this is meant to be."""
    if img.height >= target_h:
        return img
    canvas = Image.new("RGB", (img.width, target_h), (255, 255, 255))
    canvas.paste(img, (0, 0))
    return canvas


def add_shadow(img: Image.Image) -> Image.Image:
    pad = SHADOW_BLUR * 3
    w, h = img.size
    canvas = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_shape = Image.new("L", img.size, SHADOW_OPACITY)
    shadow.paste(shadow_shape, (pad + SHADOW_OFFSET[0], pad + SHADOW_OFFSET[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas = Image.alpha_composite(canvas, shadow)

    bordered = ImageOps.expand(img.convert("RGB"), border=BORDER_WIDTH, fill=BORDER_COLOR)
    canvas.paste(bordered, (pad, pad))
    return canvas


def build_grid(page_paths: list[Path], out_path: Path) -> None:
    if len(page_paths) < 4:
        raise SystemExit(f"expected at least 4 pages, got {len(page_paths)}")

    pages = [Image.open(p).convert("RGB") for p in page_paths[:4]]
    cropped = [crop_to_content(p) for p in pages]

    content_w = cropped[0].width
    row2_offset = int(content_w * ROW2_OFFSET_FRAC)
    # Tallest page's content sets the shared tile height -- padding the others
    # out to match (never cropping) keeps every page's content fully visible.
    target_h = max(c.height for c in cropped)

    tiles = [add_shadow(pad_to_height(img, target_h)) for img in cropped]
    # Post-shadow size (bigger than content_w/target_h by the shadow's padding)
    # -- positions/canvas must use this, not the pre-shadow content size, or
    # neighboring tiles' shadows would overlap.
    tile_w, tile_h = tiles[0].size

    grid_w = 2 * tile_w + GAP + row2_offset
    grid_h = 2 * tile_h + GAP
    # Force a square canvas without cropping or distorting any tile: whichever
    # axis the tile grid falls short on gets extra margin split evenly on both
    # sides, so the grid stays centered.
    side = max(grid_w, grid_h) + 2 * MARGIN
    margin_x = (side - grid_w) // 2
    margin_y = (side - grid_h) // 2
    canvas = Image.new("RGB", (side, side), (255, 255, 255))

    positions = [
        (margin_x, margin_y),
        (margin_x + tile_w + GAP, margin_y),
        (margin_x + row2_offset, margin_y + tile_h + GAP),
        (margin_x + row2_offset + tile_w + GAP, margin_y + tile_h + GAP),
    ]
    for tile, pos in zip(tiles, positions):
        canvas.paste(tile, pos, tile)

    canvas.save(out_path)
    print(f"Saved {out_path} ({canvas.size[0]}x{canvas.size[1]})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to the report PDF")
    parser.add_argument("-o", "--output", type=Path, default=Path("assets/teaser/report_stack.png"))
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pages = render_pages(args.pdf, Path(tmp))
        if not pages:
            raise SystemExit("pdftoppm produced no pages")
        build_grid(pages, args.output)


if __name__ == "__main__":
    main()
