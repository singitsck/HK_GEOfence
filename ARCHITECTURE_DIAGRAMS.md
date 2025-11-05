# 香港電子圍欄系統 - 架構流程圖

> 參考 README.md 中的完整系統設計

---

## 1. 系統整體架構流程

```mermaid
graph TB
    subgraph "外部數據源"
        CSDI[CSDI Portal<br/>政府空間數據平台]
    end
    
    subgraph "資料層"
        DOWNLOAD[數據抓取<br/>WFS/ArcGIS REST]
        CLEAN[數據清洗<br/>坐標標準化/去重]
        GATE[生成閘口幾何<br/>Gate/Corridor]
        DB[(PostgreSQL+PostGIS<br/>結構表+收費表)]
    end
    
    subgraph "定位判定層"
        MOBILE[行動端<br/>原生地理圍欄<br/>背景定位]
        SERVER[伺服器端<br/>Map Matching<br/>軌跡分析]
    end
    
    subgraph "應用層"
        API[API 服務<br/>費用計算/查詢]
    end
    
    subgraph "運營層"
        SYNC[排程同步<br/>每日/每週更新]
        MONITOR[監控告警<br/>日誌審計]
        CACHE[本地快取<br/>行動端脫網]
    end
    
    CSDI --> DOWNLOAD
    DOWNLOAD --> CLEAN
    CLEAN --> GATE
    GATE --> DB
    
    DB --> MOBILE
    DB --> SERVER
    DB --> API
    
    MOBILE --> API
    SERVER --> API
    
    API --> SYNC
    API --> MONITOR
    MOBILE --> CACHE
    
    SYNC --> CSDI
    
    style CSDI fill:#e1f5ff
    style DB fill:#fff4e1
    style API fill:#ffe1f5
    style MOBILE fill:#e1ffe1
    style SERVER fill:#e1ffe1
```

---

## 2. 地理資料處理流程

```mermaid
flowchart TD
    START([開始]) --> STEP1[從 CSDI 抓取<br/>橋/隧資料]
    
    STEP1 --> STEP2{數據類型判斷}
    STEP2 -->|全量數據| STEP2A[一次性全量導入]
    STEP2 -->|增量數據| STEP2B[每日/每週增量同步]
    
    STEP2A --> STEP3
    STEP2B --> STEP3
    
    STEP3[清洗/標準化] --> STEP3A[統一坐標系統<br/>EPSG:4326]
    STEP3A --> STEP3B[名稱去重與別名<br/>中英名/俗稱]
    STEP3B --> STEP3C[拆分橋與隧<br/>拓撲修整]
    
    STEP3C --> STEP4[建立判定幾何]
    
    STEP4 --> STEP4A{結構類型}
    STEP4A -->|隧道| TUNNEL[入口/出口閘口<br/>+ 沿線緩衝區]
    STEP4A -->|橋樑| BRIDGE[橋面幾何<br/>+ 15-30m緩衝區]
    
    TUNNEL --> STEP5
    BRIDGE --> STEP5
    
    STEP5[建立固定費用表<br/>structure_id ↔ fee] --> END([存儲到資料庫])
    
    style START fill:#c8e6c9
    style END fill:#ffcdd2
    style STEP4 fill:#fff9c4
    style STEP5 fill:#e1bee7
```

---

## 3. 電子圍欄建模策略

```mermaid
graph LR
    subgraph "模式 A: 閘口多邊形 Gate-based"
        A1[隧道入口] -->|10-50m| A2[GPS進入閘口] --> A3{檢測穿越}
        A3 -->|是| A4[觸發事件]
        A3 -->|否| A5[忽略]
    end
    
    subgraph "模式 B: 沿線緩衝 Corridor-based"
        B1[橋樑線幾何] -->|20-40m Buffer| B2[緩衝區範圍] --> B3{進入+離開<br/>時間窗口}
        B3 -->|是| B4[判定通過]
        B3 -->|否| B5[忽略]
    end
    
    subgraph "混合模式"
        C1[入口 Gate判定] --> C2{穿越閘口?}
        C2 -->|是| C3[Corridor校驗]
        C2 -->|否| C4[忽略]
        C3 --> C5{在沿線範圍?}
        C5 -->|是| C6[確認穿越]
        C5 -->|否| C7[誤判過濾]
    end
    
    style A4 fill:#c8e6c9
    style B4 fill:#c8e6c9
    style C6 fill:#c8e6c9
    style A5 fill:#ffcdd2
    style B5 fill:#ffcdd2
    style C7 fill:#ffcdd2
```

---

## 4. 判定流程（高層邏輯）

```mermaid
flowchart TD
    START([GPS定位樣本<br/>1-5秒間隔]) --> FILTER1[過濾靜止點與離群點]
    
    FILTER1 --> MAPMATCH[Map Matching<br/>道路中心線映射]
    
    MAPMATCH --> DETECT{偵測穿越事件}
    
    DETECT -->|閘口模式| GATE_CHECK[檢查閘口多邊形<br/>進入+離開順https://github.com/Dragonrise-team/device_alert.git序]
    DETECT -->|緩衝模式| CORRIDOR_CHECK[檢查沿線緩衝<br/>時間窗口內進出]
    
    GATE_CHECK --> ORDER_CHECK{入口A→出口B<br/>時間順序?}
    CORRIDOR_CHECK --> ORDER_CHECK
    
    ORDER_CHECK -->|是| LOOKUP[查詢 toll_fee<br/>structure_id]
    ORDER_CHECK -->|否| IGNORE[忽略此事件]
    
    LOOKUP --> FEE[回傳固定金額]
    
    FEE --> DEDUP{去重檢查<br/>短期內重複?}
    DEDUP -->|是| IGNORE
    DEDUP -->|否| SUCCESS([判定成功])
    
    SUCCESS --> AUDIT[事件審計<br/>信心分數/證據]
    
    style START fill:#c8e6c9
    style SUCCESS fill:#c8e6c9
    style IGNORE fill:#ffcdd2
    style AUDIT fill:#e1bee7
```

---

## 5. 後端 API 請求流程

```mermaid
sequenceDiagram
    participant APP as 行動端/車機
    participant API as API服務器
    participant DB as 資料庫
    participant MATCH as Map Matching引擎
    participant LOG as 審計日誌
    
    APP->>API: POST /v1/telemetry<br/>{deviceId, points[]}
    
    API->>MATCH: 發送GPS軌跡
    MATCH-->>API: 匹配後的軌跡
    
    API->>API: 幾何相交檢測<br/>(Gate/Corridor)
    
    API->>DB: 查詢穿越結構
    DB-->>API: structure_id, name, type
    
    API->>DB: 查詢收費表 toll_fee
    DB-->>API: fee_hkd
    
    API->>API: 去重檢查
    
    API->>LOG: 記錄事件審計
    
    API-->>APP: 返回穿越事件<br/>{structureId, feeHkd, confidence}
    
    Note over APP,LOG: 每個請求包含多個GPS點<br/>批次處理提高效率
```

---

## 6. 資料更新與維運流程

```mermaid
flowchart TD
    SCHEDULE[排程觸發<br/>每日/每週] --> SYNC[同步CSDI資料集]
    
    SYNC --> DIFF{檢測變更}
    
    DIFF -->|新增結構| ADD[新增結構記錄]
    DIFF -->|修改結構| MODIFY[更新結構幾何]
    DIFF -->|刪除結構| DELETE[標記失效日期]
    DIFF -->|無變更| SKIP[跳過]
    
    ADD --> VERSION
    MODIFY --> VERSION
    DELETE --> VERSION
    
    VERSION[版本化管理<br/>effective_from/effective_to] --> GRAY[灰度發布<br/>小流量驗證]
    
    GRAY --> TEST{測試結果}
    
    TEST -->|通過| DEPLOY[全量發布]
    TEST -->|失敗| ROLLBACK[回滾版本]
    
    DEPLOY --> MONITOR[監控告警]
    
    MONITOR --> ALERT{異常檢測}
    
    ALERT -->|資料異常| NOTIFY[通知運維]
    ALERT -->|正常| CONTINUE[持續運行]
    
    style SCHEDULE fill:#c8e6c9
    style DEPLOY fill:#c8e6c9
    style ROLLBACK fill:#ffcdd2
    style NOTIFY fill:#ffe1f5
```

---

## 7. 行動端整合流程

```mermaid
graph TB
    subgraph "iOS 流程"
        IOS_START[啟動CLLocationManager] --> IOS_REG[註冊CLCircularRegion<br/>地理圍欄]
        IOS_REG --> IOS_BG[啟用背景更新<br/>顯著位置變更]
        IOS_BG --> IOS_DETECT{檢測進入/離開}
        IOS_DETECT -->|事件觸發| IOS_SEND[上報GPS軌跡]
    end
    
    subgraph "Android 流程"
        AND_START[啟動GeofencingClient] --> AND_REG[註冊地理圍欄區域]
        AND_REG --> AND_WORK[WorkManager<br/>背景任務]
        AND_WORK --> AND_DETECT{檢測進入/離開}
        AND_DETECT -->|事件觸發| AND_SEND[上報GPS軌跡]
    end
    
    subgraph "混合策略"
        STRATEGY[小型Gate放在端點<br/>+ 伺服器Corridor校驗]
        STRATEGY --> ACTIVE[前景服務<br/>導航/通勤]
        STRATEGY --> PASSIVE[背景服務<br/>降低頻率]
    end
    
    IOS_SEND --> API
    AND_SEND --> API
    
    subgraph "伺服器端"
        API[API服務器] --> MAP[Map Matching]
        MAP --> JUDGE[判定穿越]
    end
    
    style IOS_START fill:#e1f5ff
    style AND_START fill:#fff4e1
    style JUDGE fill:#e1ffe1
```

---

## 8. 測試與監控流程

```mermaid
flowchart TD
    subgraph "測試層次"
        UNIT[單元測試<br/>幾何相交/緩衝/去重]
        SIM[模擬測試<br/>重放軌跡/噪音]
        FIELD[外場測試<br/>實測5-10條路徑]
        REGRESS[回歸測試<br/>數據更新後]
    end
    
    subgraph "監控指標"
        METRIC1[判定請求數<br/>命中率]
        METRIC2[矛盾率<br/>手動核對樣本]
        METRIC3[行動端電量影響]
        METRIC4[API錯誤率]
    end
    
    subgraph "告警規則"
        ALERT1[資料異常<br/>缺漏/重複/拓撲]
        ALERT2[收費表缺項]
        ALERT3[API錯誤率超閾]
    end
    
    subgraph "審計日誌"
        AUDIT1[穿越事件記錄]
        AUDIT2[證據點/幾何ID]
        AUDIT3[信心分數<br/>去識別化]
    end
    
    UNIT --> FIELD
    SIM --> FIELD
    FIELD --> REGRESS
    
    REGRESS --> METRIC1
    METRIC1 --> ALERT1
    METRIC2 --> ALERT2
    METRIC3 --> AUDIT1
    METRIC4 --> ALERT3
    
    style FIELD fill:#c8e6c9
    style ALERT1 fill:#ffcdd2
    style ALERT2 fill:#ffcdd2
    style ALERT3 fill:#ffcdd2
```

---

## 9. 安全與隱私流程

```mermaid
graph TB
    subgraph "數據收集"
        MINIMAL[最小化收集原則<br/>僅保存判定所需]
        ANONYMOUS[設備匿名ID<br/>非個人識別]
        SHORT[短期軌跡<br/>自動清理]
    end
    
    subgraph "數據傳輸"
        ENCRYPT_TRA[HTTPS加密<br/>TLS 1.3]
    end
    
    subgraph "數據存儲"
        ENCRYPT_STO[靜態加密<br/>AES-256]
        ACCESS[角色權限分離<br/>讀幾何 vs 改費率]
    end
    
    subgraph "合規"
        CSDI_TERMS[遵守CSDI條款]
        DATA_PROTECT[本地數據保護規範]
    end
    
    MINIMAL --> ENCRYPT_TRA
    ANONYMOUS --> ENCRYPT_TRA
    SHORT --> ENCRYPT_TRA
    
    ENCRYPT_TRA --> ENCRYPT_STO
    ENCRYPT_STO --> ACCESS
    
    ACCESS --> CSDI_TERMS
    ACCESS --> DATA_PROTECT
    
    style MINIMAL fill:#c8e6c9
    style ENCRYPT_TRA fill:#fff9c4
    style ACCESS fill:#e1bee7
```

---

## 10. 初始里程碑甘特圖

```mermaid
gantt
    title 香港電子圍欄系統 - 4週開發計劃
    dateFormat  YYYY-MM-DD
    section 第1週
    鎖定CSDI資料集         :a1, 2025-01-01, 2d
    打通WFS/ArcGIS REST    :a2, after a1, 3d
    建立清洗管線           :a3, after a2, 2d
    
    section 第2週
    幾何標準化             :b1, after a3, 3d
    Gate/Corridor生成      :b2, after b1, 2d
    建立固定費用表         :b3, after b2, 2d
    
    section 第3週
    後端API原型            :c1, after b3, 3d
    模擬測試資料           :c2, after c1, 2d
    行動端POC              :c3, after c2, 2d
    
    section 第4週
    外場測試               :d1, after c3, 3d
    優化                   :d2, after d1, 2d
    監控與資料更新排程     :d3, after d2, 2d
```

---

## 圖表使用說明

1. **系統整體架構** (圖1): 展示各層次的關係與數據流向
2. **地理資料處理** (圖2): 從CSDI數據到判定幾何的轉換流程
3. **電子圍欄建模** (圖3): 三種不同的判定策略比較
4. **判定流程** (圖4): GPS樣本到收費結果的核心邏輯
5. **API請求流程** (圖5): 端到端的請求處理時序
6. **資料更新維運** (圖6): 持續集成的管理流程
7. **行動端整合** (圖7): iOS/Android雙平台的實施方案
8. **測試與監控** (圖8): 質量保障體系
9. **安全與隱私** (圖9): 合規性要求
10. **開發里程碑** (圖10): 4週快速迭代計劃

---

## 技術棧建議

- **資料庫**: PostgreSQL + PostGIS
- **幾何運算**: JTS/GEOS/Turf.js
- **Map Matching**: Valhalla/OSRM 或自建簡化版
- **開發語言**: Node.js/Go/Python
- **GIS工具**: QGIS/ArcGIS Pro
- **監控**: Prometheus + Grafana

---

_最後更新: 2025-01-30_

