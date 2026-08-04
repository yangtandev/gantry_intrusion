# Release Notes

## v1.2.0 - 2026-08-05

- 新增同類別重複偵測框去重，可透過 `filters.duplicate_bbox` 調整重疊門檻。
- 預設只保留重疊偵測框中信心度最高者，減少同一物體顯示多個框。

## v1.1.1 - 2026-08-05

- 修正模型輸出小寫類別名稱時，會被大寫設定值過濾掉而不顯示偵測框的問題。
- 類別過濾、信心度門檻與遮罩類別比對改為不分大小寫。

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
