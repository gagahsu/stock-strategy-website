# 技術分析策略網站

台股上市櫃個人研究工具：每日選股掃描、個股診斷、策略回測、鎖股清單、持股追蹤與 LINE 出場提醒。

## 目前狀態

專案初始化：規劃、規則筆記與設定已入庫。P0 資料抓取與應用程式尚未建置。

- [完整規劃](docs/PLAN_策略網站.md)
- [規則筆記](docs/notes/)
- [預設設定](config/defaults.json)

規劃技術：Python 資料與策略引擎、FastAPI、Next.js 前端；資料庫與部署依規劃後續實作。

## 已確認設定

- 只供自己使用；台股上市櫃、多空雙向。
- 初階目標管理：月目標 2%；回測初始資金新臺幣 300,000 元。
- 排除全額交割與處置股，ETF 與 KY 不預設排除。
- 成交量採近 20 個交易日日均量至少 1,000 張，含訊號當日已收盤資料；期間與門檻可調。資料不足完整 20 日時標示不足，不納入候選。此為依常用均量算法與書中流動性門檻選定的專案預設，非市場統一標準；詳見 [研究依據](docs/VOLUME_FILTER.md)。
- 手續費基準 0.1425%、預設 2.8 折，即每邊 0.0399%。後續介面需支援自訂費率與多券商方案；第一版不含當沖。
- 策略停損與最大虧損上限先觸發先出場。上限預設 10%，後續介面需可修改並保存，回測需記錄實際使用的參數。
- 通知採 LINE 官方帳號 Messaging API，目前未接通。

`config/defaults.json` 是待實作的預設設定資料，不代表相關功能或設定介面已完成。費率目前尚未包含最低手續費、證交稅與融券成本；完整成本模型於 P4 建置。

## 本機設定

複製 `.env.example` 為 `.env`，於需要時填入資料來源、資料庫及 LINE 設定。憑證只放本機環境或部署平台的秘密設定。

LINE 後續需要 Channel access token 與接收者 user ID；若啟用 webhook，另外設定 Channel secret 與簽章驗證。

- [LINE access token 文件](https://developers.line.biz/en/docs/basics/channel-access-token/)
- [取得 user ID](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)

## 開發順序

P0 股票清單、歷史日K與每日增量、除權息及還原價 → P1 特徵與規則驗證 → P2 個股診斷 → P3 掃描與鎖股 → P4 回測 → P5 持股與通知。

原始書頁截圖留在專案外，Git 僅保存文字規劃與規則筆記。
