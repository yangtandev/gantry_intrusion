# Gantry Intrusion Architecture

## Purpose

Detect `Person`, `Machinery`, and `Vehicle` objects entering configured gantry-crane restricted zones from two RTSP cameras.

## Runtime Flow

1. Read `config.json`.
2. Load each camera RTSP stream in its own process.
3. Load the configured Ultralytics model.
4. Prefer local OpenVINO export when available.
5. Otherwise download the configured Hugging Face `.pt` file.
6. Resize frames to `runtime.frame_width` x `runtime.frame_height`.
7. Run inference at `runtime.inference_fps`.
8. Filter detections by configured class names and confidence.
9. Check each detection box bottom contact line against `zones.regions.{camera_id}` from `config.json`; cameras without zones remain display-only and reload zones from config while running.
10. Save alert images/debug JSON under `img_log/YYYYMMDD/`, trigger optional HTTP voice alert, post optional API log.
11. Write text logs under `log/`.
12. Clean runtime outputs older than seven days every hour.

## Default Model

```json
{
  "repo_id": "yihong1120/Construction-Hazard-Detection",
  "filename": "models/yolo26/pt/yolo26n.pt"
}
```

Classes:

```text
Hardhat
Mask
NO-Hardhat
NO-Mask
NO-Safety Vest
Person
Safety Cone
Safety Vest
Machinery
Utility Pole
Vehicle
```

## Filters

Configured in `config.json`:

- `classes.intrusion`: classes that can alert
- `classes.ignore`: classes to skip
- `classes.mask`: classes used only as exclusion masks
- `zones.regions`: normalized per-camera danger-zone polygons
- `filters.min_confidence_by_class`
- `filters.max_bbox_size`
- `filters.edge_confidence`
- `filters.mask_overlap`
- `filters.duplicate_bbox`
- `filters.danger_zone_overlap`

Default zone mode is `bottom_line` with `line_width_ratio=0.8`, so only the middle 80% of the detection box bottom edge needs to touch the drawn polygon. Use `mode=overlap` to return to area-overlap behavior.

Legacy `mask/{camera_id}.txt` files are still accepted when a camera has no config zone.

Default avoids rail-specific filtering. `mask_overlap`, size checks, and edge checks are off by default to reduce false negatives in a new site.

## CPU Deployment

NUC14RVH-B has no discrete GPU. Start with:

- `yolo26n.pt`
- `imgsz=640`
- `runtime.inference_fps=4`
- two camera processes
- `runtime.inference_threads=2`

Then export OpenVINO and point `model.openvino_path` to the export directory.
