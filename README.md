# Muse Voice (TTS Tunnel & Synthesis)

`muse-voice` 是一個針對受限網絡與沙盒環境設計的語音合成（TTS）與網絡穿透方案。透過 `sing-box` AnyTLS 隧道與客製化 Python CONNECT Forwarder，成功繞過企業／沙盒出口代理對 WebSocket 連線與 API 認證標頭的嚴格限制，穩定支援 **Google Gemini TTS** 與 **Microsoft Edge TTS**。

---

## 項目背景

在受限的沙盒或企業內網環境下，所有出境流量通常被迫經由上游 Egress Proxy。此架構常造成以下 TTS 服務無法正常運作：
1. **Microsoft Edge TTS 阻斷**：上游代理無法維持 WebSocket 長連線，頻繁出現 `socket read timeout`。
2. **Google Gemini API 標頭攔截**：代理的 DLP（資料外洩防護）規則會檢測並阻擋發往 Google API 的特定身分認證標頭（如 `X-goog-api-key`）。

**解決方案**：
透過自建 AnyTLS 節點構建加密隧道，出口代理僅能看到前往遠端 AnyTLS 節點的加密 TLS / CONNECT 流量，使 WebSocket 與 Google API 請求均能順暢直達目標服務。

---

## 系統架構

整體流量鏈路如下：

```
應用端 (say.py / Edge TTS)
   │
   ▼ (HTTP / SOCKS5, 代理請求)
127.0.0.1:1080 (sing-box mixed inbound)
   │
   ▼ (AnyTLS 協定封裝)
127.0.0.1:1180 (Python forwarder.py)
   │
   ▼ (手動 CONNECT 握手 + Proxy-Authorization)
上游 Egress Proxy (企業/沙盒代理)
   │
   ▼ (雙向 TCP 直通)
遠端 AnyTLS 節點 (YOUR_NODE_HOST:YOUR_NODE_PORT)
   │
   ▼ (公網出境)
目標服務 (Google Gemini API / Microsoft Edge TTS WebSocket)
```

---

## 關鍵踩坑與解決方案

### 1. aiohttp 不支援 SOCKS 代理造成 RST
* **現象**：若向 `edge-tts` 傳入 `socks5://127.0.0.1:1080`，底層 `aiohttp` 會誤將其視為 HTTP 代理進行請求，導致 sing-box 的 SOCKS inbound 直接返回 TCP RST。
* **解決方案**：sing-box inbound 必須設定為 `mixed` 類型（同時監聽 HTTP 與 SOCKS5 代理），客戶端統一使用 `http://127.0.0.1:1080` 作為代理地址。

### 2. sing-box 內建 HTTP Outbound 缺乏 Proxy 認證支援
* **現象**：當上游 Egress Proxy 需要 Basic 帳號密碼認證時，sing-box 現有版本的 HTTP outbound 無法可靠傳遞 `Proxy-Authorization` 認證頭。
* **解決方案**：自行實作輕量級非同步代理轉發器 `forwarder.py`（監聽 `127.0.0.1:1180`），由其向上游 Egress Proxy 發起帶憑證的 HTTP `CONNECT` 請求，握手成功後建立透明雙向 TCP Pipe；sing-box 的 AnyTLS outbound 則直接連接本機 `127.0.0.1:1180`。

---

## 目錄結構

```
muse-voice/
├── README.md              # 項目說明文件
├── config.example.json    # sing-box 與節點配置範本
├── docs/                  # 文件與截圖資源
│   └── aistudio-api-key.png
├── env.example            # 上游代理與環境變數範本
├── forwarder.py           # Egress Proxy CONNECT 轉發器
├── run-tunnel.sh          # 隧道一鍵啟動腳本
├── say.py                 # Gemini TTS 語音合成命令列工具
└── .gitignore             # 忽略敏感設定與憑證
```

---

## 快速開始

### 1. 前置依賴

- Python 3.8+ (`requests`, `asyncio`)
- [sing-box](https://github.com/SagerNet/sing-box)（需支援 `anytls`，放置於項目根目錄或系統 PATH）
- `ffmpeg`（用於音訊解碼與 MP3 壓縮）

```bash
# Ubuntu / Debian 安裝 ffmpeg
sudo apt-get update && sudo apt-get install -y ffmpeg
```

### 2. 配置設定檔

複製範本並填入你的真實節點與認證資訊：

```bash
cp config.example.json config.json
cp env.example env
chmod 600 config.json env
```

- **`config.json`**：
  - `outbounds[0].password`：填入 AnyTLS 節點密碼。
  - `node_target`：填入遠端節點 `主機:端口`（例如 `node.example.com:443`）。
- **`env`**：
  - 若處於需要上游代理的環境，填入 `https_proxy=http://username:password@egress-proxy:port`。
- **Gemini API Key**：
  - 可寫入 `.gemini_key` 檔案（建議 `chmod 600 .gemini_key`）或設置環境變數 `GEMINI_API_KEY`（獲取方式詳見下文 [獲取 Google Gemini API Key](#獲取-google-gemini-api-key)）。

### 3. 啟動隧道

執行啟動腳本：

```bash
chmod +x run-tunnel.sh
./run-tunnel.sh
```

啟動後：
- `127.0.0.1:1180`：Python CONNECT forwarder 監聽中。
- `127.0.0.1:1080`：sing-box Mixed Inbound 就緒（提供 HTTP / SOCKS5 代理）。

---

## 獲取 Google Gemini API Key

使用本項目（如 `say.py`）需要 Google Gemini API Key。獲取步驟如下：

1. **前往 Google AI Studio**：造訪 https://aistudio.google.com 並登入 Google 帳號。
2. **獲取 API Key**：點擊左側選單左下角的鑰匙圖示（**API Keys**），按指示建立一條 API key（免費額度已足夠一般日常使用）。
3. **配置 API Key**：將取得的 API Key 寫入以下其中一個位置：
   - 環境變數 `GEMINI_API_KEY`
   - 憑證檔案 `~/workspace/tts-tunnel/.gemini_key`（或本項目目錄下的 `.gemini_key`，權限設定為 `chmod 600`）
   - `config.json` 中的 `gemini_api_key` 欄位
4. **安全提示**：切勿將 API Key 提交至 GitHub 等公開倉庫（本項目的 `.gitignore` 已預設排除 `.gemini_key` 與 `config.json`）。

![Google AI Studio API Key 入口](docs/aistudio-api-key.png)

---

## `say.py` 使用指南

`say.py` 透過本地 `127.0.0.1:1080` 代理調用 Google Gemini API 的音訊生成功能，並使用 `ffmpeg` 將回傳的 24000Hz s16le PCM 壓製為標準 MP3。

### 基本指令

```bash
python3 say.py "<文字內容>" [聲音名稱] [輸出檔案路徑]
```

### 範例

```bash
# 預設使用 Laomedeia 聲線生成 output.mp3
python3 say.py "早晨，今日有咩可以幫到你？"

# 指定輸出檔名
python3 say.py "測試廣東話語音合成。" Laomedeia test.mp3

# 支援的聲線範例：Laomedeia (活潑女聲，廣東話推薦)、Charon (沉穩男聲)、Puck 等
python3 say.py "系統已就緒。" Charon ready.mp3
```

### 自動降級機制（Fallback）
- 預設優先使用 `gemini-2.5-flash-preview-tts`。
- 若遭遇 HTTP 429 配額限制，腳本會自動回退至可用備用模型（如 `gemini-3.8-flash-tts`）。

---

## systemd 長駐化服務

如需在背景常駐並於系統開機時自啟動，可建立 systemd user service：

1. 建立服務設定檔 `~/.config/systemd/user/tts-tunnel.service`：

```ini
[Unit]
Description=TTS Tunnel Service (sing-box + forwarder)
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/workspace/muse-voice
EnvironmentFile=-%h/workspace/muse-voice/env
ExecStart=%h/workspace/muse-voice/run-tunnel.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

2. 啟用並啟動服務：

```bash
systemctl --user daemon-reload
systemctl --user enable --now tts-tunnel.service

# 允許用戶登出後常駐運行 (Linger)
loginctl enable-linger $USER
```

3. 檢查狀態：

```bash
systemctl --user status tts-tunnel.service
```

---

## 安全提醒

請確保以下檔案**絕對不要**提交至版本庫：
- `config.json`（含有真實節點資訊與密碼）
- `.gemini_key`（Google API 憑證）
- `env`（含上游 Egress Proxy 帳號密碼）

本項目自帶之 `.gitignore` 已預設排除上述檔案。
