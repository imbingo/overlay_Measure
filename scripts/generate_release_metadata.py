from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Expected semantic version x.y.z, got {version!r}")
    return int(parts[0]), int(parts[1]), int(parts[2]), 0


def write_version_info(path: Path, version: str) -> None:
    numeric = version_tuple(version)
    comma_version = ", ".join(str(item) for item in numeric)
    dotted_version = ".".join(str(item) for item in numeric)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({comma_version}),
    prodvers=({comma_version}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404B0',
        [
          StringStruct(u'CompanyName', u'GCT'),
          StringStruct(u'FileDescription', u'SOMA Vision Metrology - 视觉轮廓与对位量测平台'),
          StringStruct(u'FileVersion', u'{dotted_version}'),
          StringStruct(u'InternalName', u'OverlayMeasure'),
          StringStruct(u'OriginalFilename', u'OverlayMeasure.exe'),
          StringStruct(u'ProductName', u'SOMA Vision Metrology'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, artifact: Path, version: str) -> None:
    checksum = sha256(artifact)
    payload = {
        "schema_version": 1,
        "product": "SOMA Vision Metrology",
        "channel": "stable",
        "version": version,
        "artifact": artifact.name,
        "artifact_type": "full_installer",
        "sha256": checksum,
        "size_bytes": artifact.stat().st_size,
        "minimum_upgrade_version": "1.8.0",
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(
        f"{checksum}  {artifact.name}\n",
        encoding="ascii",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--version-file", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    version_tuple(args.version)
    if args.version_file:
        write_version_info(args.version_file, args.version)
    if args.artifact or args.manifest:
        if not args.artifact or not args.manifest:
            parser.error("--artifact and --manifest must be supplied together")
        write_manifest(args.manifest, args.artifact, args.version)


if __name__ == "__main__":
    main()
