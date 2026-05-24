"""Frontend asset and template rendering for the generated static package."""

from __future__ import annotations

import logging
import shutil
from importlib.resources import as_file, files
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from street_viewer_360.config import AppConfig

logger = logging.getLogger(__name__)

_DEFAULT_TITLE = "Street Viewer 360"
_LOGO_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
_TILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _jinja_env() -> Environment:
    """Build a Jinja2 environment that loads templates from the package.

    Returns:
        Configured Environment with autoescape enabled for HTML/XML.
    """
    return Environment(
        loader=PackageLoader("street_viewer_360", "templates"),
        autoescape=select_autoescape(["html", "xml", "htm"]),
        keep_trailing_newline=True,
    )


def _copy_package_tree(resource_subpath: str, destination: Path) -> None:
    """Copy a directory tree from inside the package into the output.

    Args:
        resource_subpath: Path relative to the package root, e.g. "assets/leaflet".
        destination: Destination directory on disk. Created if missing.
    """
    parts = resource_subpath.split("/")
    resource = files("street_viewer_360").joinpath(*parts)
    with as_file(resource) as src:
        src_path = Path(src)
        if not src_path.is_dir():
            raise FileNotFoundError(f"Packaged resource not found: {resource_subpath}")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(src_path, destination)


def _copy_template_file(template_name: str, destination: Path) -> None:
    """Copy a plain (non-rendered) template file into the output.

    Args:
        template_name: File name inside `street_viewer_360/templates/`.
        destination: Destination file path.
    """
    resource = files("street_viewer_360").joinpath("templates", template_name)
    with as_file(resource) as src:
        shutil.copyfile(src, destination)


def _copy_logos(logo_paths: list[Path] | None, assets_dir: Path) -> list[dict[str, str]]:
    """Copy user-provided logo images into the generated frontend assets.

    Args:
        logo_paths: Logo image paths in display order.
        assets_dir: Generated package asset directory.

    Returns:
        Template-ready logo metadata with relative asset paths.

    Raises:
        FileNotFoundError: A logo path does not point to a file.
        ValueError: A logo has an unsupported web image extension.
    """
    logos_dir = assets_dir / "logos"
    if logos_dir.exists():
        shutil.rmtree(logos_dir)
    if not logo_paths:
        return []

    logos_dir.mkdir(parents=True, exist_ok=True)
    logos: list[dict[str, str]] = []
    for index, logo_path in enumerate(logo_paths, start=1):
        src_path = logo_path.expanduser()
        if not src_path.is_file():
            raise FileNotFoundError(f"Logo file not found: {logo_path}")
        suffix = src_path.suffix.lower()
        if suffix not in _LOGO_EXTENSIONS:
            raise ValueError(
                f"Unsupported logo file extension for {logo_path}. Supported extensions: "
                f"{', '.join(sorted(_LOGO_EXTENSIONS))}"
            )

        filename = f"logo_{index:03d}{suffix}"
        shutil.copyfile(src_path, logos_dir / filename)
        alt_text = src_path.stem.replace("-", " ").replace("_", " ").strip() or f"Logo {index}"
        logos.append({"src": f"assets/logos/{filename}", "alt": alt_text})

    return logos


def _inspect_tile_tree(src: Path) -> tuple[int, int, str]:
    """Determine zoom range and tile file extension for an XYZ tile directory.

    Scans top-level numeric subdirectories for ``z`` levels and samples any tile
    to detect the file extension.

    Args:
        src: Tile directory root (expected layout: ``{z}/{x}/{y}.<ext>``).

    Returns:
        Tuple of (min_zoom, max_zoom, extension without leading dot).

    Raises:
        ValueError: No numeric zoom directories or no tile files were found.
    """
    zoom_levels = sorted(int(d.name) for d in src.iterdir() if d.is_dir() and d.name.isdigit())
    if not zoom_levels:
        raise ValueError(f"No numeric zoom directories under {src}; expected XYZ layout {{z}}/{{x}}/{{y}}.")

    sample_tile: Path | None = None
    for z in zoom_levels:
        for tile in (src / str(z)).rglob("*"):
            if tile.is_file() and tile.suffix.lower() in _TILE_EXTENSIONS:
                sample_tile = tile
                break
        if sample_tile is not None:
            break
    if sample_tile is None:
        raise ValueError(f"No tile files with a supported extension found under {src}.")

    return zoom_levels[0], zoom_levels[-1], sample_tile.suffix.lower().lstrip(".")


def copy_tile_layers(layers: list[dict[str, object]], output_dir: Path) -> list[dict[str, object]]:
    """Copy custom tile directories under ``output_dir/tiles`` and build overlay metadata.

    The destination ``tiles/`` directory is fully replaced on every call so stale
    layers from previous runs are removed.

    Args:
        layers: Entries shaped ``{"src": Path, "name": str, "slug": str}``.
        output_dir: Generated package root.

    Returns:
        Overlay metadata entries (``name``, ``url``, ``min_zoom``, ``max_zoom``)
        ready to be written into ``metadata.json``.

    Raises:
        FileNotFoundError: A source directory is missing.
        ValueError: A source directory does not look like an XYZ tile tree.
    """
    tiles_root = output_dir / "tiles"
    if tiles_root.exists():
        shutil.rmtree(tiles_root)
    if not layers:
        return []

    tiles_root.mkdir(parents=True, exist_ok=True)
    overlays: list[dict[str, object]] = []
    for layer in layers:
        src = Path(layer["src"])  # type: ignore[arg-type]
        if not src.is_dir():
            raise FileNotFoundError(f"Tile directory not found: {src}")
        slug = str(layer["slug"])
        name = str(layer["name"])
        min_zoom, max_zoom, ext = _inspect_tile_tree(src)

        dest = tiles_root / slug
        shutil.copytree(src, dest)
        logger.info("Copied tile layer %r (%s) to %s [z=%d..%d, .%s]", name, src, dest, min_zoom, max_zoom, ext)

        overlays.append(
            {
                "name": name,
                "url": f"tiles/{slug}/{{z}}/{{x}}/{{y}}.{ext}",
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
            }
        )
    return overlays


def write_frontend(
    output_dir: Path,
    config: AppConfig,
    *,
    title: str = _DEFAULT_TITLE,
    logo_paths: list[Path] | None = None,
) -> None:
    """Render templates and copy vendored assets into the output directory.

    Args:
        output_dir: Root of the generated package (e.g. ./dist).
        config: Resolved application configuration (currently unused in templates
            beyond the title; map layers are read from metadata.json at runtime).
        title: Title shown in the HTML header and <title>.
        logo_paths: Optional logo image paths to show in the header.
    """
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    _copy_package_tree("assets/leaflet", assets_dir / "leaflet")
    _copy_package_tree("assets/pannellum", assets_dir / "pannellum")

    _copy_template_file("app.js", assets_dir / "app.js")
    _copy_template_file("styles.css", assets_dir / "styles.css")
    logos = _copy_logos(logo_paths, assets_dir)

    env = _jinja_env()
    index_html = env.get_template("index.html.j2").render(title=title, logos=logos)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    logger.info("Wrote frontend (index.html + assets) to %s", output_dir)
