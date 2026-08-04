# Release Notes

## v1.0.0 - 2026-08-05

- Forked project base from `rail_obstacle`.
- Replaced rail-obstacle model binding with configurable Ultralytics/Hugging Face model loading.
- Default model set to `yihong1120/Construction-Hazard-Detection` YOLO26n.
- Intrusion classes are configurable by class name.
- Removed rail-specific train temporal mask behavior from defaults.
- Added CPU-friendly runtime defaults for two 1080p RTSP cameras on NUC14RVH-B.
