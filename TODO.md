# TODO

## Performance: parallelize image processing

Currently each image takes ~3.8 s on a MacBook with MPS-backed YOLO (after
lowering the default WebP method from 6 to 4). For a 1000-image dataset this
is ~1 hour. The work is unbalanced across stages and can be parallelized.

### Per-image stage breakdown (8K MAX 2 panorama, MPS, WebP method=4)

| Stage              | Time    | GIL-releasing?   | Bottleneck type      |
|--------------------|---------|------------------|----------------------|
| Decode source      | ~70 ms  | yes (cv2)        | CPU                  |
| Horizon correction | ~470 ms | yes (cv2.remap)  | CPU                  |
| YOLO inference     | ~2.0 s  | yes (torch)      | **GPU (serial)**     |
| WebP encode        | ~1.3 s  | yes (libwebp)    | CPU                  |
| Write to disk      | ~10 ms  | yes              | I/O                  |
| **Total**          | ~3.9 s  |                  |                      |

YOLO is the floor: ultralytics is not thread-safe on a single model instance,
and MPS/CUDA process one inference at a time anyway. Everything else releases
the GIL and can run truly concurrently in threads.

### Recommended design: ThreadPoolExecutor + anonymizer lock

```
worker(source, pano_id, decision, image_name):
    image = load_bgr(source)                  # CPU, concurrent
    if decision.apply:
        image = horizon.correct(image, ...)   # CPU, concurrent
    with anonymize_lock:
        outcome = anonymizer.process_image(image)  # GPU, serialized
    image_io.save(image, ..., source_path=source)  # CPU, concurrent
    return (pano_id, outcome, decision)
```

- `pano_id`, `image_name`, and `decision` computed in the main thread before
  submitting (preserves output ordering).
- Single `threading.Lock` inside `Anonymizer` guards `process_image`.
- Results collected via `as_completed` and sorted by submission order before
  writing to `panoramas` list.
- `--workers N` CLI flag, default 3. CPU-only inference (`--device cpu`)
  benefits from higher N; on MPS, >3 hits diminishing returns because the
  CPU stages can keep up with one GPU stream.

### Expected gains

YOLO (~2.0 s) becomes the per-image floor. The other stages (~1.85 s) hide
behind the next image's YOLO call. Estimated throughput: ~2.0 s/image, so
~1.9x speedup beyond the WebP-method change, ~2.5x total versus the
pre-perf baseline.

### Implementation notes

- Memory: N workers x 8K float arrays = ~200 MB per worker. N=3 is ~600 MB
  peak. Fine on modern Macs; document the trade-off for low-RAM machines.
- Logging: thread-safe by default in Python's `logging` module, but reorder
  log lines may interleave by image. Acceptable.
- `discover_images` ordering must be deterministic (it already is).
- Tests: extend the existing generator integration tests to cover N=1 and
  N=3 with the same expected output, asserting deterministic `pano_id`
  assignment regardless of worker count.

### Not chosen: ProcessPoolExecutor

Each worker would load its own YOLO model. CPU inference would scale near
linearly with cores, but MPS would just contend for the GPU and waste VRAM
on duplicate model copies. Threads + lock is simpler and equally fast on
GPU backends.

### Open question

If MPS contention turns out to be milder than expected (multiple threads
calling into MPS via separate Python threads but the same model), the lock
could become a bottleneck. Easy to A/B test once implemented: run with N=3
and lock vs N=3 without lock and observe whether outputs are correct (no
crashes, identical detections).

## Backlog (post-MVP, from PROJECT_DEVELOPMENT_PLAN.md §15)

- Manual anonymization review workflow.
- Stricter audit trail for anonymization decisions.
- Manual placement or imported coordinates for non-GPS panoramas.
- GPX track matching when image GPS is missing.
- Project manifests for regenerating or updating an existing package.
- Optional local tile packages for fully offline maps.
- Docker-based processing for reproducible Linux GPU execution.
- End-to-end browser tests for generated web packages.

## Done

UI improvements (completed earlier):

- Tighter closest zoom level.
- Replace default Leaflet marker icon with a small circle.
- Polyline between markers in capture order (with gap-based segmentation).
- Hover tooltip showing capture timestamp.
- Marker click opens panorama viewer directly.
- Arrow-key and on-screen navigation in the viewer.
- Split view: map + panorama side-by-side; map pans to active panorama and
  highlights the active marker.

Image processing:

- Per-detector confidence thresholds for faces and plates.
- Configurable panorama zoom limits.
- URL bookmarks carrying view state across navigation.
- Map polyline broken on large distance/time gaps.
- Horizon correction from XMP GPano pose angles.
- WebP output with EXIF/XMP preservation; pose angles zeroed after correction.
- WebP encoder effort exposed via `output.webp_method` / `--webp-method`.
