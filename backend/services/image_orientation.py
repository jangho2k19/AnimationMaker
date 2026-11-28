"""
Image Orientation & Aspect-Ratio Guard (adapted from HKUDS/ViMax tools/image_orientation.py).

Verifies that a generated image matches the requested orientation (landscape 16:9 vs.
portrait 9:16 Reels vs. square 1:1) before aspect-ratio fitting/cropping, so an accidental
wrong-orientation render can be retried once with an explicit orientation directive.
"""
from __future__ import annotations

import os
from typing import Tuple

from PIL import Image


def expected_orientation(width: int, height: int, square_band: float = 1.08) -> str:
    """Returns 'landscape', 'portrait', or 'square' for target dimensions."""
    w = int(width or 0)
    h = int(height or 0)
    if w <= 0 or h <= 0:
        return "square"
    ratio = w / h
    if ratio >= square_band:
        return "landscape"
    if ratio <= (1.0 / square_band):
        return "portrait"
    return "square"


def orientation_tolerance() -> float:
    raw = os.environ.get("ANISTORY_IMAGE_ORIENTATION_TOLERANCE", "1.06")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 1.06


def check_image_orientation(
    image: Image.Image,
    target_width: int,
    target_height: int,
    tolerance: float | None = None,
) -> Tuple[bool, str]:
    """
    Checks whether `image` matches the expected orientation of `(target_width, target_height)`.

    Returns `(True, "")` when compatible, or `(False, reason)` when opposite orientation
    (e.g., portrait image generated for a landscape 16:9 frame or vice versa).
    """
    img_w, img_h = image.size
    if img_w <= 0 or img_h <= 0:
        return True, ""

    tol = tolerance if tolerance is not None else orientation_tolerance()
    want = expected_orientation(target_width, target_height)

    if want == "landscape" and img_h > img_w * tol:
        return (
            False,
            f"Generated image is portrait ({img_w}x{img_h}) for landscape target ({target_width}x{target_height})",
        )
    if want == "portrait" and img_w > img_h * tol:
        return (
            False,
            f"Generated image is landscape ({img_w}x{img_h}) for vertical target ({target_width}x{target_height})",
        )
    return True, ""


def build_orientation_retry_hint(target_width: int, target_height: int) -> str:
    """Returns a strong composition directive to append when retrying a wrong-orientation image."""
    want = expected_orientation(target_width, target_height)
    if want == "landscape":
        return (
            f"STRICT CANVAS ORIENTATION: WIDE HORIZONTAL LANDSCAPE ({target_width}x{target_height}, 16:9 widescreen). "
            "Width MUST be greater than height. Do NOT generate a tall vertical portrait image."
        )
    if want == "portrait":
        return (
            f"STRICT CANVAS ORIENTATION: TALL VERTICAL PORTRAIT ({target_width}x{target_height}, 9:16 vertical). "
            "Height MUST be greater than width. Do NOT generate a wide horizontal landscape image."
        )
    return f"STRICT CANVAS ORIENTATION: SQUARE 1:1 ({target_width}x{target_height})."
