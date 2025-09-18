from __future__ import annotations

import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import List

import img2pdf
from PIL import Image


class ConversionError(RuntimeError):
    """Raised when an error occurs during file conversion."""


def get_image_files(directory: Path) -> List[Path]:
    """Get a sorted list of image files from a directory."""
    extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    return sorted([p for p in directory.glob("*") if p.suffix.lower() in extensions])


def convert_to_pdf(image_files: List[Path], output_path: Path) -> None:
    """Convert a list of images to a single PDF file, removing alpha channels."""
    if not image_files:
        raise ConversionError("No image files found to convert to PDF.")

    images_data = []
    for image_path in image_files:
        try:
            with Image.open(image_path) as img:
                # Convert to RGB to remove alpha channel, which img2pdf doesn't like.
                if img.mode in ("RGBA", "LA"):
                    img = img.convert("RGB")
                # In-memory conversion
                with BytesIO() as byte_io:
                    img.save(byte_io, format='JPEG')
                    images_data.append(byte_io.getvalue())
        except Exception as e:
            raise ConversionError(f"Failed to process image {image_path.name}: {e}") from e

    try:
        with open(output_path, "wb") as f:
            pdf_bytes = img2pdf.convert(images_data)
            if pdf_bytes:
                f.write(pdf_bytes)
    except Exception as e:
        raise ConversionError(f"Failed to convert images to PDF: {e}") from e


def convert_to_cbz(image_files: List[Path], output_path: Path) -> None:
    """Convert a list of images to a single CBZ file."""
    if not image_files:
        raise ConversionError("No image files found to convert to CBZ.")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, image_file in enumerate(image_files):
            zf.write(image_file, f"{i:03d}{image_file.suffix}")


def cleanup_images(image_files: List[Path]) -> None:
    """Delete the given list of image files."""
    for image_file in image_files:
        try:
            image_file.unlink()
        except OSError as e:
            print(f"Warning: Could not delete file {image_file}: {e}")
