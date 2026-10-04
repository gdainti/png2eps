import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

from png2eps import (
    convert_png_to_svg, convert_png_or_svg_to_eps,
    calculate_output_dimensions, calculate_stock_dimensions,
    detect_solid_background, generate_preview_jpg
)


class TestPng2Eps(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.png_path = os.path.join(self.temp_dir.name, "test.png")

        # Create a 16x16 test pixel art image
        # Background: transparent
        # A 4x4 red square at (2, 2)
        # A 6x2 green bar at (8, 4)
        # A 1x1 blue pixel at (0, 0)
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.point([0, 0], fill=(0, 0, 255, 255))
        draw.rectangle([2, 2, 5, 5], fill=(255, 0, 0, 255))
        draw.rectangle([8, 4, 13, 5], fill=(0, 255, 0, 255))
        img.save(self.png_path)

        # Create a second image with solid white background
        # and a red character with white specular eye inside
        self.solid_bg_png = os.path.join(self.temp_dir.name, "solid_bg.png")
        img_solid = Image.new("RGBA", (16, 16), (255, 255, 255, 255))
        draw_solid = ImageDraw.Draw(img_solid)
        draw_solid.rectangle([4, 4, 11, 11], fill=(255, 0, 0, 255))
        draw_solid.point([6, 6], fill=(255, 255, 255, 255))  # internal white detail
        img_solid.save(self.solid_bg_png)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dimensions_calculation(self):
        # Default 1:1
        self.assertEqual(calculate_output_dimensions(16, 32), (16, 32))
        # Scale
        self.assertEqual(calculate_output_dimensions(16, 32, scale=2.5), (40, 80))
        # Explicit width (aspect ratio kept)
        self.assertEqual(calculate_output_dimensions(16, 32, target_w=64), (64, 128))
        # Explicit height (aspect ratio kept)
        self.assertEqual(calculate_output_dimensions(16, 32, target_h=16), (8, 16))
        # Size string '256x128'
        self.assertEqual(calculate_output_dimensions(16, 32, size_str="256x128"), (256, 128))
        # Size string single '128' (aspect ratio kept)
        self.assertEqual(calculate_output_dimensions(16, 32, size_str="64"), (64, 128))
        # Min side: 16x32 with smaller side 6000 -> 6000x12000
        self.assertEqual(calculate_output_dimensions(16, 32, min_side=6000), (6000, 12000))
        # Min side: 40x20 with smaller side 6000 -> 12000x6000
        self.assertEqual(calculate_output_dimensions(40, 20, min_side=6000), (12000, 6000))
        # Max side: 16x32 with larger side 8000 -> 4000x8000
        self.assertEqual(calculate_output_dimensions(16, 32, max_side=8000), (4000, 8000))

    def test_pixel_mode(self):
        svg_path = os.path.join(self.temp_dir.name, "pixel.svg")
        stats = convert_png_to_svg(self.png_path, svg_path, mode="pixel", group_by_color=False)
        # 1 blue + 16 red + 12 green = 29 pixels
        self.assertEqual(stats["rects_count"], 29)
        tree = ET.parse(svg_path)
        root = tree.getroot()
        self.assertEqual(root.attrib["viewBox"], "0 0 16 16")
        self.assertEqual(root.attrib["shape-rendering"], "crispEdges")

    def test_rle_mode(self):
        svg_path = os.path.join(self.temp_dir.name, "rle.svg")
        stats = convert_png_to_svg(self.png_path, svg_path, mode="rle")
        # 1 blue + (4 rows of red) + (2 rows of green) = 1 + 4 + 2 = 7 elements
        self.assertEqual(stats["rects_count"], 7)
        tree = ET.parse(svg_path)
        self.assertIsNotNone(tree.getroot())

    def test_greedy_mode(self):
        svg_path = os.path.join(self.temp_dir.name, "greedy.svg")
        stats = convert_png_to_svg(self.png_path, svg_path, mode="greedy")
        # 1 blue (1x1) + 1 red block (4x4) + 1 green block (6x2) = 3 elements!
        self.assertEqual(stats["rects_count"], 3)
        tree = ET.parse(svg_path)
        self.assertIsNotNone(tree.getroot())

    def test_path_output(self):
        svg_path = os.path.join(self.temp_dir.name, "path.svg")
        stats = convert_png_to_svg(self.png_path, svg_path, mode="greedy", element_type="path")
        tree = ET.parse(svg_path)
        root = tree.getroot()
        paths = [elem for elem in root.iter() if elem.tag.endswith("path")]
        self.assertEqual(len(paths), 3)

    def test_size_scaling_in_svg(self):
        svg_path = os.path.join(self.temp_dir.name, "scaled.svg")
        stats = convert_png_to_svg(self.png_path, svg_path, scale=10)
        self.assertEqual(stats["output_size"], (160, 160))
        tree = ET.parse(svg_path)
        root = tree.getroot()
        self.assertEqual(root.attrib["width"], "160")
        self.assertEqual(root.attrib["height"], "160")
        self.assertEqual(root.attrib["viewBox"], "0 0 16 16")

    def test_bg_detection_and_canvas_rect(self):
        svg_path = os.path.join(self.temp_dir.name, "bg_detected.svg")
        stats = convert_png_to_svg(self.solid_bg_png, svg_path, bg_detect=True, mode="greedy")
        self.assertTrue(stats["bg_detected"])
        self.assertEqual(stats["bg_color"], (255, 255, 255, 255))
        self.assertEqual(stats["bg_pixels_removed"], 192)

        tree = ET.parse(svg_path)
        root = tree.getroot()
        first_child = root[0]
        self.assertTrue(first_child.tag.endswith("rect"))
        self.assertEqual(first_child.attrib["width"], "16")
        self.assertEqual(first_child.attrib["height"], "16")
        self.assertEqual(first_child.attrib["fill"], "#ffffff")

    def test_strict_bg_detection(self):
        # 100% white border -> detected
        with Image.open(self.solid_bg_png) as im:
            self.assertEqual(detect_solid_background(im.load(), 16, 16), (255, 255, 255, 255))

        # Border has even 1 pixel of different color -> NOT detected
        with Image.open(self.solid_bg_png) as im:
            im_copy = im.copy()
            im_copy.putpixel((0, 5), (255, 0, 0, 255))  # red pixel on left edge
            self.assertIsNone(detect_solid_background(im_copy.load(), 16, 16))

    def test_png_to_eps_generation(self):
        eps_path = os.path.join(self.temp_dir.name, "output.eps")
        stats = convert_png_or_svg_to_eps(self.solid_bg_png, eps_path, mode="greedy", bg_detect=True, scale=10)
        self.assertEqual(stats["output_size"], (160, 160))
        self.assertTrue(os.path.exists(eps_path))

        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check Illustrator DSC headers
        self.assertIn("%!PS-Adobe-3.1 EPSF-3.0", content)
        self.assertIn("%%Creator: Adobe Illustrator(R) 16.0", content)
        self.assertIn("%%BoundingBox: 0 0 160 160", content)
        self.assertIn("%%HiResBoundingBox: 0 0 160.0000 160.0000", content)
        self.assertIn("%%EOF", content)

        # Validate with Ghostscript if installed
        res = subprocess.run(["gs", "-sDEVICE=nullpage", "-dBATCH", "-dNOPAUSE", eps_path], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)

    def test_svg_to_eps_conversion(self):
        # First generate SVG
        svg_path = os.path.join(self.temp_dir.name, "input.svg")
        convert_png_to_svg(self.solid_bg_png, svg_path, mode="greedy", bg_detect=True, scale=10)

        # Convert SVG to EPS
        eps_path = os.path.join(self.temp_dir.name, "from_svg.eps")
        stats = convert_png_or_svg_to_eps(svg_path, eps_path)
        self.assertEqual(stats["output_size"], (160.0, 160.0))

        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("%!PS-Adobe-3.1 EPSF-3.0", content)
        self.assertIn("%%BoundingBox: 0 0 160 160", content)

        # Validate with Ghostscript
        res = subprocess.run(["gs", "-sDEVICE=nullpage", "-dBATCH", "-dNOPAUSE", eps_path], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)

    def test_cli_default_format_is_eps(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        res = subprocess.run(
            ["python3", script_path, self.png_path],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        expected_eps = os.path.join(self.temp_dir.name, "test.eps")
        self.assertTrue(os.path.exists(expected_eps))

    def test_cli_svg_flag(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        res = subprocess.run(
            ["python3", script_path, self.png_path, "--svg"],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        expected_svg = os.path.join(self.temp_dir.name, "test.svg")
        self.assertTrue(os.path.exists(expected_svg))

    def test_cli_both_flag(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        res = subprocess.run(
            ["python3", script_path, self.png_path, "--both"],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "test.eps")))
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "test.svg")))

    def test_stock_canvas_and_preview_separation(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        # Explicit canvas min side (3000) and explicit preview min side (6000)
        res = subprocess.run(
            ["python3", script_path, self.png_path, "--canvas-min-side", "3000", "--preview", "--preview-min-side", "6000"],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)

        eps_path = os.path.join(self.temp_dir.name, "test.eps")
        jpg_path = os.path.join(self.temp_dir.name, "test.jpg")
        self.assertTrue(os.path.exists(eps_path))
        self.assertTrue(os.path.exists(jpg_path))

        # Canvas BoundingBox should be 3000x3000
        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("%%BoundingBox: 0 0 3000 3000", content)

        # Preview JPEG should be 6000x6000
        with Image.open(jpg_path) as im:
            self.assertEqual(im.size, (6000, 6000))

    def test_default_stock_sizing_for_canvas(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        res = subprocess.run(
            ["python3", script_path, self.png_path],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        eps_path = os.path.join(self.temp_dir.name, "test.eps")
        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Default 16x16 sprite auto-scales to 4000x4000 (16 MP, 15-25 MP sweet spot)
        self.assertIn("%%BoundingBox: 0 0 4000 4000", content)

    def test_svg_to_eps_and_preview_via_png2eps(self):
        # Generate SVG first
        svg_path = os.path.join(self.temp_dir.name, "source.svg")
        convert_png_to_svg(self.png_path, svg_path, mode="pixel")

        script_path = os.path.join(os.path.dirname(__file__), "..", "png2eps.py")
        res = subprocess.run(
            ["python3", script_path, svg_path, "--preview"],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        eps_path = os.path.join(self.temp_dir.name, "source.eps")
        jpg_path = os.path.join(self.temp_dir.name, "source.jpg")
        self.assertTrue(os.path.exists(eps_path))
        self.assertTrue(os.path.exists(jpg_path))

        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("%%BoundingBox: 0 0 4000 4000", content)

        with Image.open(jpg_path) as im:
            self.assertEqual(im.size, (6000, 6000))

    def test_svg2eps_cli(self):
        # Generate SVG first
        svg_path = os.path.join(self.temp_dir.name, "heart.svg")
        convert_png_to_svg(self.png_path, svg_path, mode="pixel")

        script_path = os.path.join(os.path.dirname(__file__), "..", "svg2eps.py")
        res = subprocess.run(
            ["python3", script_path, svg_path, "--preview", "--canvas-min-side", "4800"],
            capture_output=True, text=True, cwd=self.temp_dir.name
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        eps_path = os.path.join(self.temp_dir.name, "heart.eps")
        jpg_path = os.path.join(self.temp_dir.name, "heart.jpg")
        self.assertTrue(os.path.exists(eps_path))
        self.assertTrue(os.path.exists(jpg_path))

        with open(eps_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("%%BoundingBox: 0 0 4800 4800", content)

        with Image.open(jpg_path) as im:
            self.assertEqual(im.size, (6000, 6000))


if __name__ == "__main__":
    unittest.main()
