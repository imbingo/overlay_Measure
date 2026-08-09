from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .image_loader import load_image
from .models import ImageData


@dataclass(frozen=True)
class BatchImageRef:
    """A lightweight batch item that defers pixel loading until measurement time."""

    path: str
    display_name: str = ""
    size_bytes: int = 0

    @classmethod
    def from_path(cls, path: str) -> "BatchImageRef":
        file_path = Path(path)
        try:
            size = file_path.stat().st_size
        except OSError:
            size = 0
        return cls(str(file_path), file_path.name, int(size))

    def load(self) -> ImageData:
        return load_image(self.path)


def resolve_image(value: ImageData | BatchImageRef | None) -> ImageData | None:
    if value is None or isinstance(value, ImageData):
        return value
    return value.load()


def image_path(value: ImageData | BatchImageRef | None) -> str:
    return "" if value is None else str(value.path)
