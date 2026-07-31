"""
QR code payload generator. qrcode (PIL-based); optionally composite onto larger image.
Returns absolute Path to created file.
"""
from pathlib import Path
from typing import Optional

import qrcode
from PIL import Image

from payloads.config import get_output_dir
from payloads._utils import resolve_output_path


def create_qr_image(
    payload: str,
    filename: Optional[str] = None,
    subdir: str = "images",
    composite_width: Optional[int] = None,
    composite_height: Optional[int] = None,
    extension: str = "png",
) -> Path:
    """
    Create a QR code image. If composite_width/composite_height are set,
    paste the QR onto a larger blank image. Returns absolute path.
    """
    base = get_output_dir()
    path = resolve_output_path(filename, subdir, extension, base)
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img = qr_img.convert("RGB")
    if composite_width is not None and composite_height is not None and (composite_width > qr_img.width or composite_height > qr_img.height):
        out = Image.new("RGB", (composite_width, composite_height), color=(255, 255, 255))
        x = (composite_width - qr_img.width) // 2
        y = (composite_height - qr_img.height) // 2
        out.paste(qr_img, (x, y))
        out.save(str(path))
    else:
        qr_img.save(str(path))
    return path
