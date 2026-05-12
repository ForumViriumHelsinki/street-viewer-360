# Street Viewer 360

Local command-line tool that turns a folder of 360 panorama photos into a static, browsable web package: a Leaflet map with markers and a Pannellum panorama viewer. Optionally blurs faces and license plates.

See [PROJECT_DEVELOPMENT_PLAN.md](PROJECT_DEVELOPMENT_PLAN.md) for the full plan.

## Requirements

- macOS or Linux
- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv)

## Setup

Base install (metadata + frontend only):

```bash
uv sync
uv run pre-commit install
```

Anonymization support (faces + license plates) needs heavy ML dependencies (torch, ultralytics, opencv-python). Install them as an optional extra:

```bash
uv sync --extra anonymization
```

## Usage

### 1. Generate a static package

```bash
uv run street-viewer-360 generate \
  --input ./data/test-photos \
  --output ./dist-output \
  --config ./config.example.yaml \
  --overwrite
```

Open `dist-output/index.html` via any static server:

```bash
python3 -m http.server -d dist-output 8765
# http://127.0.0.1:8765
```

Run `uv run street-viewer-360 generate --help` for all options.

### 2. Download default anonymization models (optional)

Anonymization is opt-in and requires YOLOv8 model files. You can either supply your own `.pt` weights, or fetch the bundled defaults:

```bash
uv run street-viewer-360 download-models --target ./models
```

This downloads:
- `yolov8n-face.pt` — face detection ([arnabdhar/YOLOv8-Face-Detection](https://huggingface.co/arnabdhar/YOLOv8-Face-Detection))
- `yolov11n-license-plate.pt` — license plate detection ([morsetechlab/yolov11-license-plate-detection](https://huggingface.co/morsetechlab/yolov11-license-plate-detection))

This step is one-time. After it, pass the model paths to `generate` via CLI:

```bash
uv run street-viewer-360 generate \
  --input ./data/test-photos \
  --output ./dist-output \
  --face-model ./models/yolov8n-face.pt \
  --plate-model ./models/yolov11n-license-plate.pt \
  --overwrite
```

…or set them in a config file:

```yaml
anonymization:
  enabled: true
  blur_sigma: 15
  confidence_threshold: 0.35
  face_model_path: ./models/yolov8n-face.pt
  plate_model_path: ./models/yolov11n-license-plate.pt
```

If anonymization is enabled but no model paths are configured, the generator logs a warning and writes panoramas without blur (status `no_models` in metadata). Pass `--no-anonymization` to skip entirely. **You are responsible for reviewing output before publication** — detectors are best-effort.

### Configuration

`config.example.yaml` documents all options. CLI flags override config values, which override the built-in defaults. Key CLI overrides:

```text
--input PATH              Source directory
--output PATH             Destination directory
--config PATH             Optional YAML config
--overwrite               Replace existing output directory
--device auto|cpu|cuda|mps
--include-without-gps     Include images lacking GPS in metadata.json
--face-model PATH         YOLOv8 face-detection model (.pt)
--plate-model PATH        YOLOv8 license-plate-detection model (.pt)
--no-anonymization        Skip anonymization entirely
--dry-run                 Inspect without writing output
```

## Output layout

```text
dist-output/
  index.html
  metadata.json
  generation_report.json
  images/
    pano_000001.jpg
    ...
  assets/
    app.js  styles.css
    leaflet/  pannellum/
```

## Development

```bash
just lint    # ruff check
just fmt     # ruff format
just test    # pytest
just sample  # run against ./data/test-photos
```

## Status

Milestones 1–4 implemented (skeleton, metadata pipeline, static frontend, anonymization framework). See the project plan for upcoming items.
