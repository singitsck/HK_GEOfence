### README: 以香港政府 CSDI 數據構建「香港電子圍欄」以區分過橋費（橋/隧固定費用）

> 參考來源：CSDI Portal（包含 Map APIs、Dataset APIs、WFS/WMS/ArcGIS REST、Dataset API Explorer）  
> 連結：[`https://portal.csdi.gov.hk/csdi-webpage/`](https://portal.csdi.gov.hk/csdi-webpage/)

---

### 目標
- 利用政府公開空間數據（CSDI）建立香港橋樑/隧道的電子圍欄，當裝置或車隊定位穿越特定橋/隧時，系統可自動判定並套用固定費用。
- 支援行動端（背景定位+地理圍欄）與伺服器側（高精度地圖匹配）的雙模式。

---

### 數據來源與授權
- 主要來源：CSDI Portal（地圖 API、Dataset API、WFS/WMS、ArcGIS REST）。  
  入口與文件：[`https://portal.csdi.gov.hk/csdi-webpage/`](https://portal.csdi.gov.hk/csdi-webpage/)
- 可能需要的主題/分類（CSDI「Framework Spatial Data Themes」與「Dataset Categories」）：
  - Transportation（道路網絡、橋樑、隧道）
  - Land Information / Geography（基礎地理資料作為輔助）
- 使用前請確認 CSDI Terms and Conditions 與數據集各自的授權條款；如需離線快取或再分發，需符合原授權要求。

---

### 系統總覽架構
- **資料層**：從 CSDI 以 WFS/ArcGIS REST 拉取橋樑/隧道幾何，清洗並轉為標準化 GeoJSON；維護一張「收費表」映射每個橋/隧到固定費用。
- **定位判定層**：
  - 行動端：OS 原生地理圍欄（低電耗）+ 前景/背景定位修正。
  - 伺服器側：接收 GPS 軌跡 → 地圖匹配（map-matching）→ 穿越事件偵測。
- **應用層**：統一費用計算 API，回傳「因穿越 X 橋/隧應收 Y 元」。
- **運營層**：資料更新（排程同步 CSDI）、灰度發布、監控、審計。

---

### 需要的資料集與取得方式（CSDI）
- 優先尋找包含下列幾何/屬性的資料集：
  - 橋樑（Bridge）線或面幾何，名稱、道路編號/別名。
  - 隧道（Tunnel）線或面幾何，名稱、入口/出口位置或端點。
  - 道路網絡（Road Network/Centerline）做地圖匹配參考。
- 取得方式（擇一或並用）：
  - Map APIs（用於底圖呈現）
  - Dataset API（WFS/WMS/ArcGIS REST）擷取幾何/屬性做計算
  - Dataset API Explorer（互動查找與測 API）
- 小貼士：
  - 使用 WFS（GeoJSON/GML）利於直接落地管線；ArcGIS REST 需再轉換。
  - 僅需精簡欄位：`id`, `name`, `geometry`, `type`（bridge/tunnel）, `aliases`。

資料入口與 API 類型說明均可見於 CSDI Portal：[`https://portal.csdi.gov.hk/csdi-webpage/`](https://portal.csdi.gov.hk/csdi-webpage/)

---

### 地理資料處理流程
1. 從 CSDI 抓取橋/隧資料（WFS/ArcGIS REST），一次性全量 → 以後每日/每週增量同步。
2. 清洗/標準化：
   - 坐標系統統一（通常 EPSG:4326 或本地投影）。
   - 名稱去重與別名（中英名、俗稱）。
   - 拆分橋與隧、確保幾何拓撲正確（MultiLineString/Polygon 修整）。
3. 建立「判定幾何」：
   - 隧道：在入口/出口兩端建立「閘口多邊形」（gate polygon），或沿線緩衝區（buffer）。
   - 橋樑：在橋面範圍建立面幾何或沿線緩衝區（例如 15–30 m）。
   - 方向敏感時，為雙向各建一個「入口閘口」。
4. 建立「固定費用表」：`structure_id ↔ fee`，若按車種有所不同，納入 `vehicle_class` 維度。

---

### 電子圍欄建模策略
- 模式 A：入口/出口「閘口多邊形」（Gate-based）
  - 優點：耗電低，行動端原生地理圍欄可直接用；事件粒度清晰（穿越即觸發）。
  - 作法：在橋/隧兩端建立小面積多邊形（10–50 m），只要 GPS 進入該多邊形即視為穿越。
- 模式 B：沿線緩衝（Corridor-based）
  - 優點：GPS 漂移容忍度較高。
  - 作法：對橋/隧線幾何做 buffer（例如 20–40 m），配合進入與離開事件窗口判定。
- 混合：入口用 Gate 判定，沿線用 Corridor 校驗，降低誤判（平行道路、立交層疊）。

---

### 收費模型（固定費）
- 前置假設：每個橋/隧收費固定（可依車種/時段擴充）。
- 建議資料表：
```sql
-- 結構主檔
CREATE TABLE transport_structure (
  structure_id TEXT PRIMARY KEY,
  name_zh TEXT NOT NULL,
  name_en TEXT,
  type TEXT CHECK(type IN ('bridge','tunnel')) NOT NULL,
  geometry_geojson JSONB NOT NULL,
  aliases JSONB DEFAULT '[]'
);

-- 收費表
CREATE TABLE toll_fee (
  structure_id TEXT REFERENCES transport_structure(structure_id),
  vehicle_class TEXT DEFAULT 'default',
  fee_hkd NUMERIC(10,2) NOT NULL,
  effective_from TIMESTAMP NOT NULL,
  effective_to TIMESTAMP,
  PRIMARY KEY (structure_id, vehicle_class, effective_from)
);
```

---

### 判定流程（高層邏輯）
1. 取得定位樣本（行動端或車機，每 1–5 秒）。
2. 伺服器側 map-matching 到道路中心線；過濾靜止點與離群點。
3. 偵測是否穿越「閘口多邊形」或進出「沿線緩衝」：
   - 若在時間窗口內，先後穿過「入口 A」→「出口 B」，則判定通過該橋/隧一次。
4. 透過 `structure_id` 查 `toll_fee`，回傳固定金額。
5. 去重與防重計（同路段短時間內重複觸發只計一次）。

---

### 後端 API 設計（範例）
- 上報 GPS
```http
POST /v1/telemetry
Content-Type: application/json

{
  "deviceId": "abc123",
  "ts": 1730341620,
  "points": [
    {"lat":22.304, "lng":114.161, "ts":1730341610, "speed":38},
    {"lat":22.305, "lng":114.162, "ts":1730341613, "speed":42}
  ]
}
```
- 判定結果回傳
```json
{
  "events":[
    {
      "structureId":"TUNNEL_LH",
      "nameZh":"紅磡海底隧道",
      "type":"tunnel",
      "crossedAt":"2025-10-31T07:27:10Z",
      "vehicleClass":"default",
      "feeHkd":20.00,
      "evidence":{
        "enterGateId":"LH_E",
        "exitGateId":"LH_W",
        "confidence":0.93
      }
    }
  ]
}
```
- 結構與費用查詢
```http
GET /v1/structures?bbox=114.15,22.30,114.18,22.32
GET /v1/tolls/{structureId}
```

---

### 行動端整合指引
- iOS：`CLLocationManager` + `CLCircularRegion`/自定多邊形（如需更精確，改伺服器判定）。啟用「顯著位置變更」與「背景更新」。
- Android：`GeofencingClient` + `WorkManager` 背景上報，進出事件觸發上報。
- 建議策略：
  - 小型 Gate 放在端點；Corridor 交由伺服器判定，提高準確性與抗漂移。
  - 使用前景服務（Android）在導航/通勤使用時，並降低上報頻率在閒置狀態。

---

### 精度與邊界情況
- 高架/多層立交：使用道路等級與 Z 座標（如可得）或拓撲關係過濾。
- 平行道路/匝道：入口 Gate 幾何需盡可能縮小、貼近實際入口車道；配合朝向與速度閾值。
- GPS 漂移：採用短時間窗口內的進出順序與濾波；必要時以 map-matching 結果為主。

---

### 資料更新與維運
- 排程更新：每日/每週同步 CSDI 資料集，校對新增/刪改之橋/隧幾何。
- 版本化：`transport_structure` 與 `toll_fee` 皆以生效期間控制；灰度釋出給小流量驗證。
- 快取：行動端保留本地只讀快取（結構邊界 + 版本號），脫網仍可粗判；回網後上傳事件與對賬。

---

### 測試計畫
- 單元：幾何相交、緩衝、方向判定、去重。
- 模擬：重放多條穿越/非穿越軌跡（含噪音與隨機漂移）。
- 外場：實測 5–10 條典型路徑（繁忙隧道、跨海橋、立交密集），記錄命中率與誤報率。
- 回歸：每次資料更新後自動跑回歸樣本。

---

### 監控與日誌
- 事件級審計：保留穿越事件、證據點、幾何 ID、信心分數（去識別化）。
- 指標：每日判定請求、命中率、矛盾率（手動核對樣本）、行動端電量影響。
- 告警：資料異常（結構缺漏/重覆/拓撲錯）、收費表缺項、API 錯誤率。

---

### 安全與隱私
- 最小化收集原則：僅保存判定所需資料與短期軌跡；採用設備匿名 ID。
- 傳輸與靜態加密；角色權限分離（讀幾何 vs 改費率）。
- 遵守 CSDI 數據條款與本地數據保護規範。

---

### 初始里程碑（建議）
- 第1週：鎖定 CSDI 資料集、打通 WFS/ArcGIS REST 拉取 → 建立清洗管線。
- 第2週：完成幾何標準化與 Gate/Corridor 生成 → 建立固定費用表。
- 第3週：後端 API 原型 + 模擬測試資料 → 行動端 POC。
- 第4週：外場測試與優化 → 監控與資料更新排程。

---

### 範例：GeoJSON 幾何與費用維護
```json
{
  "structure": {
    "structureId": "TUNNEL_LH",
    "nameZh": "紅磡海底隧道",
    "type": "tunnel",
    "geometry": {
      "type": "MultiLineString",
      "coordinates": [[[114.18,22.30],[114.17,22.30]]]
    },
    "gates": [
      {"gateId":"LH_E","polygon":{"type":"Polygon","coordinates":[[[114.181,22.301],[114.1809,22.301],[114.1809,22.3009],[114.181,22.3009],[114.181,22.301]]]}},
      {"gateId":"LH_W","polygon":{"type":"Polygon","coordinates":[[[114.171,22.3008],[114.1709,22.3008],[114.1709,22.3007],[114.171,22.3007],[114.171,22.3008]]]} }
    ]
  },
  "toll": {
    "vehicleClass": "default",
    "feeHkd": 20.0,
    "effectiveFrom": "2025-01-01T00:00:00Z"
  }
}
```

---

### 開發工具建議
- GIS：QGIS/ArcGIS Pro（人工檢視與修矯幾何）。
- 伺服器：PostGIS 或 SQLite+SpatiaLite；Node.js/Go/Python 皆可。
- 幾何運算：JTS/GEOS/Turf.js。
- 地圖匹配：現成服務（如 Valhalla/OSRM Map Matching）或自建簡化版。

---

### 重要連結
- CSDI Portal（包含 Map APIs、Dataset APIs、Explorer、OGC 服務）：[`https://portal.csdi.gov.hk/csdi-webpage/`](https://portal.csdi.gov.hk/csdi-webpage/)
- CSDI WFS 道路中心線服務：[`https://portal.csdi.gov.hk/server/services/common/landsd_rcd_1637310758814_80061/MapServer/WFSServer`](https://portal.csdi.gov.hk/server/services/common/landsd_rcd_1637310758814_80061/MapServer/WFSServer?service=wfs&request=GetCapabilities)

---

### API 服務

#### 道路中心線查詢服務 (`road_centreline_api.py`)

提供從 CSDI WFS 服務獲取香港道路中心線資料的獨立 Flask 應用。

**安裝依賴**:
```bash
pip install -r requirements.txt
```

**運行服務**:
```bash
python road_centreline_api.py
```

服務將在 `http://localhost:5008` 啟動。

**API 端點**:

1. **獲取道路中心線** - `POST /get_road_centreline`
   ```json
   {
     "bbox": [830000, 820000, 840000, 830000],  // 可選，EPSG:2326 座標
     "format": "geojson"  // 可選：geojson, json, gml, kml
   }
   ```

2. **獲取服務能力** - `GET /get_capabilities`
   - 返回 WFS 服務的能力描述

3. **健康檢查** - `GET /health`

**使用範例**:
```bash
# 獲取全部道路中心線
curl -X POST http://localhost:5008/get_road_centreline \
  -H "Content-Type: application/json" \
  -d '{}'

# 獲取特定區域的道路中心線
curl -X POST http://localhost:5008/get_road_centreline \
  -H "Content-Type: application/json" \
  -d '{
    "bbox": [830000, 820000, 840000, 830000],
    "format": "geojson"
  }'
```

**返回格式**:
```json
{
  "result": "0",
  "resultMessage": "Success",
  "data": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "feature_count": 123
}
```

---

### 交付物清單
- 標準化之橋/隧 GeoJSON 與 Gate/Corridor 幾何。
- 固定費率資料表與維護腳本。
- 判定服務 API（含事件審計與監控）。
- 行動端 SDK/指引（地理圍欄配置與上報協議）。
- 測試報告（命中/誤報/耗電）。
