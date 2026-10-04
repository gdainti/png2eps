#!/usr/bin/env python3
"""
svg2eps: Convert pixel art SVG vector files to Adobe Illustrator-compatible EPS files
and high-resolution companion preview JPEGs (optimized for microstock platforms like Adobe Stock & Shutterstock).
"""

import argparse
import os
import sys
from typing import Optional

from png2eps import (
    convert_png_or_svg_to_eps,
    generate_preview_jpg,
    color_to_svg_attrs,
    parse_color_string
)


def convert_svg_to_eps(
    input_path: str,
    output_path: str,
    scale: Optional[float] = None,
    target_w: Optional[int] = None,
    target_h: Optional[int] = None,
    size_str: Optional[str] = None,
    min_side: Optional[int] = None,
    max_side: Optional[int] = None,
    stock: bool = True,
    transparent_bg: bool = False,
    bg: Optional[str] = None,
    color_mode: str = "rgb",
    eps_style: str = "rect"
) -> dict:
    """
    Convert an SVG file to an Adobe Illustrator-compatible EPS file.
    By default (stock=True), auto-scales the vector artboard to the 15-25 MP sweet spot.
    """
    return convert_png_or_svg_to_eps(
        input_path=input_path,
        output_path=output_path,
        scale=scale,
        target_w=target_w,
        target_h=target_h,
        size_str=size_str,
        min_side=min_side,
        max_side=max_side,
        stock=stock,
        transparent_bg=transparent_bg,
        bg=bg,
        color_mode=color_mode,
        eps_style=eps_style
    )


def parse_args():
    parser = argparse.ArgumentParser(
        prog="svg2eps",
        description="Convert pixel art SVG vector files to Illustrator-compatible EPS files and preview JPEGs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert SVG to EPS with default stock artboard sizing (15-25 MP sweet spot):
  svg2eps icon.svg

  # Convert SVG to EPS and generate companion high-res preview JPEG:
  svg2eps icon.svg --preview

  # Keep original 1:1 SVG dimensions without microstock auto-scaling:
  svg2eps icon.svg --original-size

  # Specify shorter side of artboard in points:
  svg2eps icon.svg --min-side 4000
        """
    )

    parser.add_argument("input", help="Path to input SVG file")
    parser.add_argument("output", nargs="?", default=None, help="Path to output EPS file (default: <input_base>.eps)")

    # Vector Canvas sizing options
    canvas_group = parser.add_argument_group("Vector Canvas Sizing Options (EPS)")
    canvas_group.add_argument(
        "--canvas-min-side", "--min-side", "--short-side",
        dest="min_side",
        type=int,
        default=None,
        help="Set size of smaller/shorter side of EPS canvas in points (e.g. 4000)"
    )
    canvas_group.add_argument(
        "--canvas-max-side", "--max-side", "--long-side",
        dest="max_side",
        type=int,
        default=None,
        help="Set size of larger/longer side of EPS canvas in points"
    )
    canvas_group.add_argument(
        "-s", "--scale", "--canvas-scale",
        dest="scale",
        type=float,
        default=None,
        help="Scale multiplier for EPS canvas (e.g. 10 produces 10x artboard dimensions)"
    )
    canvas_group.add_argument(
        "--size", "--canvas-size",
        dest="size",
        type=str,
        default=None,
        help="Target EPS canvas dimensions, e.g. '4000' or '4800x3200'"
    )
    canvas_group.add_argument(
        "-W", "--width", "--canvas-width",
        dest="width",
        type=int,
        default=None,
        help="Explicit EPS canvas width (height auto-calculated to maintain aspect ratio)"
    )
    canvas_group.add_argument(
        "-H", "--height", "--canvas-height",
        dest="height",
        type=int,
        default=None,
        help="Explicit EPS canvas height (width auto-calculated to maintain aspect ratio)"
    )
    canvas_group.add_argument(
        "--stock",
        action="store_true",
        default=True,
        help="Auto-scale EPS artboard to microstock sweet spot (15-25 MP, default: enabled)"
    )
    canvas_group.add_argument(
        "--original-size", "--no-stock",
        dest="stock",
        action="store_false",
        help="Disable auto stock scaling and keep original SVG dimensions"
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

    # Background options
    bg_group = parser.add_argument_group("Background Options")
    bg_group.add_argument(
        "--bg",
        type=str,
        default=None,
        help="Specify/override background color: '#ffffff', 'black', etc."
    )
    bg_group.add_argument(
        "--transparent-bg",
        action="store_true",
        default=False,
        help="Omit background canvas rect from EPS (transparent)"
    )

    # EPS Format Options
    eps_group = parser.add_argument_group("EPS Format Options")
    eps_group.add_argument(
        "--color-mode",
        choices=["rgb", "cmyk"],
        default="rgb",
        help="Color model for EPS output: 'rgb' (default, required by stock sites) or 'cmyk'"
    )
    eps_group.add_argument(
        "--rgb",
        dest="color_mode",
        action="store_const",
        const="rgb",
        help="Use RGB color space for EPS (default)"
    )
    eps_group.add_argument(
        "--cmyk",
        dest="color_mode",
        action="store_const",
        const="cmyk",
        help="Use CMYK color space for EPS (print)"
    )
    eps_group.add_argument(
        "--eps-style",
        choices=["rect", "path"],
        default="rect",
        help="EPS shape representation: 'rect' (DSC rectfill, default) or 'path' (moveto/lineto polygon)"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    input_file = args.input
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)

    base = os.path.splitext(input_file)[0]
    eps_file = args.output if args.output else f"{base}.eps"

    has_custom_canvas_size = any([
        args.scale is not None,
        args.width is not None,
        args.height is not None,
        args.size is not None,
        args.min_side is not None,
        args.max_side is not None
    ])
    use_stock_canvas = args.stock and not has_custom_canvas_size

    try:
        stats_eps = convert_svg_to_eps(
            input_path=input_file,
            output_path=eps_file,
            scale=args.scale,
            target_w=args.width,
            target_h=args.height,
            size_str=args.size,
            min_side=args.min_side,
            max_side=args.max_side,
            stock=use_stock_canvas,
            transparent_bg=args.transparent_bg,
            bg=args.bg,
            color_mode=args.color_mode,
            eps_style=args.eps_style
        )

        in_w, in_h = stats_eps["input_size"]
        out_w, out_h = stats_eps["output_size"]
        mp = (out_w * out_h) / 1_000_000

        print(f"Successfully generated EPS (Illustrator-compatible): {eps_file}")
        print(f"  BoundingBox: 0 0 {int(round(out_w))} {int(round(out_h))} ({mp:.2f} MP)")
        if stats_eps.get("bg_detected"):
            bg_hex, _ = color_to_svg_attrs(stats_eps["bg_color"])
            action = "made transparent" if stats_eps.get("transparent_bg") else "preserved as 1 canvas rect"
            print(f"  Background: detected {bg_hex} ({action})")
        print(f"  Vector paths: {stats_eps['rects_count']} objects ({stats_eps['eps_file_size'] / 1024:.2f} KB)")

        if args.preview:
            preview_file = f"{base}.jpg"
            bg_col = stats_eps.get("bg_color")
            trans_bg = stats_eps.get("transparent_bg", False)
            if args.bg and args.bg.lower() not in ("none", "false", "auto"):
                bg_col = parse_color_string(args.bg)

            stats_preview = generate_preview_jpg(
                input_path=input_file,
                output_path=preview_file,
                min_side=args.preview_min_side,
                max_side=args.preview_max_side,
                scale=args.preview_scale,
                bg_color=bg_col,
                transparent_bg=trans_bg,
                quality=args.preview_quality,
                rects=stats_eps.get("rects"),
                orig_size=stats_eps.get("orig_size")
            )
            p_w, p_h = stats_preview["output_size"]
            print(f"Successfully generated Preview JPEG: {preview_file}")
            print(f"  Dimensions: {p_w}x{p_h} ({stats_preview['megapixels']:.2f} MP, {stats_preview['file_size'] / 1024:.2f} KB)")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
