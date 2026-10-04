# 台股技術分析策略網站

個人用的收盤後研究工具：Python / FastAPI 策略引擎、Next.js 網站、SQLite 本機持久化。設定 `DATABASE_URL` 可改用 PostgreSQL；第一版不用申請雲端服務。

股票池預設排除ETF，掃描及回補採交易所現行上市櫃股票名單（包含創新板與臺灣存託憑證）。舊股票與ETF的既有行情保留於資料庫，但不納入此股票池。

## 使用

Windows PowerShell，於專案目錄執行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
Copy-Item .env.example .env  # 僅第一次；已存在時不要覆蓋
npm run build
.\scripts\start.ps1 -Production
```

開啟 http://127.0.0.1:3000 。開發模式使用 `.\scripts\start.ps1`。背景啟動使用 `.\scripts\serve-background.ps1`，服務紀錄與 PID 存於 `data/`；不要啟動多組佔用相同埠號的服務。

每個頁面上方都有「操作導覽」：先介紹全站使用順序，再逐步說明當頁按鈕與資料判讀。支援上一步、下一步、略過、完成與Escape關閉；導覽不會啟動背景工作或修改資料。

| 頁面 | 功能 |
|---|---|
| `/scan` | 多空訊號、必要濾網、類股排名、自訂掃描條件保存 |
| `/watchlist` | 手動／自動鎖股、強弱排序、趨勢轉空汰換 |
| `/stock/2330` | 日週月K、均線／轉折／缺口／大量K標註、六六大順、4基10技、10戒律、17項收盤後工作 |
| `/backtest` | 多進場規則組合、7種出場模組、5種停損方法、多券商成本、樣本外、9組參數比較、逐筆交易與下載 |
| `/portfolio` | 個別持股批次、出場／套牢／牛步股／加碼位置提醒、月目標與實際報酬、LINE佇列 |
| `/rules` | 規則出處、數值近似標示、Part02~12筆記 |
| `/settings` | 月2%目標／本金30萬、可調10%最大虧損、策略停損、均量、股票池、券商及規則參數 |
| `/data` | 先全市場近期行情／還原價，再10年歷史與基本面；回補啟停與續跑、資料覆蓋、品質及背景工作狀態 |

## 資料與排程

```powershell
.venv\Scripts\python.exe -m backend.ingest list
.venv\Scripts\python.exe -m backend.ingest daily
.venv\Scripts\python.exe -m backend.ingest backfill --stocks 2330,2317,2454 --years 10
.venv\Scripts\python.exe -m backend.worker --years 10
.\scripts\install-schedule.ps1
```

每天本機時間15:30與20:00執行 `StockStrategyDaily`，僅平日；資料、掃描、持股與通知結果持久保存。電腦需要在可執行排程的狀態。GitHub Actions的每日工作另提供部署用範本，預設停用，須設定持久的 `DATABASE_URL` 與 `ENABLE_DAILY_JOB=true` 才執行，避免同時跑兩組排程。

日K使用 [TWSE](https://openapi.twse.com.tw/)、[TPEx](https://www.tpex.org.tw/openapi/)；歷史、法人、融資券、營收及財報使用 [FinMind](https://finmind.github.io/)。還原價使用免費除權息／減資參考價建立因子，不依賴付費 `TaiwanStockPriceAdj`。API失敗保留原始資料與檢查點，FinMind背景工作等待10分鐘後重試，操作停止也不刪資料。

可另執行 `python -m backend.official_history --years 10`，使用交易所公開歷史單日行情先補全市場近370日，再往前補10年日K，不消耗FinMind額度。此程序只新增缺少的原始行情，保留既有價格與還原驗證，不把日K完成冒充為法人、營收、財報或還原價已完成。歷史行情依現行股票代號跨兩市場比對，保留轉板前的行情；ETF依股票池排除。逐市場／交易日檢查點可續跑，空白或日期／欄位不符的回應不標記完成，異常OHLC另行隔離。狀態存於資料庫 `official_bulk/latest`；建立 `data/STOP_OFFICIAL_HISTORY` 可停止，移除後重新執行即續跑。此程序有獨立OS鎖，不會重複啟動。

**程式可續跑不代表全市場10年資料已回補完成。** `/data` 顯示實際完成檔數；`/scan` 只計入至少60日日K的股票，缺資料不能當成沒有訊號。來源日K可能含停牌缺日，未知限制股及不完整均量窗口不納入可交易候選。無完整歷史券源的空方結果僅供研究。

SQLite資料、持股與設定保存在 `data/strategy.db`，不提交Git。備份請用 `python -m scripts.backup`，不要只複製正在使用中的主資料庫而漏掉WAL。若需要FinMind token，僅在 `.env` 設定；不要提交金鑰或資料庫。

## 通知與存取

在 `.env` 設定 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_RECIPIENT_USER_ID`，重新啟動後端，於設定頁啟用通知。通知依「持股／日期／規則」去重，以固定 `X-Line-Retry-Key` 重試，失敗保留佇列；未設定憑證時只能預覽，不宣稱已傳送。使用者已選擇稍後自行設定，實機傳送驗收暫不執行。

- [LINE token](https://developers.line.biz/en/docs/basics/channel-access-token/)
- [LINE user ID](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)

本機服務綁定127.0.0.1。遠端部署須設定 `API_TOKEN`、`APP_PASSWORD`（帳號 `owner`）、`APP_ORIGIN`，並使用HTTPS。金鑰只由伺服器代理持有。提供Dockerfile與compose；Docker需先啟動引擎，`docker compose up --build -d` 的設定預設只發布本機3000埠。Docker映像尚未在本機引擎驗收，不能把前端建置成功當作容器已驗收。

## 回測與規則的實際範圍

- 訊號只使用當日及以前完成日K，次交易日開盤成交。入場／補回當日不做日內出場；隔日觸價停損，跳空用較差開盤價再加滑價。日K不提供盤中事件順序。
- 策略停損與可調最大虧損上限取先觸發的價位；上限不能保證跳空時的成交損失。每次結果保存當次全部設定與成本快照。
- 成交價格與股數使用期初基準的還原價模型，成本按模型金額計算，並非逐日現金股利／配股的券商對帳。持股頁使用自行輸入的實際成本。
- 每邊手續費預設0.1425%×0.28＝0.0399%，最低20元，可依券商調整；另計賣出稅、滑價與空單借券費。ETF仍採表單選定的統一稅率，研究ETF時需自行設定適用成本。
- 三均線減碼與補回採FIFO批次成本；不憑空回補超過現金或大盤水位允許的資金。持股追蹤支援自行記錄加碼批次；提示不是自動下單。
- 還原因子來源取得不代表特殊分割、合併等事件全部涵蓋；還原後超過25%跳價會拒絕一般回測，僅明確開啟研究模式可繼續。歷史處置／全額交割／停券與下市樣本不完整，仍有存活者偏差。
- 33種圖像、切線、ABC、軌道與主觀位置明列數值近似；圓弧以雙底代理，新聞題材與分時需人工確認。**沒有宣稱33圖逐例精確辨識或原書全部示例均已通過黃金驗收。** 詳見 [規則核對](docs/RULE_VALIDATION.md)。
- 樣本外預設末段30%從現金開始。多次挑選參數後，同一保留期間不能再視為未接觸樣本。書中獲利方程式為簡化加總，與含部位／成本的權益曲線算法不同。

## 驗證

```powershell
.venv\Scripts\python.exe -m pytest -q
npm run build
.venv\Scripts\python.exe -m scripts.verify_live
```

測試包含因果性、成本與FIFO結算、停損、次日成交、不得當沖、API輸入、通知佇列及原書漢磊3707的12個進出價／MA5狀態。原書報告45.6%；用實際12個收盤價精算為7.65元／45.9%，差異為書中中間數字取位，不把錯誤算式寫進引擎。這個書本收盤算法驗證與網站次日開盤回測分開。

原始書頁在專案外，Git僅保存筆記、程式與少量公開行情測試樣本。完整規劃見 [PLAN](docs/PLAN_策略網站.md)，均量設定依據見 [VOLUME_FILTER](docs/VOLUME_FILTER.md)。
