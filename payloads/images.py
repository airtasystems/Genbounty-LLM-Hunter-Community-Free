"""
Image payload generators using Pillow. Text overlays with colors, transparency,
rotation, blur, and noise for red-team testing. Optional source image (upload).
Up to 3 text lines; each line can have its own font_size, color, alpha, position.
Returns absolute Path. PNG.
"""
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, BinaryIO

from payloads.config import get_output_dir
from payloads._utils import resolve_output_path

# Position: "top_left", "top_center", "top_right", "center_left", "center", "center_right", "bottom_left", "bottom_center", "bottom_right"
POSITION_OPTIONS = [
    "top_left", "top_center", "top_right",
    "center_left", "center", "center_right",
    "bottom_left", "bottom_center", "bottom_right",
]


def _parse_color(
    value: Optional[Union[str, Tuple[int, ...], list]],
    default_alpha: int = 255,
) -> Tuple[int, int, int, int]:
    """Return (r, g, b, a). Supports hex (#fff), names (white), or (r,g,b)[,a]."""
    if value is None or value == "":
        return (255, 255, 255, default_alpha)
    if isinstance(value, (list, tuple)):
        parts = [int(x) for x in value[:4]]
        if len(parts) == 3:
            parts.append(default_alpha)
        return tuple(max(0, min(255, p)) for p in parts[:4])  # type: ignore
    from PIL import ImageColor

    s = str(value).strip()
    if not s:
        return (255, 255, 255, default_alpha)
    try:
        rgb = ImageColor.getrgb(s)
        return (rgb[0], rgb[1], rgb[2], default_alpha)
    except (ValueError, TypeError):
        return (255, 255, 255, default_alpha)


def _position_to_xy(
    position: Union[str, List[Any], Tuple[Any, ...]],
    width: int,
    height: int,
    block_width: int,
    block_height: int,
    padding: int = 20,
) -> Tuple[int, int]:
    """Return (start_x, start_y) for the text block. position e.g. top_left, center, or [x, y]."""
    if isinstance(position, (list, tuple)) and len(position) >= 2:
        try:
            return int(float(position[0])), int(float(position[1]))
        except (TypeError, ValueError):
            pass
    pos = (position or "top_left").strip().lower().replace(" ", "_")
    if "_" not in pos:
        pos_v = pos if pos in ("top", "center", "bottom") else "top"
        pos_h = "center"
    else:
        parts = pos.split("_", 1)
        pos_v = parts[0] if parts[0] in ("top", "center", "bottom") else "top"
        pos_h = parts[1] if len(parts) > 1 and parts[1] in ("left", "center", "right") else "left"
    if pos_v == "top":
        start_y = padding
    elif pos_v == "bottom":
        start_y = max(padding, height - padding - block_height)
    else:
        start_y = max(0, (height - block_height) // 2)
    if pos_h == "left":
        start_x = padding
    elif pos_h == "right":
        start_x = max(padding, width - padding - block_width)
    else:
        start_x = max(0, (width - block_width) // 2)
    return start_x, start_y


# Common paths for a scalable font (size is only respected with truetype, not load_default).
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSText.ttf",
]


def _get_font(size: int):
    """Load a scalable font at the given size. Tries common paths so size is respected; falls back to default (fixed size)."""
    from PIL import ImageFont

    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _normalize_line_config(
    line: Any,
    default_fg: Tuple[int, ...],
    default_position: str,
    default_font_size: int,
    default_low_contrast: bool = False,
    default_text_rotation: float = 0.0,
    default_blur_radius: float = 0.0,
    default_noise_level: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Convert line to dict with text, font_size, color, alpha, position, low_contrast, text_rotation, blur_radius, noise_level. Returns None if text empty."""
    if isinstance(line, dict):
        text = (line.get("text") or "").strip()[:80]
        if not text:
            return None
        position_raw = line.get("position") if line.get("position") is not None else default_position
        if isinstance(position_raw, str):
            position_value: Union[str, List[Any], Tuple[Any, ...]] = position_raw.strip() or default_position
        elif isinstance(position_raw, (list, tuple)) and len(position_raw) >= 2:
            position_value = position_raw
        else:
            position_value = default_position
        return {
            "text": text,
            "font_size": max(8, min(120, int(line.get("font_size") or default_font_size))),
            "color": (line.get("color") or "").strip() or None,
            "alpha": min(255, max(0, int(line.get("alpha", 255)))),
            "position": position_value,
            "low_contrast": bool(line.get("low_contrast", default_low_contrast)),
            "text_rotation": float(line.get("text_rotation", default_text_rotation)),
            "blur_radius": max(0.0, min(25.0, float(line.get("blur_radius", default_blur_radius)))),
            "noise_level": max(0.0, min(1.0, float(line.get("noise_level", default_noise_level)))),
        }
    text = str(line).strip()[:80]
    if not text:
        return None
    return {
        "text": text,
        "font_size": default_font_size,
        "color": None,
        "alpha": 255,
        "position": default_position,
        "low_contrast": default_low_contrast,
        "text_rotation": default_text_rotation,
        "blur_radius": default_blur_radius,
        "noise_level": default_noise_level,
    }


def create_text_image(
    content: Optional[str] = None,
    width: int = 400,
    height: int = 200,
    filename: Optional[str] = None,
    subdir: str = "images",
    low_contrast: bool = False,
    extension: str = "png",
    background_color: Optional[Union[str, Tuple[int, ...]]] = None,
    text_color: Optional[Union[str, Tuple[int, ...]]] = None,
    background_alpha: int = 255,
    text_alpha: int = 255,
    text_rotation: float = 0.0,
    blur_radius: float = 0.0,
    noise_level: float = 0.0,
    source_image: Optional[Union[str, Path, bytes, BinaryIO]] = None,
    text_lines: Optional[List[Union[str, Dict[str, Any]]]] = None,
    position: str = "top_left",
    font_size: int = 14,
) -> Path:
    """
    Create an image with text overlay (injection payload). Returns absolute path.
    - text_lines: optional list of up to 3 items: string or dict with text, font_size, color, alpha, position per line.
    - position, font_size, text_color, text_alpha: used when text_lines are plain strings or as defaults for dicts.
    - source_image: optional path, bytes, or file-like; use as base image and draw on top.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    base = get_output_dir()
    path = resolve_output_path(filename, subdir, extension, base)
    use_alpha = background_alpha < 255 or text_alpha < 255
    mode = "RGBA" if use_alpha else "RGB"
    bg = _parse_color(background_color, background_alpha)
    default_fg = _parse_color(text_color, text_alpha)
    if low_contrast:
        default_fg = (180, 180, 180, text_alpha)
        if not background_color and not source_image:
            bg = (240, 240, 240, background_alpha)
    if not use_alpha and len(bg) == 4:
        bg = bg[:3]
    if not use_alpha and len(default_fg) == 4:
        default_fg = default_fg[:3]

    if source_image is not None:
        img = Image.open(source_image).convert("RGBA")
        w, h = img.size
        if width != 400 or height != 200:
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        else:
            width, height = w, h
        if len(default_fg) == 3:
            default_fg = default_fg + (text_alpha,)
    else:
        img = Image.new(mode, (width, height), color=bg)
    if img.mode == "RGBA" and len(default_fg) == 3:
        default_fg = default_fg + (text_alpha,)

    default_font_size = max(8, min(120, int(font_size)))
    padding = 20

    if text_lines is not None and len(text_lines) > 0:
        line_configs = []
        for line in text_lines[:3]:
            cfg = _normalize_line_config(
                line, default_fg, position, default_font_size,
                default_low_contrast=low_contrast,
                default_text_rotation=text_rotation,
                default_blur_radius=blur_radius,
                default_noise_level=noise_level,
            )
            if cfg:
                line_configs.append(cfg)
        if not line_configs:
            line_configs = [{
                "text": (content or "").strip()[:80] or "Instruction overlay.",
                "font_size": default_font_size, "color": None, "alpha": text_alpha, "position": position,
                "low_contrast": low_contrast, "text_rotation": text_rotation, "blur_radius": blur_radius, "noise_level": noise_level,
            }]
    else:
        lines_from_content = [l.strip()[:80] for l in (content or "").replace("\r", "").split("\n") if l.strip()][:3]
        if not lines_from_content:
            lines_from_content = [(content or "").strip()[:80] or "Instruction overlay."]
        line_configs = [{
            "text": t, "font_size": default_font_size, "color": None, "alpha": text_alpha, "position": position,
            "low_contrast": low_contrast, "text_rotation": text_rotation, "blur_radius": blur_radius, "noise_level": noise_level,
        } for t in lines_from_content]

    draw = ImageDraw.Draw(img)
    for cfg in line_configs:
        line_text = cfg["text"]
        line_font_size = cfg["font_size"]
        line_fill = _parse_color(cfg.get("color"), cfg.get("alpha", 255))
        if cfg.get("low_contrast", False) and not cfg.get("color"):
            line_fill = (180, 180, 180, cfg.get("alpha", 255))
        if img.mode == "RGBA" and len(line_fill) == 3:
            line_fill = line_fill + (cfg.get("alpha", 255),)
        if img.mode != "RGBA" and len(line_fill) == 4:
            line_fill = line_fill[:3]
        line_font = _get_font(line_font_size)
        bbox = draw.textbbox((0, 0), line_text, font=line_font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1] + 6
        start_x, start_y = _position_to_xy(cfg["position"], width, height, line_w, line_h, padding)
        line_rotation = float(cfg.get("text_rotation", 0))
        region_x, region_y, region_w, region_h = start_x, start_y, line_w, line_h

        if abs(line_rotation) >= 0.5:
            tw = max(line_w + 40, 20)
            th = max(line_h + 20, 20)
            layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            draw_layer = ImageDraw.Draw(layer)
            draw_layer.text((10, 2), line_text, fill=line_fill, font=line_font)
            rotated = layer.rotate(-line_rotation, expand=True, resample=Image.Resampling.BICUBIC)
            px = start_x
            py = max(0, start_y - rotated.height // 2)
            region_x, region_y = px, py
            region_w, region_h = rotated.width, rotated.height
            if img.mode != "RGBA":
                img = img.convert("RGBA")
                draw = ImageDraw.Draw(img)
            img.paste(rotated, (px, py), rotated)
        else:
            draw.text((start_x, start_y), line_text, fill=line_fill, font=line_font)

        line_blur = max(0.0, min(25.0, float(cfg.get("blur_radius", 0))))
        line_noise = max(0.0, min(1.0, float(cfg.get("noise_level", 0))))
        if line_blur > 0 or line_noise > 0:
            pad = int(max(line_blur * 2, 10)) if line_blur > 0 else 0
            x1 = max(0, region_x - pad)
            y1 = max(0, region_y - pad)
            x2 = min(width, region_x + region_w + pad)
            y2 = min(height, region_y + region_h + pad)
            if x2 > x1 and y2 > y1:
                crop = img.crop((x1, y1, x2, y2))
                if line_blur > 0:
                    crop = crop.filter(ImageFilter.GaussianBlur(radius=line_blur))
                if line_noise > 0:
                    arr = bytearray(crop.tobytes())
                    nch = len(crop.getbands())
                    for i in range(0, len(arr), nch):
                        for c in range(min(nch, 3)):
                            delta = int((random.random() - 0.5) * 2 * 255 * line_noise)
                            arr[i + c] = max(0, min(255, arr[i + c] + delta))
                    crop = Image.frombytes(crop.mode, crop.size, bytes(arr))
                img.paste(crop, (x1, y1))
                draw = ImageDraw.Draw(img)

    img.save(str(path), "PNG")
    return path
