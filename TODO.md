# TODO

## UI improvements (next session)

- [ ] Zoom in by a couple of levels at the closest setting — current closest zoom is too far away.
- [ ] Replace the default Leaflet marker icon with a small circle (CSS `divIcon` or `CircleMarker`).
- [ ] Draw a thin polyline between markers in capture order so the path is visible.
- [ ] Hover tooltip on each marker showing the capture timestamp (and later, a small thumbnail).
- [ ] Clicking a marker opens the panorama viewer directly (skip the popup with the "Open panorama" link).
- [ ] In the panorama viewer: arrow keys (left / right) navigate to previous / next image; also on-screen left / right arrows. ESC closes (already works).

## Backlog (post-MVP, from PROJECT_DEVELOPMENT_PLAN.md §15)

- Manual anonymization review workflow.
- Stricter audit trail for anonymization decisions.
- Manual placement or imported coordinates for non-GPS panoramas.
- GPX track matching when image GPS is missing.
- Project manifests for regenerating or updating an existing package.
- Optional local tile packages for fully offline maps.
- Docker-based processing for reproducible Linux GPU execution.
- End-to-end browser tests for generated web packages.
