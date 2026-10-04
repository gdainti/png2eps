#!/usr/bin/env python3
"""
png2eps: Convert pixel art PNG images to pixel-perfect SVG and Adobe Illustrator compatible EPS vector files.
"""

from collections import Counter, defaultdict, deque
import argparse
import datetime
import math
import os
import re
import sys
from typing import List, Tuple, Dict, Optional
import xml.etree.ElementTree as ET
from PIL import Image, ImageColor


def detect_solid_background(
    pixels,
    width: int,
    height: int,
    alpha_threshold: int = 0
) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect whether the image has a solid background.
    Strictly checks that 100% of all perimeter pixels around all 4 edges share the exact same color.
    Returns the RGBA tuple of the background color if detected, else None.
    """
    if width <= 0 or height <= 0:
        return None

    # Reference color from top-left corner
    bg_color = pixels[0, 0]

    # If the candidate color is transparent, there is no solid background to replace
    if bg_color[3] <= alpha_threshold:
        return None

    # Check 100% of top and bottom edges
    for x in range(width):
        if pixels[x, 0] != bg_color or pixels[x, height - 1] != bg_color:
            return None

    # Check 100% of left and right edges
    for y in range(1, height - 1):
        if pixels[0, y] != bg_color or pixels[width - 1, y] != bg_color:
            return None

    return bg_color


def compute_background_mask(
    pixels,
    width: int,
    height: int,
    bg_color: Tuple[int, int, int, int],
    scope: str = "flood"
) -> List[List[bool]]:
    """
    Returns 2D boolean mask where True means the pixel belongs to the background.
    - 'flood': Flood fills from image borders inwards. Only outer background connected to borders
               is marked, preserving interior sprite pixels of the same color (e.g. eyes, teeth).
    - 'all': Marks all pixels matching bg_color across the entire image.
    """
    mask = [[False] * width for _ in range(height)]

    if scope == "all":
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == bg_color:
                    mask[y][x] = True
        return mask

    # Flood fill (BFS) starting from all perimeter pixels matching bg_color
    queue = deque()
    for x in range(width):
        if pixels[x, 0] == bg_color and not mask[0][x]:
            mask[0][x] = True
            queue.append((x, 0))
        if pixels[x, height - 1] == bg_color and not mask[height - 1][x]:
            mask[height - 1][x] = True
            queue.append((x, height - 1))

    for y in range(1, height - 1):
        if pixels[0, y] == bg_color and not mask[y][0]:
            mask[y][0] = True
            queue.append((0, y))
        if pixels[width - 1, y] == bg_color and not mask[y][width - 1]:
            mask[y][width - 1] = True
            queue.append((width - 1, y))

    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < width and 0 <= ny < height and not mask[ny][nx]:
                if pixels[nx, ny] == bg_color:
                    mask[ny][nx] = True
                    queue.append((nx, ny))

    return mask


def parse_color_string(color_str: str) -> Tuple[int, int, int, int]:
    """Parse color string into (R, G, B, A). Supports hex #fff, #ffffff, #ffffffff, and named CSS colors."""
    color_str = color_str.strip()
    if color_str.startswith("#") and len(color_str) == 9:
        r = int(color_str[1:3], 16)
        g = int(color_str[3:5], 16)
        b = int(color_str[5:7], 16)
        a = int(color_str[7:9], 16)
        return (r, g, b, a)
    try:
        rgb = ImageColor.getrgb(color_str)
        if len(rgb) == 4:
            return rgb
        return (rgb[0], rgb[1], rgb[2], 255)
    except Exception as e:
        raise ValueError(f"Could not parse color '{color_str}': {e}")


def extract_pixels(
    pixels,
    width: int,
    height: int,
    alpha_threshold: int = 0,
    bg_mask: Optional[List[List[bool]]] = None
) -> List[Tuple[int, int, int, int, Tuple[int, int, int, int]]]:
    """
    Direct 1:1 pixel extraction: 1 square (1x1) per visible pixel.
    Returns list of (x, y, w, h, (r, g, b, a)).
    """
    rects = []
    for y in range(height):
        for x in range(width):
            if bg_mask and bg_mask[y][x]:
                continue
            color = pixels[x, y]
            if color[3] > alpha_threshold:
                rects.append((x, y, 1, 1, color))
    return rects


def extract_rle(
    pixels,
    width: int,
    height: int,
    alpha_threshold: int = 0,
    bg_mask: Optional[List[List[bool]]] = None
) -> List[Tuple[int, int, int, int, Tuple[int, int, int, int]]]:
    """
    1D Horizontal Run-Length Encoding.
    Merges adjacent horizontal pixels of identical color into 1-row-high rects.
    """
    rects = []
    for y in range(height):
        run_start = 0
        run_color = None
        run_length = 0

        for x in range(width):
            is_bg = (bg_mask and bg_mask[y][x])
            color = pixels[x, y]
            is_visible = (not is_bg) and (color[3] > alpha_threshold)

            if is_visible:
                if run_color == color:
                    run_length += 1
                else:
                    if run_color is not None:
                        rects.append((run_start, y, run_length, 1, run_color))
                    run_color = color
                    run_start = x
                    run_length = 1
            else:
                if run_color is not None:
                    rects.append((run_start, y, run_length, 1, run_color))
                    run_color = None
                    run_length = 0

        if run_color is not None:
            rects.append((run_start, y, run_length, 1, run_color))
    return rects


def extract_greedy(
    pixels,
    width: int,
    height: int,
    alpha_threshold: int = 0,
    bg_mask: Optional[List[List[bool]]] = None
) -> List[Tuple[int, int, int, int, Tuple[int, int, int, int]]]:
    """
    2D Greedy Rectangle Meshing.
    Merges adjacent horizontal and vertical blocks of the same color into
    the largest possible non-overlapping rectangular areas.
    """
    visited = [[False] * width for _ in range(height)]
    rects = []

    for y in range(height):
        for x in range(width):
            if visited[y][x]:
                continue
            if bg_mask and bg_mask[y][x]:
                visited[y][x] = True
                continue
            color = pixels[x, y]
            if color[3] <= alpha_threshold:
                visited[y][x] = True
                continue

            # 1. Expand horizontally as far as possible
            max_w = 0
            while x + max_w < width and not visited[y][x + max_w]:
                if (bg_mask and bg_mask[y][x + max_w]) or pixels[x + max_w, y] != color:
                    break
                max_w += 1

            # 2. Expand vertically while maintaining uniform width
            max_h = 1
            while y + max_h < height:
                row_match = True
                for rx in range(x, x + max_w):
                    if visited[y + max_h][rx] or (bg_mask and bg_mask[y + max_h][rx]) or pixels[rx, y + max_h] != color:
                        row_match = False
                        break
                if not row_match:
                    break
                max_h += 1

            # 3. Mark grid area as visited
            for dy in range(max_h):
                for dx in range(max_w):
                    visited[y + dy][x + dx] = True

            rects.append((x, y, max_w, max_h, color))
    return rects


def color_to_svg_attrs(color: Tuple[int, int, int, int]) -> Tuple[str, str]:
    """Convert (R, G, B, A) to hex color '#rrggbb' and optional fill-opacity attribute."""
    r, g, b, a = color
    hex_color = f"#{r:02x}{g:02x}{b:02x}"
    opacity = f' fill-opacity="{a / 255:.3f}"' if a < 255 else ""
    return hex_color, opacity


def generate_svg_rects(rects: List[Tuple[int, int, int, int, Tuple[int, int, int, int]]], group_by_color: bool = True) -> str:
    """Generate SVG using <rect> elements, optionally grouped by color."""
    if not group_by_color:
        lines = []
        for x, y, w, h, color in rects:
            fill, opacity = color_to_svg_attrs(color)
            lines.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"{opacity}/>')
        return "\n".join(lines)

    # Group by color
    color_groups = defaultdict(list)
    for x, y, w, h, color in rects:
        color_groups[color].append((x, y, w, h))

    lines = []
    for color, items in color_groups.items():
        fill, opacity = color_to_svg_attrs(color)
        lines.append(f'  <g fill="{fill}"{opacity}>')
        for x, y, w, h in items:
            lines.append(f'    <rect x="{x}" y="{y}" width="{w}" height="{h}"/>')
        lines.append('  </g>')
    return "\n".join(lines)


def generate_svg_paths(rects: List[Tuple[int, int, int, int, Tuple[int, int, int, int]]]) -> str:
    """
    Generate SVG using consolidated <path> elements per color.
    Each rectangle is encoded as M x y h w v h h -w Z.
    """
    color_groups = defaultdict(list)
    for x, y, w, h, color in rects:
        color_groups[color].append((x, y, w, h))

    lines = []
    for color, items in color_groups.items():
        fill, opacity = color_to_svg_attrs(color)
        path_segments = []
        for x, y, w, h in items:
            path_segments.append(f"M{x} {y}h{w}v{h}h{-w}z")
        d = " ".join(path_segments)
        lines.append(f'  <path fill="{fill}"{opacity} d="{d}"/>')
    return "\n".join(lines)


def rgb_to_cmyk(r: int, g: int, b: int) -> Tuple[float, float, float, float]:
    """Convert 0-255 RGB to 0.0-1.0 CMYK."""
    if r == 0 and g == 0 and b == 0:
        return 0.0, 0.0, 0.0, 1.0
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    k = 1.0 - max(rf, gf, bf)
    denom = 1.0 - k
    if denom <= 0:
        return 0.0, 0.0, 0.0, 1.0
    c = (1.0 - rf - k) / denom
    m = (1.0 - gf - k) / denom
    y = (1.0 - bf - k) / denom
    return round(c, 4), round(m, 4), round(y, 4), round(k, 4)


def generate_eps(
    rects: List[Tuple[int, int, int, int, Tuple[int, int, int, int]]],
    orig_w: int,
    orig_h: int,
    out_w: float,
    out_h: float,
    bg_color: Optional[Tuple[int, int, int, int]] = None,
    transparent_bg: bool = False,
    title: str = "pixelart",
    color_mode: str = "rgb",
    eps_style: str = "rect"
) -> str:
    """
    Generate an Adobe Illustrator-compatible EPS (Encapsulated PostScript DSC 3.0) file.
    Matches Adobe Illustrator CS6 / EPS 10 structure and conventions.
    """
    scale_x = out_w / orig_w
    scale_y = out_h / orig_h
    now_str = datetime.datetime.now().strftime("%m/%d/%Y")

    bb_w = int(round(out_w))
    bb_h = int(round(out_h))

    process_colors = "Cyan Magenta Yellow Black" if color_mode == "cmyk" else "RGB"

    header = [
        "%!PS-Adobe-3.1 EPSF-3.0",
        "%ADO_DSC_Encoding: Windows Roman",
        f"%%Title: {title}.eps",
        "%%Creator: Adobe Illustrator(R) 16.0",
        f"%%CreationDate: {now_str}",
        f"%%BoundingBox: 0 0 {bb_w} {bb_h}",
        f"%%HiResBoundingBox: 0 0 {out_w:.4f} {out_h:.4f}",
        f"%%CropBox: 0 0 {out_w:.4f} {out_h:.4f}",
        "%%LanguageLevel: 2",
        "%%DocumentData: Clean7Bit",
        '%ADOBeginClientInjection: DocumentHeader "AI11EPS"',
        "%%AI8_CreatorVersion: 16.0.0",
        "%%Pages: 1",
        f"%%DocumentProcessColors:  {process_colors}",
        "%%EndComments",
        "%%BeginProlog",
        "/c { setrgbcolor } bind def",
        "/k { setcmykcolor } bind def",
        "/r { rectfill } bind def",
        "/mo { moveto } bind def",
        "/li { lineto } bind def",
        "/cp { closepath } bind def",
        "/f { fill } bind def",
        "%%EndProlog",
        "%%BeginSetup",
        "%%EndSetup",
        "%%Page: 1 1",
        "%%BeginPageSetup",
        "%%EndPageSetup",
        "gsave"
    ]

    body = []

    def format_color(color_tuple):
        r, g, b, _ = color_tuple
        if color_mode == "cmyk":
            c, m, y, k = rgb_to_cmyk(r, g, b)
            return f"{c:.4f} {m:.4f} {y:.4f} {k:.4f} k"
        else:
            return f"{r/255:.4f} {g/255:.4f} {b/255:.4f} c"

    # 1. Background canvas rectangle (if present)
    if bg_color is not None and not transparent_bg:
        body.append("% --- Background Canvas ---")
        body.append(format_color(bg_color))
        if eps_style == "path":
            body.append(f"0 0 mo")
            body.append(f"{out_w:.2f} 0 li")
            body.append(f"{out_w:.2f} {out_h:.2f} li")
            body.append(f"0 {out_h:.2f} li")
            body.append("cp")
            body.append("f")
        else:
            body.append(f"0 0 {out_w:.2f} {out_h:.2f} r")

    # 2. Foreground rectangles grouped by color
    color_groups = defaultdict(list)
    for x, y, w, h, color in rects:
        color_groups[color].append((x, y, w, h))

    for color_key, items in color_groups.items():
        r, g, b, _ = color_key
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        body.append(f"% Layer: {hex_color}")
        body.append(format_color(color_key))

        for x, y, w, h in items:
            rx = x * scale_x
            ry = (orig_h - y - h) * scale_y
            rw = w * scale_x
            rh = h * scale_y
            if eps_style == "path":
                body.append(f"{rx:.2f} {ry:.2f} mo")
                body.append(f"{rx + rw:.2f} {ry:.2f} li")
                body.append(f"{rx + rw:.2f} {ry + rh:.2f} li")
                body.append(f"{rx:.2f} {ry + rh:.2f} li")
                body.append("cp")
                body.append("f")
            else:
                body.append(f"{rx:.2f} {ry:.2f} {rw:.2f} {rh:.2f} r")

    trailer = [
        "grestore",
        "showpage",
        "%%PageTrailer",
        "%%Trailer",
        "%%EOF"
    ]

    return "\n".join(header + body + trailer) + "\n"


def parse_svg_to_rects(svg_path: str):
    """
    Parse an existing SVG file created by png2eps or containing pixel art rects/paths.
    Returns (orig_w, orig_h, out_w, out_h, rects, bg_color).
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Parse viewBox
    viewbox = root.attrib.get("viewBox", "")
    if viewbox:
        vb_parts = [float(p) for p in re.split(r"[\s,]+", viewbox.strip())]
        orig_w, orig_h = vb_parts[2], vb_parts[3]
    else:
        orig_w = float(re.match(r"[\d\.]+", root.attrib.get("width", "100")).group(0))
        orig_h = float(re.match(r"[\d\.]+", root.attrib.get("height", "100")).group(0))

    # Parse display dimensions
    w_attr = root.attrib.get("width", str(orig_w))
    h_attr = root.attrib.get("height", str(orig_h))
    out_w = float(re.match(r"[\d\.]+", w_attr).group(0))
    out_h = float(re.match(r"[\d\.]+", h_attr).group(0))

    rects = []
    bg_color = None

    def walk(elem, parent_color):
        nonlocal bg_color
        color_attr = elem.attrib.get("fill", parent_color)
        tag = elem.tag.split("}")[-1]

        if tag == "rect":
            x = float(elem.attrib.get("x", 0))
            y = float(elem.attrib.get("y", 0))
            w = float(elem.attrib.get("width", 0))
            h = float(elem.attrib.get("height", 0))
            color = parse_color_string(color_attr) if color_attr and color_attr != "none" else None

            # Detect canvas background rectangle
            if x == 0 and y == 0 and w == orig_w and h == orig_h:
                bg_color = color
            else:
                if color:
                    rects.append((x, y, w, h, color))

        elif tag == "path":
            d = elem.attrib.get("d", "")
            color = parse_color_string(color_attr) if color_attr and color_attr != "none" else None
            if color:
                for m in re.finditer(r"M\s*([\d\.-]+)\s+([\d\.-]+)h([\d\.-]+)v([\d\.-]+)h(?:-?[\d\.-]+)z", d, re.I):
                    px, py, pw, ph = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
                    rects.append((px, py, pw, ph, color))

        for child in elem:
            walk(child, color_attr)

    walk(root, None)
    return orig_w, orig_h, out_w, out_h, rects, bg_color


def calculate_stock_dimensions(orig_w: int, orig_h: int, target_mp: float = 16.0) -> Tuple[int, int]:
    """
    Calculate canvas dimensions compliant with Adobe Stock (recommended min 15 MP, max 65 MP)
    and Shutterstock (required min 4 MP, max 25 MP).
    Targets ~16 MP by finding an optimal integer multiplier if possible.
    """
    area = orig_w * orig_h
    min_area = 15_000_000
    max_area = 25_000_000
    target_area = target_mp * 1_000_000

    if min_area <= area <= max_area:
        return orig_w, orig_h

    # Ideal continuous scale
    ideal_scale = math.sqrt(target_area / area)

    # Try candidate integer scales around ideal_scale to keep pixel art pixels cleanly aligned
    candidates = set()
    for s in (math.floor(ideal_scale), math.ceil(ideal_scale), round(ideal_scale)):
        if s > 0:
            candidates.add(s)

    # Prefer integer scale that lands strictly within [15 MP, 25 MP]
    valid_int_scales = [s for s in candidates if min_area <= (orig_w * s) * (orig_h * s) <= max_area]
    if valid_int_scales:
        best_s = min(valid_int_scales, key=lambda s: abs((orig_w * s) * (orig_h * s) - target_area))
        return orig_w * best_s, orig_h * best_s

    # If no integer lands in [15 MP, 25 MP], check if any lands in Shutterstock's [4 MP, 25 MP] range
    shutterstock_scales = [s for s in candidates if 4_000_000 <= (orig_w * s) * (orig_h * s) <= max_area]
    if shutterstock_scales:
        best_s = min(shutterstock_scales, key=lambda s: abs((orig_w * s) * (orig_h * s) - target_area))
        return orig_w * best_s, orig_h * best_s

    # Fallback to continuous float scale clamped to [15 MP, 25 MP]
    clamped_scale = min(max(ideal_scale, math.sqrt(min_area / area)), math.sqrt(max_area / area))
    return round(orig_w * clamped_scale), round(orig_h * clamped_scale)


def calculate_output_dimensions(
    orig_w: int,
    orig_h: int,
    scale: float = None,
    target_w: int = None,
    target_h: int = None,
    size_str: str = None,
    min_side: int = None,
    max_side: int = None,
    stock: bool = False
) -> Tuple[int, int]:
    """Calculate the final rendered width and height based on user options."""
    if min_side is not None:
        if min_side <= 0:
            raise ValueError(f"min_side must be greater than 0, got {min_side}")
        if orig_w <= orig_h:
            factor = min_side / orig_w
            return min_side, round(orig_h * factor)
        else:
            factor = min_side / orig_h
            return round(orig_w * factor), min_side

    if max_side is not None:
        if max_side <= 0:
            raise ValueError(f"max_side must be greater than 0, got {max_side}")
        if orig_w >= orig_h:
            factor = max_side / orig_w
            return max_side, round(orig_h * factor)
        else:
            factor = max_side / orig_h
            return round(orig_w * factor), max_side

    if size_str:
        match = re.match(r"^(\d+)(?:x(\d+))?$", size_str.strip().lower())
        if not match:
            raise ValueError(f"Invalid size format: '{size_str}'. Expected format like '512' or '512x512'.")
        w_part = int(match.group(1))
        h_part = int(match.group(2)) if match.group(2) else None
        if h_part is None:
            target_w = w_part
            target_h = round(w_part * orig_h / orig_w)
        else:
            target_w = w_part
            target_h = h_part
        return target_w, target_h

    if scale is not None:
        if scale <= 0:
            raise ValueError(f"Scale must be greater than 0, got {scale}")
        return round(orig_w * scale), round(orig_h * scale)

    if target_w is not None and target_h is not None:
        return target_w, target_h
    elif target_w is not None:
        return target_w, round(target_w * orig_h / orig_w)
    elif target_h is not None:
        return round(target_h * orig_w / orig_h), target_h

    if stock:
        return calculate_stock_dimensions(orig_w, orig_h)

    # Default: match pixel dimensions 1:1
    return orig_w, orig_h


def generate_preview_jpg(
    input_path: str,
    output_path: str,
    min_side: Optional[int] = 6000,
    max_side: Optional[int] = None,
    scale: Optional[float] = None,
    bg_color: Optional[Tuple[int, int, int, int]] = None,
    transparent_bg: bool = False,
    quality: int = 95
) -> dict:
    """
    Generate high-resolution preview JPEG using nearest-neighbor scaling
    to preserve razor-sharp pixel art edges without anti-aliasing artifacts.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with Image.open(input_path) as img:
        img = img.convert("RGBA")
        width, height = img.size

        out_w, out_h = calculate_output_dimensions(
            width, height, scale=scale, min_side=min_side, max_side=max_side
        )

        # Nearest-neighbor resize for razor-sharp pixel edges
        resized = img.resize((out_w, out_h), resample=Image.Resampling.NEAREST)

        # JPEG requires RGB. Determine canvas background color.
        if bg_color is not None and not transparent_bg:
            bg_rgb = bg_color[:3]
        else:
            bg_rgb = (255, 255, 255)  # Clean white background for transparent vectors

        canvas = Image.new("RGB", (out_w, out_h), bg_rgb)
        alpha = resized.split()[3]
        canvas.paste(resized, (0, 0), mask=alpha)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        # subsampling=0 (4:4:4) disables chroma subsampling so pixel boundaries don't bleed color
        canvas.save(output_path, "JPEG", quality=quality, subsampling=0)

    file_size = os.path.getsize(output_path)
    return {
        "input_size": (width, height),
        "output_size": (out_w, out_h),
        "megapixels": (out_w * out_h) / 1_000_000,
        "file_size": file_size,
        "output_path": output_path
    }


def convert_png_to_svg(
    input_path: str,
    output_path: str,
    mode: str = "pixel",
    element_type: str = "rect",
    scale: float = None,
    target_w: int = None,
    target_h: int = None,
    size_str: str = None,
    min_side: int = None,
    max_side: int = None,
    stock: bool = False,
    crisp: bool = True,
    alpha_threshold: int = 0,
    group_by_color: bool = True,
    bg: Optional[str] = None,
    bg_detect: bool = True,
    bg_scope: str = "flood",
    transparent_bg: bool = False
) -> dict:
    """
    Main PNG to SVG conversion logic.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with Image.open(input_path) as img:
        img = img.convert("RGBA")
        width, height = img.size
        pixels = img.load()

    # Size selection
    out_w, out_h = calculate_output_dimensions(
        width, height, scale=scale, target_w=target_w, target_h=target_h, size_str=size_str,
        min_side=min_side, max_side=max_side, stock=stock
    )

    # Background detection / handling
    bg_color = None
    bg_mask = None
    bg_pixels_removed = 0

    if bg_detect or (bg and bg.lower() == "auto"):
        bg_color = detect_solid_background(pixels, width, height, alpha_threshold=alpha_threshold)
    elif bg and bg.lower() not in ("none", "false"):
        bg_color = parse_color_string(bg)

    if bg_color is not None:
        bg_mask = compute_background_mask(pixels, width, height, bg_color, scope=bg_scope)
        bg_pixels_removed = sum(sum(row) for row in bg_mask)

    # Strategy selection
    if mode in ("pixel", "direct"):
        rects = extract_pixels(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    elif mode in ("rle", "runlength"):
        rects = extract_rle(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    elif mode == "greedy":
        rects = extract_greedy(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    else:
        raise ValueError(f"Unknown mode: {mode}. Choose from 'greedy', 'rle', 'pixel'.")

    # Generate XML body
    if element_type == "path":
        body = generate_svg_paths(rects)
    else:
        body = generate_svg_rects(rects, group_by_color=group_by_color)

    # Background element (1 big canvas rectangle)
    bg_element = ""
    if bg_color is not None and not transparent_bg:
        bg_hex, bg_op = color_to_svg_attrs(bg_color)
        bg_element = f'  <rect width="{width}" height="{height}" fill="{bg_hex}"{bg_op}/>'

    elements_list = []
    if bg_element:
        elements_list.append(bg_element)
    if body:
        elements_list.append(body)
    svg_body = "\n".join(elements_list)

    crisp_attr = ' shape-rendering="crispEdges"' if crisp else ""
    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{out_w}" height="{out_h}"{crisp_attr}>
{svg_body}
</svg>
'''

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    total_element_count = len(rects) + (1 if bg_element else 0)

    return {
        "input_size": (width, height),
        "output_size": (out_w, out_h),
        "total_pixels": width * height,
        "rects_count": total_element_count,
        "foreground_rects_count": len(rects),
        "rects": rects,
        "bg_detected": bg_color is not None,
        "bg_color": bg_color,
        "bg_pixels_removed": bg_pixels_removed,
        "bg_scope": bg_scope,
        "transparent_bg": transparent_bg,
        "svg_file_size": len(svg_content.encode("utf-8")),
    }


def convert_png_or_svg_to_eps(
    input_path: str,
    output_path: str,
    mode: str = "pixel",
    scale: float = None,
    target_w: int = None,
    target_h: int = None,
    size_str: str = None,
    min_side: int = None,
    max_side: int = None,
    stock: bool = False,
    alpha_threshold: int = 0,
    bg: Optional[str] = None,
    bg_detect: bool = True,
    bg_scope: str = "flood",
    transparent_bg: bool = False,
    color_mode: str = "rgb",
    eps_style: str = "rect"
) -> dict:
    """
    Convert PNG or existing SVG directly into an Adobe Illustrator-compatible EPS file.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    title = os.path.splitext(os.path.basename(output_path))[0]

    # If input is already an SVG
    if input_path.lower().endswith(".svg"):
        orig_w, orig_h, cur_out_w, cur_out_h, rects, bg_color = parse_svg_to_rects(input_path)
        # Apply scaling if requested, else use SVG's out dimensions
        if scale or target_w or target_h or size_str or min_side or max_side or stock:
            out_w, out_h = calculate_output_dimensions(
                orig_w, orig_h, scale=scale, target_w=target_w, target_h=target_h, size_str=size_str,
                min_side=min_side, max_side=max_side, stock=stock
            )
        else:
            out_w, out_h = cur_out_w, cur_out_h

        eps_content = generate_eps(
            rects=rects,
            orig_w=orig_w,
            orig_h=orig_h,
            out_w=out_w,
            out_h=out_h,
            bg_color=bg_color,
            transparent_bg=transparent_bg,
            title=title,
            color_mode=color_mode,
            eps_style=eps_style
        )
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(eps_content)

        return {
            "input_size": (orig_w, orig_h),
            "output_size": (out_w, out_h),
            "rects_count": len(rects) + (1 if bg_color and not transparent_bg else 0),
            "bg_color": bg_color,
            "color_mode": color_mode,
            "eps_style": eps_style,
            "eps_file_size": len(eps_content.encode("utf-8")),
        }

    # Input is PNG
    with Image.open(input_path) as img:
        img = img.convert("RGBA")
        width, height = img.size
        pixels = img.load()

    out_w, out_h = calculate_output_dimensions(
        width, height, scale=scale, target_w=target_w, target_h=target_h, size_str=size_str,
        min_side=min_side, max_side=max_side, stock=stock
    )

    bg_color = None
    bg_mask = None
    bg_pixels_removed = 0

    if bg_detect or (bg and bg.lower() == "auto"):
        bg_color = detect_solid_background(pixels, width, height, alpha_threshold=alpha_threshold)
    elif bg and bg.lower() not in ("none", "false"):
        bg_color = parse_color_string(bg)

    if bg_color is not None:
        bg_mask = compute_background_mask(pixels, width, height, bg_color, scope=bg_scope)
        bg_pixels_removed = sum(sum(row) for row in bg_mask)

    if mode in ("pixel", "direct"):
        rects = extract_pixels(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    elif mode in ("rle", "runlength"):
        rects = extract_rle(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    elif mode == "greedy":
        rects = extract_greedy(pixels, width, height, alpha_threshold=alpha_threshold, bg_mask=bg_mask)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    eps_content = generate_eps(
        rects=rects,
        orig_w=width,
        orig_h=height,
        out_w=out_w,
        out_h=out_h,
        bg_color=bg_color,
        transparent_bg=transparent_bg,
        title=title,
        color_mode=color_mode,
        eps_style=eps_style
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(eps_content)

    return {
        "input_size": (width, height),
        "output_size": (out_w, out_h),
        "total_pixels": width * height,
        "rects_count": len(rects) + (1 if bg_color and not transparent_bg else 0),
        "bg_detected": bg_color is not None,
        "bg_color": bg_color,
        "bg_pixels_removed": bg_pixels_removed,
        "bg_scope": bg_scope,
        "transparent_bg": transparent_bg,
        "eps_file_size": len(eps_content.encode("utf-8")),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert pixel art PNG images to pixel-perfect SVG and Illustrator-compatible EPS files."
    )
    parser.add_argument("input", help="Path to input PNG or SVG file")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path to output EPS or SVG file (defaults to input filename with .eps extension, or .svg if --svg is set)"
    )

    # Output format
    fmt_group = parser.add_argument_group("Output Format Options")
    fmt_group.add_argument(
        "-f", "--format",
        choices=["eps", "svg", "both"],
        default=None,
        help="Output vector format: 'eps' (default, Illustrator-compatible), 'svg', or 'both'"
    )
    fmt_group.add_argument(
        "--svg",
        action="store_true",
        default=False,
        help="Generate SVG file instead of EPS"
    )
    fmt_group.add_argument(
        "--eps",
        action="store_true",
        default=False,
        help="Generate Illustrator-compatible EPS file (default)"
    )
    fmt_group.add_argument(
        "--both",
        action="store_true",
        default=False,
        help="Generate both EPS and SVG files simultaneously"
    )

    # Mode / Strategy
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-m", "--mode",
        choices=["pixel", "greedy", "rle"],
        default="pixel",
        help="Conversion strategy: 'pixel' (1x1 square per pixel, default), 'greedy' (2D meshing), 'rle' (horizontal run-length)"
    )
    mode_group.add_argument(
        "--pixel",
        dest="mode",
        action="store_const",
        const="pixel",
        help="Direct 1:1 pixel mapping (every pixel is an individual 1x1 square, default)"
    )
    mode_group.add_argument(
        "--greedy",
        dest="mode",
        action="store_const",
        const="greedy",
        help="Use 2D greedy rectangle merging"
    )
    mode_group.add_argument(
        "--rle",
        dest="mode",
        action="store_const",
        const="rle",
        help="Use 1D horizontal run-length merging"
    )

    # Vector Canvas sizing options (EPS & SVG)
    canvas_group = parser.add_argument_group("Vector Canvas Sizing Options (EPS & SVG)")
    canvas_group.add_argument(
        "--canvas-min-side", "--min-side", "--short-side",
        dest="min_side",
        type=int,
        default=None,
        help="Set exact size of smaller/shorter side of vector canvas in points (e.g. 4000)"
    )
    canvas_group.add_argument(
        "--canvas-max-side", "--max-side", "--long-side",
        dest="max_side",
        type=int,
        default=None,
        help="Set exact size of larger/longer side of vector canvas in points"
    )
    canvas_group.add_argument(
        "-s", "--scale", "--canvas-scale",
        dest="scale",
        type=float,
        default=None,
        help="Scale multiplier for vector canvas (e.g. 10 produces 10x display size)"
    )
    canvas_group.add_argument(
        "--size", "--canvas-size",
        dest="size",
        type=str,
        default=None,
        help="Target vector canvas dimensions, e.g. '4000' or '4800x3200'"
    )
    canvas_group.add_argument(
        "-W", "--width", "--canvas-width",
        dest="width",
        type=int,
        default=None,
        help="Explicit vector canvas width (height auto-calculated to maintain aspect ratio)"
    )
    canvas_group.add_argument(
        "-H", "--height", "--canvas-height",
        dest="height",
        type=int,
        default=None,
        help="Explicit vector canvas height (width auto-calculated to maintain aspect ratio)"
    )
    canvas_group.add_argument(
        "--stock",
        action="store_true",
        default=True,
        help="Auto-scale vector canvas to microstock sweet spot (15-25 MP, targeting ~16 MP compliant with Shutterstock & Adobe Stock, default)"
    )
    canvas_group.add_argument(
        "--original-size", "--no-stock",
        dest="stock",
        action="store_false",
        help="Disable auto stock scaling and keep 1:1 original pixel dimensions for vector canvas"
    )

    # Preview JPEG options
    preview_group = parser.add_argument_group("Preview JPEG Options")
    preview_group.add_argument(
        "--preview", "--jpg",
        dest="preview",
        action="store_true",
        default=False,
        help="Generate companion high-resolution preview JPEG (<name>.jpg)"
    )
    preview_group.add_argument(
        "--preview-min-side",
        type=int,
        default=6000,
        help="Minimum side dimension for preview JPEG in pixels (default: 6000)"
    )
    preview_group.add_argument(
        "--preview-max-side",
        type=int,
        default=None,
        help="Maximum side dimension for preview JPEG in pixels"
    )
    preview_group.add_argument(
        "--preview-scale",
        type=float,
        default=None,
        help="Scale multiplier specifically for preview JPEG"
    )
    preview_group.add_argument(
        "--preview-quality",
        type=int,
        default=95,
        help="JPEG quality for the preview image (1-100, default: 95)"
    )

    # Background detection & optimization
    bg_group = parser.add_argument_group("Background Options")
    bg_group.add_argument(
        "--bg-detect",
        dest="bg_detect",
        action="store_true",
        default=True,
        help="Auto-detect solid background (when 100% of border pixels match) and replace with 1 canvas <rect> (default: enabled)"
    )
    bg_group.add_argument(
        "--no-bg-detect",
        dest="bg_detect",
        action="store_false",
        help="Disable automatic background detection and keep all background pixels as individual shapes"
    )
    bg_group.add_argument(
        "--bg",
        type=str,
        default=None,
        help="Specify background: 'auto' (detect), or explicit color '#ffffff', 'black', etc."
    )
    bg_group.add_argument(
        "--bg-scope",
        choices=["flood", "all"],
        default="flood",
        help="'flood' (default): only remove outer border-connected background; 'all': remove all pixels matching color"
    )
    bg_group.add_argument(
        "--transparent-bg",
        action="store_true",
        default=False,
        help="Remove detected/specified background completely without adding a canvas rect (transparent)"
    )

    # Element representation
    elem_group = parser.add_argument_group("SVG Styling Options")
    elem_group.add_argument(
        "--element",
        choices=["rect", "path"],
        default="rect",
        help="SVG element format: 'rect' (<rect> elements) or 'path' (single compound <path> per color)"
    )
    elem_group.add_argument(
        "--no-group",
        dest="group_by_color",
        action="store_false",
        default=True,
        help="Do not group <rect> elements by color in <g fill='...'>"
    )
    elem_group.add_argument(
        "--no-crisp",
        dest="crisp",
        action="store_false",
        default=True,
        help="Disable shape-rendering='crispEdges'"
    )
    elem_group.add_argument(
        "--alpha-threshold",
        type=int,
        default=0,
        help="Alpha threshold (0-255) below which pixels are treated as transparent (default: 0)"
    )

    # EPS options
    eps_opts = parser.add_argument_group("EPS Format Options")
    eps_opts.add_argument(
        "--color-mode",
        choices=["rgb", "cmyk"],
        default="rgb",
        help="Color model for EPS output: 'rgb' (default, required by Adobe Stock & Shutterstock) or 'cmyk'"
    )
    eps_opts.add_argument(
        "--rgb",
        dest="color_mode",
        action="store_const",
        const="rgb",
        help="Use RGB color space for EPS (default, required by stock sites)"
    )
    eps_opts.add_argument(
        "--cmyk",
        dest="color_mode",
        action="store_const",
        const="cmyk",
        help="Use CMYK color space for EPS (optional for print)"
    )
    eps_opts.add_argument(
        "--eps-style",
        choices=["rect", "path"],
        default="rect",
        help="EPS shape format: 'rect' (PostScript Level 2 rectfill, compact, default) or 'path' (Illustrator mo/li/cp/f polygons)"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    input_file = args.input
    base, in_ext = os.path.splitext(input_file)
    in_ext = in_ext.lower()

    # Determine desired format(s)
    fmt = args.format
    if args.both:
        fmt = "both"
    elif args.svg:
        fmt = "svg"
    elif args.eps:
        fmt = "eps"

    if fmt is None:
        if args.output:
            out_ext = os.path.splitext(args.output)[1].lower()
            if out_ext == ".svg":
                fmt = "svg"
            else:
                fmt = "eps"
        else:
            fmt = "eps"

    try:
        # Determine target file paths
        if fmt == "both":
            out_base = os.path.splitext(args.output)[0] if args.output else base
            svg_file = f"{out_base}.svg"
            eps_file = f"{out_base}.eps"
        elif fmt == "svg":
            svg_file = args.output if args.output else f"{base}.svg"
            eps_file = None
        else:
            eps_file = args.output if args.output else f"{base}.eps"
            svg_file = None

        # Determine whether default stock scaling should be applied to the vector canvas
        has_custom_canvas_size = any([
            args.scale is not None,
            args.width is not None,
            args.height is not None,
            args.size is not None,
            args.min_side is not None,
            args.max_side is not None
        ])
        use_stock_canvas = args.stock and not has_custom_canvas_size

        stats_svg = None
        stats_eps = None

        # Execute conversions
        if svg_file and in_ext != ".svg":
            stats_svg = convert_png_to_svg(
                input_path=input_file,
                output_path=svg_file,
                mode=args.mode,
                element_type=args.element,
                scale=args.scale,
                target_w=args.width,
                target_h=args.height,
                size_str=args.size,
                min_side=args.min_side,
                max_side=args.max_side,
                stock=use_stock_canvas,
                crisp=args.crisp,
                alpha_threshold=args.alpha_threshold,
                group_by_color=args.group_by_color,
                bg=args.bg,
                bg_detect=args.bg_detect,
                bg_scope=args.bg_scope,
                transparent_bg=args.transparent_bg
            )
            in_w, in_h = stats_svg["input_size"]
            out_w, out_h = stats_svg["output_size"]
            mp = (out_w * out_h) / 1_000_000
            print(f"Successfully generated SVG: {svg_file}")
            print(f"  Canvas: {in_w}x{in_h} -> {out_w}x{out_h} points ({mp:.2f} MP)")
            if stats_svg["bg_detected"]:
                bg_hex, _ = color_to_svg_attrs(stats_svg["bg_color"])
                action = "made transparent" if stats_svg["transparent_bg"] else "replaced by 1 canvas rect"
                print(f"  Background: detected {bg_hex} ({stats_svg['bg_pixels_removed']} pixels {action})")
            print(f"  Elements: {stats_svg['rects_count']} {args.element}(s) ({stats_svg['svg_file_size'] / 1024:.2f} KB)")

        if eps_file:
            stats_eps = convert_png_or_svg_to_eps(
                input_path=input_file,
                output_path=eps_file,
                mode=args.mode,
                scale=args.scale,
                target_w=args.width,
                target_h=args.height,
                size_str=args.size,
                min_side=args.min_side,
                max_side=args.max_side,
                stock=use_stock_canvas,
                alpha_threshold=args.alpha_threshold,
                bg=args.bg,
                bg_detect=args.bg_detect,
                bg_scope=args.bg_scope,
                transparent_bg=args.transparent_bg,
                color_mode=args.color_mode,
                eps_style=args.eps_style
            )
            in_w, in_h = stats_eps["input_size"]
            out_w, out_h = stats_eps["output_size"]
            mp = (out_w * out_h) / 1_000_000
            print(f"Successfully generated EPS (Illustrator-compatible): {eps_file}")
            print(f"  BoundingBox: 0 0 {int(round(out_w))} {int(round(out_h))} ({mp:.2f} MP)")
            if stats_eps["bg_detected"]:
                bg_hex, _ = color_to_svg_attrs(stats_eps["bg_color"])
                action = "made transparent" if stats_eps["transparent_bg"] else "replaced by 1 canvas rect"
                print(f"  Background: detected {bg_hex} ({stats_eps['bg_pixels_removed']} pixels {action})")
            print(f"  Vector paths: {stats_eps['rects_count']} objects ({stats_eps['eps_file_size'] / 1024:.2f} KB)")

        # Generate companion preview JPEG if requested
        if args.preview and in_ext == ".png":
            preview_file = f"{base}.jpg"
            bg_col = None
            trans_bg = args.transparent_bg
            if stats_eps:
                bg_col = stats_eps.get("bg_color")
                trans_bg = stats_eps.get("transparent_bg", False)
            elif stats_svg:
                bg_col = stats_svg.get("bg_color")
                trans_bg = stats_svg.get("transparent_bg", False)
            elif args.bg and args.bg.lower() not in ("none", "false", "auto"):
                bg_col = parse_color_string(args.bg)

            stats_preview = generate_preview_jpg(
                input_path=input_file,
                output_path=preview_file,
                min_side=args.preview_min_side,
                max_side=args.preview_max_side,
                scale=args.preview_scale,
                bg_color=bg_col,
                transparent_bg=trans_bg,
                quality=args.preview_quality
            )
            p_w, p_h = stats_preview["output_size"]
            print(f"Successfully generated Preview JPEG: {preview_file}")
            print(f"  Dimensions: {p_w}x{p_h} ({stats_preview['megapixels']:.2f} MP, {stats_preview['file_size'] / 1024:.2f} KB)")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
