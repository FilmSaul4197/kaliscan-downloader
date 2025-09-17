from __future__ import annotations

import shutil
import zipfile
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
    """Convert a list of images to a single PDF file."""
    if not image_files:
        raise ConversionError("No image files found to convert to PDF.")
    
    try:
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(image_files))
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
