# Release Notes

## v1.1.0 - 2026-08-05

- 首次啟動會自動匯出 OpenVINO 模型，之後直接載入本機匯出目錄。
- 載入 OpenVINO 前會驗證 IR 檔案可讀，避免壞模型被誤判為可用。
- 釘住已驗證可用的 OpenVINO 版本，移除不需要的 `openvino-dev`。
- 改善 `Ctrl+C` 與 `systemctl --user stop` 的關閉流程，減少清理期間的 traceback。

## v1.0.0 - 2026-08-05

- Forked project base from `rail_obstacle`.
- Replaced rail-obstacle model binding with configurable Ultralytics/Hugging Face model loading.
- Default model set to `yihong1120/Construction-Hazard-Detection` YOLO26n.
- Intrusion classes are configurable by class name.
- Removed rail-specific train temporal mask behavior from defaults.
- Added CPU-friendly runtime defaults for two 1080p RTSP cameras on NUC14RVH-B.
