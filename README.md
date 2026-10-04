# png2eps

Convert pixel art PNG images to pixel-perfect, Adobe Illustrator-compatible EPS vector files (and SVG) with zero blur, sharp boundaries, 2D greedy meshing, and smart background optimization.

## Features

- **Pixel-Perfect Vectorization**: Sets `shape-rendering="crispEdges"` and proper `viewBox` coordinates so individual pixels are never blurred by anti-aliasing.
- **Adobe Illustrator-Compatible EPS Export**:
  - Generates standard Encapsulated PostScript (EPS Level 2, DSC 3.0 conforming).
  - Fully compliant with **Adobe Stock**, **Shutterstock**, and **Freepik** standards (sRGB by default, clean DSC headers, optional CMYK for print).
  - All shapes open as clean, editable vector paths arranged on an artboard matching `%%BoundingBox`.
  - Can convert **directly from PNG** or **from an existing SVG**.
  - Can export both `.eps` and `.svg` in a single run (`--both`).
- **Conversion Strategies**:
  - **Pixel Mapping (`--pixel`, default)**: Direct 1:1 mapping where each pixel is preserved as an individual separate square (unmerged).
  - **Greedy Meshing (`--greedy`)**: 2D rectangular decomposition that merges adjacent matching pixels into maximal rectangles, drastically reducing DOM/path node count and file size by 70–90%.
  - **Run-Length Encoding (`--rle`)**: Merges contiguous horizontal pixels of identical color into 1-row-high rects.
- **Background Recognition & Canvas Optimization (Default: Enabled)**:
  - Automatically identifies solid backgrounds by strictly verifying that **100% of all perimeter pixels along all 4 outer edges** share the exact same color (can be disabled with `--no-bg-detect`).
  - Removes all outer background pixels and replaces them with a **single 1-item canvas rectangle** (`0 0 W H rectfill` in EPS, `<rect width="W" height="H"/>` in SVG).
  - Uses border-connected **flood filling** (`--bg-scope flood`) by default so interior pixels of the same color (e.g. character eyes, teeth, gloves) are never erased.
  - Option to make solid background transparent (`--transparent-bg`).
- **Vector Canvas Sizing (EPS & SVG)**:
  - **Auto Stock Sizing (Default)**: Automatically targets the universal **15–25 Megapixel sweet spot** (~16 MP), satisfying both Adobe Stock ($\ge 15\text{ MP}$) and Shutterstock ($4\text{--}25\text{ MP}$) with exact integer pixel scaling.
  - Smaller side scaling (`--canvas-min-side <N>` or `--min-side <N>`): Sets the shorter side of the vector canvas in points (e.g. 4000).
  - Larger side scaling (`--canvas-max-side <N>` or `--max-side <N>`): Sets the longer side of the vector canvas in points.
  - Scale multiplier (`-s <N>`, `--canvas-scale <N>`): Multiplies vector canvas dimensions by $N$.
  - Target dimension (`--size <WxH>`): Explicit canvas size, e.g. '4000x3000'.
  - 1:1 original dimensions (`--original-size` or `--no-stock`).
- **Preview JPEG Export Options**:
  - Companion JPEG export (`--preview` or `--jpg`): Generates `<name>.jpg` preview alongside the vector file.
  - Preview minimum side (`--preview-min-side <N>`, default `6000`): Sets the shortest side for the preview image.
  - Preview maximum side (`--preview-max-side <N>`): Sets the longest side for the preview image.
  - Preview quality (`--preview-quality <N>`, default `95`): High-quality JPEG compression with 4:4:4 chroma subsampling (`subsampling=0`) for crisp pixel edges.
  - Grouped `<rect>` elements (`--element rect`, default).
  - Consolidated `<path>` per color (`--element path`).
- **Transparency Support**: Fully transparent pixels (`alpha == 0` or below `--alpha-threshold`) are omitted; translucent pixels retain proper `fill-opacity`.

## Installation

```bash
pip install -r requirements.txt
# or editable mode:
pip install -e .
```

Requires Python 3.8+ and Pillow (`pillow>=9.0.0`).

## Usage

### 1. Generating Illustrator-Compatible EPS (Default)

```bash
# Convert PNG directly to Illustrator EPS (EPS is the default format)
./png2eps.py sprite.png --min-side 6000

# Export SVG instead of EPS using the --svg flag
./png2eps.py sprite.png --svg

# Generate both EPS and SVG simultaneously
./png2eps.py sprite.png --both --min-side 6000 --bg-detect

# Export using CMYK for print
./png2eps.py sprite.png --cmyk

# Export using Illustrator polygon path syntax (moveto/lineto/closepath)
./png2eps.py sprite.png --eps-style path

# Convert an existing SVG to Illustrator EPS
./png2eps.py sprite.svg sprite.eps
```

### 2. Background Recognition & Optimization

```bash
# Auto-detect solid background, remove all its pixels, and replace with 1 canvas rect
./png2eps.py sprite_on_black.png --bg-detect

# Export to EPS with background detected and scaled 16x
./png2eps.py sample_heart.png sample_heart.eps --bg-detect -s 16

# Auto-detect solid background and make it completely transparent
./png2eps.py sprite_on_white.png --bg-detect --transparent-bg

# Manually specify background color
./png2eps.py sprite.png --bg "#ffffff"
```

### 3. Sizing & Stock Optimization

By default, `png2eps` automatically calculates the optimal canvas dimensions for microstock platforms (**15–25 Megapixels**, targeting ~16 MP). This simultaneously fulfills:
- **Adobe Stock**: Meets the recommended $\ge 15\text{ MP}$ threshold for sharp thumbnail previews (max 65 MP).
- **Shutterstock**: Strictly obeys the mandatory $4\text{ MP}$ minimum and $25\text{ MP}$ maximum bounding box limit.

```bash
# 1. Default: Auto-scales vector canvas to stock sweet spot (~16 MP)
./png2eps.py sprite.png --bg-detect

# 2. Generate EPS + companion high-res preview JPEG (default: 6000px on min side)
./png2eps.py sprite.png --bg-detect --preview

# 3. Explicit separation: canvas 4000pt on min side, preview 6000px on min side
./png2eps.py sprite.png --canvas-min-side 4000 --preview --preview-min-side 6000

# 4. Custom preview JPEG quality and max side
./png2eps.py sprite.png --preview --preview-quality 98 --preview-max-side 8000

# 5. Disable auto stock scaling to keep 1:1 original pixel dimensions
./png2eps.py sprite.png --original-size

# 6. Manual scale factor for vector canvas (e.g. 16x)
./png2eps.py sprite.png -s 16
```

### 4. Conversion Modes

```bash
# Strict 1:1 pixel mapping (1 rect per pixel, default - pixels are kept separate)
./png2eps.py input.png output.eps

# 2D greedy rectangle merging (smaller file size)
./png2eps.py input.png output.eps --greedy

# Horizontal run-length merging
./png2eps.py input.png output.eps --rle
```

### 5. SVG to EPS Conversion (`svg2eps`)

You can also convert existing SVG pixel art files to Illustrator-compatible EPS files and companion preview JPEGs using either `svg2eps.py` or `png2eps.py`:

```bash
# Convert SVG to stock-ready EPS (auto-scaled to 15-25 MP sweet spot):
./svg2eps.py icon.svg

# Convert SVG to EPS and generate high-res preview JPEG (default: 6000px):
./svg2eps.py icon.svg --preview

# Keep original 1:1 SVG artboard dimensions:
./svg2eps.py icon.svg --original-size

# Specify custom artboard dimensions and preview JPEG size:
./svg2eps.py icon.svg --canvas-min-side 4000 --preview --preview-min-side 6000

# You can also pass SVG directly to png2eps:
./png2eps.py icon.svg --preview
```

## Running Tests

```bash
python3 -m unittest discover tests
```
