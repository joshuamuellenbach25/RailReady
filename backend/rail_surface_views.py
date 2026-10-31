"""Original pixels plus bounded detail views for one rail-surface provider request."""
import base64
import io
import math

from PIL import Image

VERSION = "rail-detail-v1"
MAX_SIDE = 1568
JPEG_QUALITY = 88


def build_views(img: Image.Image) -> tuple[list[str], list[dict]]:
    """Caller supplies the EXIF-oriented image. Never enlarge or enhance its pixels."""
    width, height = img.size
    if width < 1 or height < 1:
        raise ValueError("Image dimensions must be positive.")
    rects = [(0, 0, width, height)]
    if max(width, height) > MAX_SIDE:
        # Four overlapping native-pixel crops; the full frame supplies context.
        xs = [(0, math.ceil(width * 0.55)), (math.floor(width * 0.45), width)]
        ys = [(0, math.ceil(height * 0.55)), (math.floor(height * 0.45), height)]
        rects += [(left, top, right, bottom) for top, bottom in ys for left, right in xs]
    images, views = [], []
    for view_id, rect in enumerate(rects):
        detail = img.crop(rect).convert("RGB")
        detail.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        detail.save(buf, format="JPEG", quality=JPEG_QUALITY)
        images.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        views.append({"view_id": view_id, "source_pixel_rect": list(rect),
                      "source_image_size": [width, height], "inference_image_size": list(detail.size)})
    return images, views


def _finite(value) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def map_box(box, view_id, views: list[dict]) -> list[float]:
    """Map a box in one supplied view to normalized EXIF-oriented full-frame coordinates."""
    if view_id is None:
        view_id = 0
    if not isinstance(view_id, int) or isinstance(view_id, bool) or not 0 <= view_id < len(views):
        raise ValueError("Unknown rail-surface view_id.")
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(_finite(v) for v in box):
        raise ValueError("Box must contain four finite numbers.")
    x, y, w, h = map(float, box)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise ValueError("Box must fit inside its source view.")
    view = views[view_id]
    if not isinstance(view, dict) or view.get("view_id") != view_id:
        raise ValueError("Mismatched rail-surface view metadata.")
    size, rect = view.get("source_image_size"), view.get("source_pixel_rect")
    if (not isinstance(size, (list, tuple)) or len(size) != 2 or not all(_finite(v) and v > 0 for v in size)
            or not isinstance(rect, (list, tuple)) or len(rect) != 4 or not all(_finite(v) for v in rect)):
        raise ValueError("Invalid rail-surface view geometry.")
    width, height = size
    left, top, right, bottom = rect
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("Rail-surface view lies outside the original image.")
    if rect == [0, 0, width, height] or rect == (0, 0, width, height):
        return [x, y, w, h]
    x0, y0 = (left + x * (right - left)) / width, (top + y * (bottom - top)) / height
    x1, y1 = (left + (x + w) * (right - left)) / width, (top + (y + h) * (bottom - top)) / height
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Box collapses at full-frame precision.")
    return [x0, y0, x1 - x0, y1 - y0]
