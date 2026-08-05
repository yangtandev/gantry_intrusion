#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  Gantry Intrusion Detection — One-Click Setup               ║
# ║                                                              ║
# ║  Targets: Fresh Ubuntu 22.04+ (no pre-existing environment) ║
# ║  Usage:   chmod +x install.sh && sudo ./install.sh          ║
# ╚══════════════════════════════════════════════════════════════╝
set -euo pipefail

# ======================== Configuration ========================
SERVICE_NAME="gantry_intrusion"
PYTHON_VERSION="3.12"
VENV_DIR="venv"
# ===============================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

user_systemctl() {
    local uid
    uid="$(id -u "${ACTUAL_USER}")"
    sudo -u "${ACTUAL_USER}" env \
        XDG_RUNTIME_DIR="/run/user/${uid}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
        systemctl --user "$@"
}

log_step()    { echo -e "\n${CYAN}${BOLD}[$1/7]${NC} ${BOLD}$2${NC}"; }
log_info()    { echo -e "  ${BLUE}→${NC} $1"; }
log_success() { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "  ${YELLOW}!${NC} $1"; }
log_error()   { echo -e "  ${RED}✗${NC} $1"; exit 1; }

# ──────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────
preflight() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此腳本需要 root 權限。請使用: sudo ./install.sh"
    fi

    ACTUAL_USER="${SUDO_USER:-$(whoami)}"
    ACTUAL_HOME=$(eval echo "~${ACTUAL_USER}")
    UV_BIN="${ACTUAL_HOME}/.local/bin/uv"

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║  Gantry Intrusion Detection — Setup Script ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Project:    ${CYAN}${PROJECT_DIR}${NC}"
    echo -e "  User:       ${CYAN}${ACTUAL_USER}${NC}"
    echo -e "  Python:     ${CYAN}${PYTHON_VERSION}${NC}"
    echo -e "  Service:    ${CYAN}${SERVICE_NAME}.service${NC}"
}

# ──────────────────────────────────────────────────────────────
# Step 1: Collect deployment configuration (ALL interaction here)
# ──────────────────────────────────────────────────────────────
collect_config() {
    log_step 1 "收集部署設定資訊..."

    local config_file="${PROJECT_DIR}/config.json"

    if [[ -f "${config_file}" ]]; then
        echo ""
        read -p "  已發現 config.json，是否重新配置？(y/N): " reconfigure
        if [[ ! "${reconfigure}" =~ ^[yY]$ ]]; then
            log_success "使用現有配置"
            return
        fi
    fi

    echo ""
    echo -e "  ${BOLD}請輸入以下部署資訊（按 Enter 使用 [預設值]）:${NC}"
    echo ""

    read -p "  API 端點 URL [https://example.com/api/v1]: " input_api_url
    local api_url="${input_api_url:-https://example.com/api/v1}"

    read -p "  是否啟用自動錄影？(y/N): " input_recording
    local enable_recording="false"
    if [[ "${input_recording}" =~ ^[yY]$ ]]; then
        enable_recording="true"
    fi

    read -p "  廣播語音文字 [天車行進區，請盡速離開]: " input_alert_voice_text
    local alert_voice_text="${input_alert_voice_text:-天車行進區，請盡速離開}"

    # --- Cameras ---
    echo ""
    echo -e "  ${BOLD}攝影機設定${NC}（至少需設定一台，輸入空白 ID 結束）:"

    local cameras_json=""
    local cam_index=0

    while true; do
        cam_index=$((cam_index + 1))
        echo ""

        local default_id=""
        if [[ ${cam_index} -eq 1 ]]; then default_id="camera_1"; fi
        if [[ ${cam_index} -eq 2 ]]; then default_id="camera_2"; fi

        if [[ -n "${default_id}" ]]; then
            read -p "  攝影機 #${cam_index} ID [${default_id}]: " input_cam_id
            input_cam_id="${input_cam_id:-${default_id}}"
        else
            read -p "  攝影機 #${cam_index} ID（留空結束）: " input_cam_id
        fi

        # Empty ID = stop adding cameras (must have at least 1)
        if [[ -z "${input_cam_id}" ]]; then
            if [[ ${cam_index} -eq 1 ]]; then
                log_error "至少需要設定一台攝影機"
            fi
            break
        fi

        local default_rtsp="rtsp://user:password@192.168.1.10${cam_index}:554/stream1"
        read -p "  攝影機 #${cam_index} RTSP URL [${default_rtsp}]: " input_rtsp
        input_rtsp="${input_rtsp:-${default_rtsp}}"

        read -p "  攝影機 #${cam_index} 警報裝置 IP（選填，留空跳過）: " input_alert_ip

        read -p "  攝影機 #${cam_index} Location ID [${cam_index}]: " input_loc_id
        input_loc_id="${input_loc_id:-${cam_index}}"

        [[ -n "${cameras_json}" ]] && cameras_json+=","
        cameras_json+="
        {
            \"id\": \"${input_cam_id}\",
            \"rtsp_url\": \"${input_rtsp}\""
        [[ -n "${input_alert_ip}" ]] && cameras_json+=",
            \"alert_device_ip\": \"${input_alert_ip}\""
        [[ -n "${input_loc_id}" ]] && cameras_json+=",
            \"location_id\": ${input_loc_id}"
        cameras_json+="
        }"
    done

    cat > "${config_file}" <<EOF
{
  "api_url": "${api_url}",
  "enable_recording": ${enable_recording},
  "cooldown_seconds": 5,
  "alert_voice_text": "${alert_voice_text}",
  "display": {
    "enabled": true
  },
  "runtime": {
    "frame_width": 1280,
    "frame_height": 720,
    "record_width": 1920,
    "record_height": 1080,
    "record_fps": 15,
    "inference_fps": 4,
    "inference_threads": 2
  },
  "model": {
    "backend": "ultralytics",
    "repo_id": "yihong1120/Construction-Hazard-Detection",
    "filename": "models/yolo26/pt/yolo26n.pt",
    "local_path": "",
    "openvino_path": "models/hf/yolo26n_openvino_model",
    "prefer_openvino": true,
    "auto_export_openvino": true,
    "device": "intel:cpu",
    "imgsz": 640,
    "confidence": 0.25,
    "iou": 0.5
  },
  "classes": {
    "intrusion": ["Person", "Machinery", "Vehicle"],
    "ignore": ["Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest", "Safety Cone", "Safety Vest", "Utility Pole"],
    "mask": []
  },
  "filters": {
    "min_confidence_by_class": {
      "Person": 0.3,
      "Machinery": 0.3,
      "Vehicle": 0.3
    },
    "max_bbox_size": {
      "enabled": false,
      "width_ratio": 0.8,
      "height_ratio": 0.8
    },
    "edge_confidence": {
      "enabled": false,
      "edge_ratio": 0.1,
      "min_confidence": 0.75
    },
    "mask_overlap": {
      "enabled": false,
      "max_overlap_ratio": 0.8,
      "ttl_frames": 15
    },
    "duplicate_bbox": {
      "enabled": true,
      "max_overlap_ratio": 0.8
    },
    "danger_zone_overlap": {
      "mode": "bottom_line",
      "line_width_ratio": 0.8,
      "bottom_offset_ratio": 0.0,
      "min_bbox_overlap_ratio": 0.15,
      "bottom_check_enabled": false,
      "bottom_margin_ratio": 0.1
    }
  },
  "zones": {
    "regions": {}
  },
  "cameras": [${cameras_json}
  ]
}
EOF

    chown "${ACTUAL_USER}:$(id -gn "${ACTUAL_USER}")" "${config_file}"
    echo ""
    log_success "配置已儲存至 config.json"
}

# ──────────────────────────────────────────────────────────────
# Step 2: System dependencies
# ──────────────────────────────────────────────────────────────
install_system_deps() {
    log_step 2 "安裝系統依賴套件 (git, git-lfs, OpenCV 執行期函式庫)..."

    apt-get update -qq > /dev/null 2>&1
    apt-get install -y -qq \
        git \
        git-lfs \
        ffmpeg \
        curl \
        build-essential \
        libgl1-mesa-glx \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libfontconfig1 \
        > /dev/null 2>&1

    sudo -u "${ACTUAL_USER}" git lfs install --skip-repo > /dev/null 2>&1

    log_success "系統依賴安裝完成"
}

# ──────────────────────────────────────────────────────────────
# Step 3: Install uv
# ──────────────────────────────────────────────────────────────
install_uv() {
    log_step 3 "安裝 uv (Rust 驅動的 Python 套件管理器)..."

    if sudo -u "${ACTUAL_USER}" bash -c "export PATH='${ACTUAL_HOME}/.local/bin:\${PATH}' && command -v uv" > /dev/null 2>&1; then
        local uv_ver
        uv_ver=$(sudo -u "${ACTUAL_USER}" bash -c "export PATH='${ACTUAL_HOME}/.local/bin:\${PATH}' && uv --version" 2>/dev/null)
        log_success "uv 已安裝: ${uv_ver}"
        return
    fi

    sudo -u "${ACTUAL_USER}" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' > /dev/null 2>&1

    if [[ -f "${UV_BIN}" ]]; then
        local uv_ver
        uv_ver=$("${UV_BIN}" --version 2>/dev/null)
        log_success "uv 安裝完成: ${uv_ver}"
    else
        log_error "uv 安裝失敗，請手動安裝: https://docs.astral.sh/uv/"
    fi
}

# ──────────────────────────────────────────────────────────────
# Step 4: Python environment
# ──────────────────────────────────────────────────────────────
setup_python_env() {
    log_step 4 "透過 uv 安裝 Python ${PYTHON_VERSION} 並建立虛擬環境..."

    log_info "下載 Python ${PYTHON_VERSION} (standalone build)..."
    sudo -u "${ACTUAL_USER}" bash -c "'${UV_BIN}' python install '${PYTHON_VERSION}'" > /dev/null 2>&1
    log_success "Python ${PYTHON_VERSION} 已就緒"

    log_info "建立虛擬環境: ${VENV_DIR}/"
    sudo -u "${ACTUAL_USER}" bash -c "cd '${PROJECT_DIR}' && '${UV_BIN}' venv --python '${PYTHON_VERSION}' '${VENV_DIR}'" > /dev/null 2>&1
    log_success "虛擬環境已建立"
}

# ──────────────────────────────────────────────────────────────
# Step 5: Python dependencies
# ──────────────────────────────────────────────────────────────
install_python_deps() {
    log_step 5 "安裝 Python 依賴套件 (ultralytics, OpenVINO, OpenCV...)..."
    log_info "這可能需要幾分鐘，請耐心等候..."

    sudo -u "${ACTUAL_USER}" bash -c "cd '${PROJECT_DIR}' && '${UV_BIN}' pip install --python '${VENV_DIR}/bin/python' -r requirements.txt" 2>&1 | tail -1

    log_success "所有 Python 依賴安裝完成"
}

# ──────────────────────────────────────────────────────────────
# Step 6: Git LFS model files
# ──────────────────────────────────────────────────────────────
pull_lfs_models() {
    log_step 6 "檢查模型檔案..."

    if [[ -d "${PROJECT_DIR}/.git" ]]; then
        sudo -u "${ACTUAL_USER}" bash -c "cd '${PROJECT_DIR}' && git lfs pull" > /dev/null 2>&1 || true
    fi

    if [[ -d "${PROJECT_DIR}/models/hf/yolo26n_openvino_model" ]]; then
        log_success "OpenVINO 模型已存在"
    else
        log_warn "尚未建立 OpenVINO 模型；第一次執行會從 Hugging Face 下載 PyTorch 權重"
        log_warn "CPU 部署建議之後匯出 OpenVINO：model.export(format='openvino')"
    fi
}

# ──────────────────────────────────────────────────────────────
# Step 7: User systemd service
# ──────────────────────────────────────────────────────────────
setup_and_start_service() {
    log_step 7 "部署 systemd user 服務並啟動..."

    local python_bin="${PROJECT_DIR}/${VENV_DIR}/bin/python"
    local user_uid
    user_uid="$(id -u "${ACTUAL_USER}")"
    local service_dir="${ACTUAL_HOME}/.config/systemd/user"
    local service_file="${service_dir}/${SERVICE_NAME}.service"

    # Ensure runtime output directories exist
    for dir in img_log log records exhibition_shots; do
        sudo -u "${ACTUAL_USER}" mkdir -p "${PROJECT_DIR}/${dir}"
    done

    sudo -u "${ACTUAL_USER}" mkdir -p "${service_dir}"

    cat > "${service_file}" <<EOF
[Unit]
Description=Gantry Intrusion Detection Service

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${python_bin} ${PROJECT_DIR}/main.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# Environment
Environment=OPENCV_LOG_LEVEL=SILENT
Environment=OPENCV_FFMPEG_LOGLEVEL=-8

# Display (uncomment if the edge device has a connected monitor)
# Environment=DISPLAY=:0
# Environment=XAUTHORITY=${ACTUAL_HOME}/.Xauthority

[Install]
WantedBy=default.target
EOF

    chown "${ACTUAL_USER}:$(id -gn "${ACTUAL_USER}")" "${service_file}"
    chmod 644 "${service_file}"

    if systemctl list-unit-files --type=service "${SERVICE_NAME}.service" 2>/dev/null | grep -q "^${SERVICE_NAME}\.service"; then
        systemctl disable --now "${SERVICE_NAME}.service" > /dev/null 2>&1 || true
        log_info "已停用舊的 system service，避免重複啟動"
    fi

    loginctl enable-linger "${ACTUAL_USER}" > /dev/null 2>&1
    systemctl start "user@${user_uid}.service" > /dev/null 2>&1 || true

    user_systemctl daemon-reload
    user_systemctl enable "${SERVICE_NAME}.service" > /dev/null 2>&1
    log_success "user 服務已建立並設為開機自啟"

    log_info "啟動服務..."
    user_systemctl start "${SERVICE_NAME}.service"

    sleep 3
    if user_systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        log_success "服務運行中！"
    else
        log_warn "服務可能啟動失敗，請檢查日誌: journalctl --user -u ${SERVICE_NAME} -n 50"
    fi
}

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}${BOLD}  Gantry Intrusion Detection — 部署完成          ${NC}"
    echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}常用指令:${NC}"
    echo -e "    查看即時日誌    ${CYAN}journalctl --user -u ${SERVICE_NAME} -f${NC}"
    echo -e "    查看服務狀態    ${CYAN}systemctl --user status ${SERVICE_NAME}${NC}"
    echo -e "    重啟服務        ${CYAN}systemctl --user restart ${SERVICE_NAME}${NC}"
    echo -e "    停止服務        ${CYAN}systemctl --user stop ${SERVICE_NAME}${NC}"
    echo ""
    echo -e "  ${BOLD}注意事項:${NC}"
    echo -e "    • 若需要 cv2.imshow 顯示視窗，請編輯 ${CYAN}${ACTUAL_HOME}/.config/systemd/user/${SERVICE_NAME}.service${NC}"
    echo -e "      取消 DISPLAY 與 XAUTHORITY 的註解，然後執行 ${CYAN}systemctl --user daemon-reload && systemctl --user restart ${SERVICE_NAME}${NC}"
    echo -e "    • 攝影機配置可直接編輯 ${CYAN}config.json${NC}，修改後重啟服務即可生效"
    echo ""
}

# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
main() {
    preflight
    collect_config
    install_system_deps
    install_uv
    setup_python_env
    install_python_deps
    pull_lfs_models
    setup_and_start_service
    print_summary
}

main "$@"
