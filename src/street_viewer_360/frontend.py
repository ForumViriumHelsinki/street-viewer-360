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
