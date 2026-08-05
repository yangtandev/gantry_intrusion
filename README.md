# Gantry Intrusion Detection

Gantry crane restricted-zone intrusion detection for two RTSP cameras.

The app detects configured object classes inside per-camera polygon zones, saves alert images/debug JSON, triggers an optional HTTP voice alert, and posts intrusion logs to an API.

## Directories

- `mask/`: optional legacy fallback. New zone polygons live in `config.json`.
- `models/`: optional at first run, recommended. Local OpenVINO exports or pinned model files.
- `img_log/`: runtime output. Alert images by date, ignored by git.
- `log/`: runtime output. Text logs, ignored by git.
- `image/`: optional. Manual snapshots only.
- `tools/`: optional. Setup, mask drawing, and dataset helper scripts.
- `datasets/`: optional. Training config/reference files.
- `docs/`: optional. Project notes.

## Model

Default model source:

- Hugging Face repo: `yihong1120/Construction-Hazard-Detection`
- Default weight: `models/yolo26/pt/yolo26n.pt`
- Runtime: Ultralytics YOLO
- CPU path: auto-export OpenVINO on first run, then prefer `models/hf/yolo26n_openvino_model/`

Model classes:

```text
0 Hardhat
1 Mask
2 NO-Hardhat
3 NO-Mask
4 NO-Safety Vest
5 Person
6 Safety Cone
7 Safety Vest
8 Machinery
9 Utility Pole
10 Vehicle
```

Default intrusion classes:

```json
["Person", "Machinery", "Vehicle"]
```

## CPU Defaults

Target hardware: ASUS/Intel NUC14RVH-B, no discrete GPU.

Default runtime config reads 1920x1080/15 FPS camera streams, resizes frames to 1280x720, and runs inference at 4 FPS per camera with `imgsz=640`. Tune `runtime.inference_fps`, `runtime.inference_threads`, and `model.imgsz` in `config.json`.

## Configuration

`config.json` contains site-specific RTSP passwords and zone coordinates, so it is ignored by git. Create it with `install.sh`, then edit the local file when needed:

- `model.repo_id`, `model.filename`: Hugging Face model source
- `model.openvino_path`: local OpenVINO export path
- `classes.intrusion`: classes that can trigger zone intrusion
- `classes.ignore`: detected classes ignored for intrusion
- `filters.*`: optional size/edge/mask/duplicate/zone contact filters
- `zones.regions.{camera_id}`: normalized danger-zone polygon points
- `cameras[].rtsp_url`: RTSP URL
- `cameras[].alert_device_ip`: optional voice broadcast device host
- `cameras[].location_id`: API location id

Camera settings and danger zones are stored in `config.json`; zone points use normalized `[x, y]` coordinates:

```json
"cameras": [
  {
    "id": "camera_1",
    "rtsp_url": "rtsp://user:password@192.168.1.101:554/stream1",
    "alert_device_ip": "192.168.1.189",
    "location_id": 1
  }
],
"zones": {
  "regions": {
    "wb02_left": [
      [0.2063, 0.6069],
      [0.7094, 0.5736],
      [0.7875, 0.7639],
      [0.1648, 0.8222]
    ]
  }
}
```

Use `tools/calibrate_zone.py` to draw/edit camera zones.
Configured cameras without a zone still display live detections, but do not alert until a zone exists. Saving a zone to `config.json` is picked up automatically while the app is running.

Draw from the current RTSP frame:

```bash
python tools/calibrate_zone.py camera_1
```

Or draw from any image path:

```bash
python tools/calibrate_zone.py camera_1 --image /path/to/frame.jpg
```

`mask/{camera_id}.txt` is still accepted as a legacy fallback when `zones.regions.{camera_id}` is missing.

Controls:

- Left click: add point
- Right click or `U`: undo last point
- `R`: reset current zone
- `S`: save, requires at least 3 points
- `Q` or Esc: quit without saving

## Output Retention

Alert screenshots are written to:

```text
img_log/YYYYMMDD/
```

Text logs are written to:

```text
log/gantry_intrusion.log
```

The app cleans old `img_log/YYYYMMDD/` folders and rotated text logs hourly. Default retention is seven days.

## Zone Contact

Default intrusion check uses the middle 80% of each detection box bottom line:

```json
"danger_zone_overlap": {
  "mode": "bottom_line",
  "line_width_ratio": 0.8,
  "bottom_offset_ratio": 0.0
}
```

This is better for the slightly top-down camera angle because a person's upper body can overlap the drawn zone before their feet enter it. Set `line_width_ratio` smaller or larger as needed. Use `"mode": "overlap"` to return to area-overlap behavior.

## Run

```bash
source venv/bin/activate
python main.py
```

Or deploy:

```bash
sudo bash install.sh
```

Service name:

```bash
systemctl --user status gantry_intrusion
journalctl --user -u gantry_intrusion -f
```

## Check

```bash
python -m py_compile main.py camera.py tools/self_check.py
python tools/self_check.py
```

## Notes

- First run needs network to download the Hugging Face `.pt` model unless `model.local_path` points to a local file.
- First run also exports OpenVINO to `models/hf/yolo26n_openvino_model/`; later runs load that directory directly.
- `NO-Hardhat`, `NO-Mask`, and `NO-Safety Vest` are PPE findings, not intrusion by default.
- The model license is AGPL-3.0. Confirm license fit before production/commercial deployment.
