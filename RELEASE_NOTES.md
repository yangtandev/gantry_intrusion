# Release Notes

## v1.6.5 - 2026-08-12

- 新增 `zone_crop_detection.mode=crop_only`，可只針對管制區裁切畫面推論，避免全畫面推論拖慢。
- 新增 `zone_crop_detection.multi_scale`，由管制區自動產生 context crop 與 zoom crops，適應不同攝影機角度。
- 新增 worker 效能 log，定期輸出取幀、推論、crop、後處理與顯示耗時。

## v1.6.4 - 2026-08-12

- 將灰色低結構雜訊檢查移到主流程取用最新幀時執行，避免 camera 讀取 thread 因逐幀分析造成串流積壓。
- 保留壞 frame 不進入辨識與告警流程，同時讓 RTSP 讀取持續追最新畫面。

## v1.6.3 - 2026-08-12

- 移除 RTSP 解碼警告監聽與警告後丟 frame 機制，避免額外 log 與短暫卡頓。
- 保留預設啟用的灰色低結構雜訊畫面過濾，專注以畫面品質判斷壞 frame。

## v1.6.2 - 2026-08-12

- 新增 RTSP 解碼警告監聽，解碼異常期間會丟棄可疑畫面。
- 新增預設啟用的灰色雜訊畫面過濾，避免壞畫面進入辨識與告警流程。
- 調整雜訊判斷加入邊緣密度，避免正常夜間黑白畫面被誤擋。

## v1.6.1 - 2026-08-11

- 降低即時顯示延遲，顯示佇列滿時會丟棄舊畫面並保留最新畫面。
- RTSP FFmpeg 管線新增低延遲旗標，減少串流緩衝造成的畫面落後。

## v1.6.0 - 2026-08-11

- 新增管制區裁切自動分段，長條管制區會以 480x270 tile 補強小人辨識。
- 新增上方補高與下緣錨定設定，保留站立人員上半身並減少不必要的 tile 推論。
- debug 目錄新增告警疊圖，顯示管制區、裁切 tile 與候選偵測框，方便現場調整參數。

## v1.5.0 - 2026-08-06

- 新增可選的管制區裁切人員偵測，保留全畫面偵測並補強遠距小人辨識。
- 裁切偵測結果會轉回原畫面座標後合併、去重，再套用既有管制區判斷。
- debug JSON 新增管制區座標、裁切偵測資訊與告警來源，方便判斷全畫面或裁切觸發。

## v1.4.1 - 2026-08-05

- 移除 `alert_voice_text` 設定與安裝時的語音文字輸入。
- 語音告警改為只呼叫播報裝置的 `voice1` 越南語與泰語版本。
- 語音內容與語音檔建立改由播報裝置統一管理。

## v1.4.0 - 2026-08-05

- 將原 GPIO 告警改為 HTTP 語音廣播告警。
- 新增共用 `alert_voice_text` 設定，安裝時可輸入廣播文字。
- 廣播裝置未建立語音時，會自動帶入共用文字建立語音檔。

## v1.3.0 - 2026-08-05

- 未設定管制區的攝影機仍會顯示即時畫面與偵測框，但暫不觸發告警。
- 管制區存回 `config.json` 後會自動熱更新套用，不需重啟服務。
- 改善 `Ctrl+C` 與 systemd stop 的 worker 結束流程，避免子行程收到 `SIGTERM` 後只記錄訊息卻未退出。

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
