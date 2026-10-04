"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Chart from "./Chart";
import ScanFilters from "./ScanFilters";
import OperationTour from "./OperationTour";

type Data = any;
const links = [
  ["/scan", "今日掃描", "收盤訊號與市場水位"],
  ["/watchlist", "鎖股清單", "追蹤候選股票與轉折"],
  ["/stock/2330", "個股診斷", "K線、型態與選股檢查"],
  ["/backtest", "策略回測", "檢驗策略、成本與風險"],
  ["/portfolio", "持股追蹤", "部位、停損與目標管理"],
  ["/rules", "規則筆記", "查閱策略定義與判讀限制"],
  ["/settings", "偏好設定", "股票池、資金與交易成本"],
  ["/data", "資料管理", "更新資料與檢查完整性"],
];
const pct = (x: number | null | undefined) =>
  x == null ? "—" : `${(x * 100).toFixed(2)}%`;
const money = (x: number | null | undefined) =>
  x == null ? "—" : Math.round(x).toLocaleString("zh-TW");
async function api(path: string, method = "GET", body?: unknown) {
  const r = await fetch("/api/" + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
function useLoad(path: string) {
  const [data, setData] = useState<Data>(null),
    [error, setError] = useState("");
  const load = () =>
    api(path)
      .then(setData)
      .catch((e) => setError(e.message));
  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    const refresh = () =>
      api(path)
        .then((x) => {
          if (alive) setData(x);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    refresh();
    window.addEventListener("refresh-data", refresh);
    return () => {
      alive = false;
      window.removeEventListener("refresh-data", refresh);
    };
  }, [path]);
  return { data, error, load, setData };
}
function Empty({
  text = "目前沒有資料。可先到資料管理抓取日K，再執行掃描。",
}: {
  text?: string;
}) {
  return (
    <div className="empty">
      <span>◇</span>
      <p>{text}</p>
      <Link href="/data">前往資料管理 →</Link>
    </div>
  );
}
function Notice({ children }: { children: React.ReactNode }) {
  return <div className="notice">{children}</div>;
}
function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  );
}
function Tag({
  children,
  kind = "",
}: {
  children: React.ReactNode;
  kind?: string;
}) {
  return <span className={"tag " + kind}>{children}</span>;
}
function Checks({ rows }: { rows: Data[] }) {
  return (
    <div className="checks">
      {rows.map((x, i) => (
        <div key={i}>
          <span
            className={
              x.passed === true ? "ok" : x.passed === false ? "bad" : "muted"
            }
          >
            {x.passed === true ? "✓" : x.passed === false ? "×" : "?"}
          </span>
          <section>
            <b>{x.name}</b>
            <small>{x.reason}</small>
          </section>
          {x.hard && <Tag>必要條件</Tag>}
        </div>
      ))}
    </div>
  );
}
function Curve({ rows }: { rows: { date: string; equity: number }[] }) {
  if (!rows?.length) return null;
  const vals = rows.map((x) => x.equity),
    min = Math.min(...vals),
    max = Math.max(...vals);
  const path = rows
    .map(
      (x, i) =>
        `${i ? "L" : "M"}${(i / (rows.length - 1 || 1)) * 900},${190 - ((x.equity - min) / (max - min || 1)) * 170}`,
    )
    .join(" ");
  return (
    <div className="curve">
      <svg viewBox="0 0 900 210" role="img" aria-label="回測資金曲線">
        <defs>
          <linearGradient id="fill" x1="0" x2="0" y1="0" y2="1">
            <stop stopColor="#002fa7" stopOpacity=".14" />
            <stop offset="1" stopColor="#002fa7" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={path + " L900,210 L0,210 Z"} fill="url(#fill)" />
        <path d={path} fill="none" stroke="#002fa7" strokeWidth="2" />
      </svg>
      <div className="between muted">
        <span>{rows[0].date}</span>
        <span>{rows[rows.length - 1].date}</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const path = usePathname(),
    title =
      links.find((x) =>
        path.startsWith(
          x[0].split("/")[1] ? "/" + x[0].split("/")[1] : "/scan",
        ),
      )?.[1] || "今日掃描";
  const [search, setSearch] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [refresh, setRefresh] = useState(0);
  const status = useLoad("status");
  const notify = (text: string) => {
    setMessage(text);
  };
  async function action(fn: () => Promise<Data>) {
    setBusy(true);
    setMessage("");
    try {
      const result = await fn();
      if (result?.job_id) {
        notify("工作已排入，正在處理…");
        let job;
        do {
          await new Promise((r) => setTimeout(r, 1500));
          job = await api("jobs/" + result.job_id);
        } while (["queued", "running"].includes(job.status));
        if (job.status === "failed") throw new Error(job.error);
        notify("處理完成");
      } else notify("已保存");
      setRefresh((x) => x + 1);
      window.dispatchEvent(new Event("refresh-data"));
      status.load();
      return result;
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="shell">
      <aside>
        <Link href="/scan" className="brand">
          <span className="brandmark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none">
              <path
                d="M5 25V7M5 25H27M9 20L15 14L20 17L27 8"
                stroke="currentColor"
                strokeWidth="2.3"
              />
              <path d="M21 8H27V14" stroke="currentColor" strokeWidth="2.3" />
            </svg>
          </span>
          <div>
            選股研究室<small>台股策略 · 個人研究</small>
          </div>
        </Link>
        <div className="side-label">研究與交易紀律</div>
        <nav aria-label="主要導覽">
          {links.map(([href, label], index) => (
            <Link
              key={href}
              className={
                path.startsWith("/" + href.split("/")[1]) ||
                (path === "/" && href === "/scan")
                  ? "active"
                  : ""
              }
              href={href}
              aria-current={
                path.startsWith("/" + href.split("/")[1]) ||
                (path === "/" && href === "/scan")
                  ? "page"
                  : undefined
              }
            >
              <span className="nav-index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="nav-title">{label}</span>
            </Link>
          ))}
        </nav>
        <div className="side-foot">
          <span className="dot" /> 個人研究模式<p>收盤資料 · 台股上市櫃</p>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="eyebrow">台股上市櫃 / 收盤研究</div>
            <h1>{title}</h1>
            <p className="page-description">
              {links.find((x) =>
                path.startsWith("/" + x[0].split("/")[1]),
              )?.[2] || links[0][2]}
            </p>
          </div>
          <div className="header-tools">
            <form
              className="search"
              onSubmit={(e) => {
                e.preventDefault();
                if (search.trim())
                  location.href = "/stock/" + encodeURIComponent(search.trim());
              }}
            >
              <input
                aria-label="搜尋股票代號"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="輸入股票代號，例如 2330"
              />
              <button aria-label="查詢股票">
                <svg
                  viewBox="0 0 24 24"
                  width="18"
                  height="18"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle
                    cx="10.5"
                    cy="10.5"
                    r="6"
                    stroke="currentColor"
                    strokeWidth="1.8"
                  />
                  <path
                    d="m15 15 5 5"
                    stroke="currentColor"
                    strokeWidth="1.8"
                  />
                </svg>
              </button>
            </form>
            <OperationTour path={path} />
          </div>
        </header>
        <div className="topline">
          <span>資料範圍：收盤日K · 上市與上櫃</span>
          <small>已載入 {money(status.data?.bars)} 根日K</small>
        </div>
        {message && (
          <div role="status" className="message">
            <span>
              {busy ? "◌" : "✓"} {message}
            </span>
            <button onClick={() => setMessage("")}>關閉</button>
          </div>
        )}
        {status.error && <Notice>{status.error}</Notice>}
        <div data-tour="page">
          {(path === "/" || path === "/scan") && (
            <Scan action={action} busy={busy} />
          )}
          {path === "/watchlist" && <Watchlist action={action} busy={busy} />}
          {path.startsWith("/stock/") && (
            <StockPage
              sid={decodeURIComponent(path.split("/")[2])}
              action={action}
              busy={busy}
            />
          )}
          {path === "/backtest" && <Backtest action={action} busy={busy} />}
          {path === "/portfolio" && <Portfolio action={action} busy={busy} />}
          {path === "/rules" && <Rules />}
          {path === "/settings" && <Settings action={action} busy={busy} />}
          {path === "/data" && (
            <DataPage status={status.data} action={action} busy={busy} />
          )}
        </div>
        <footer>
          個人研究工具 · 訊號與型態包含明列的數值近似，請核對資料與規則定義。
          <a
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noreferrer"
          >
            圖表由 TradingView Lightweight Charts 提供
          </a>
        </footer>
      </main>
    </div>
  );
}
type Actions = {
  action: (fn: () => Promise<Data>) => Promise<Data>;
  busy: boolean;
};
function Scan({ action, busy }: Actions) {
  const { data, error } = useLoad("scan");
  const [tab, setTab] = useState("all");
  const [filters, setFilters] = useState<any>({
    minChange: -100,
    minVolumeRatio: 0,
    eligibleOnly: false,
    rulePrefix: "",
  });
  if (!data && !error) return <div className="empty">讀取掃描結果中…</div>;
  const rows = (data?.rows || [])
    .filter(
      (x: Data) =>
        tab === "all" ||
        (tab === "long" &&
          x.signals.some((s: Data) => s.direction === "long")) ||
        (tab === "short" &&
          x.signals.some((s: Data) => s.direction === "short")) ||
        (tab === "watch" && !x.eligible),
    )
    .filter(
      (x: Data) =>
        (x.change ?? 0) * 100 >= filters.minChange &&
        (x.volume_ratio ?? 0) >= filters.minVolumeRatio &&
        (!filters.eligibleOnly ||
          (tab === "short"
            ? x.eligible_short
            : tab === "long"
              ? x.eligible_long
              : x.eligible)) &&
        (!filters.rulePrefix ||
          x.signals.some(
            (s: Data) =>
              s.id.startsWith(filters.rulePrefix) ||
              (filters.rulePrefix.startsWith("L-") &&
                s.id.startsWith("S-" + filters.rulePrefix.slice(2))),
          )),
    );
  return (
    <>
      <div className="stats">
        <Stat
          label="大盤狀態"
          value={data?.market?.state || "尚未掃描"}
          note={data?.market?.date}
        />
        <Stat
          label="建議投入比例"
          value={pct(data?.market?.allocation)}
          note="依大盤水位表"
        />
        <Stat
          label="已掃描股票"
          value={money(data?.rows?.length)}
          note="至少60根日K"
        />
        <Stat
          label="濾網候選"
          value={money(
            data?.rows?.filter((x: Data) => x.eligible && x.signals.length)
              .length,
          )}
          note="必要濾網通過，人工項仍須核對"
        />
      </div>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>收盤後訊號</h2>
            <small>
              {data?.updated_at
                ? new Date(data.updated_at).toLocaleString("zh-TW", {
                    timeZone: "Asia/Taipei",
                  })
                : "尚無掃描結果"}
            </small>
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={() => action(() => api("scan", "POST"))}
          >
            執行全市場掃描
          </button>
        </div>
        <div className="tabs">
          {[
            ["all", "全部"],
            ["long", "做多訊號"],
            ["short", "做空訊號"],
            ["watch", "待確認"],
          ].map(([v, l]) => (
            <button
              className={v === tab ? "selected" : ""}
              key={v}
              onClick={() => setTab(v)}
            >
              {l}
            </button>
          ))}
        </div>
        <ScanFilters onChange={setFilters} />
        {error && <Notice>{error}</Notice>}
        {!rows.length ? (
          <Empty />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>股票 / 類股</th>
                  <th>收盤</th>
                  <th>漲跌</th>
                  <th>量比</th>
                  <th>20日報酬</th>
                  <th>訊號與狀態</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((x: Data) => (
                  <tr key={x.id}>
                    <td>
                      <Link className="stocklink" href={"/stock/" + x.id}>
                        {x.id} {x.name}
                      </Link>
                      <small>{x.industry}</small>
                    </td>
                    <td>{x.close.toFixed(2)}</td>
                    <td className={x.change >= 0 ? "up" : "down"}>
                      {pct(x.change)}
                    </td>
                    <td>{x.volume_ratio?.toFixed(2) || "—"}×</td>
                    <td>{pct(x.return20)}</td>
                    <td>
                      <Tag kind={x.eligible ? "success" : "neutral"}>
                        {x.eligible ? "濾網通過" : "必要條件待確認"}
                      </Tag>
                      <small>
                        {x.signals
                          .slice(0, 2)
                          .map((s: Data) => s.name)
                          .join("、") || "未觸發"}
                      </small>
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(() =>
                            api("watchlist", "POST", { stock_id: x.id }),
                          )
                        }
                      >
                        ＋鎖股
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="two-col">
        <div className="panel">
          <h2>強勢類股</h2>
          {(data?.industry_ranks || [])
            .slice(0, 3)
            .map((x: Data, i: number) => (
              <div className="rank" key={x.industry}>
                <b>0{i + 1}</b>
                <span>
                  {x.industry}
                  <small>{x.stocks}檔有資料</small>
                </span>
                <strong className="up">{pct(x.return20)}</strong>
              </div>
            ))}
        </div>
        <div className="panel">
          <h2>收盤後工作</h2>
          <p className="muted">
            先看漲跌幅 ≥3.5%
            與放量股，再依趨勢、位置、量價、週線與支撐壓力檢查。
          </p>
          <div className="chips">
            <Tag>六六大順</Tag>
            <Tag>4基10技</Tag>
            <Tag>淘汰法</Tag>
            <Tag>12口訣</Tag>
          </div>
          <Link href="/rules">查看規則與出處 →</Link>
        </div>
      </div>
    </>
  );
}
function Watchlist({ action, busy }: Actions) {
  const { data, error } = useLoad("watchlist");
  const [id, setId] = useState(""),
    [reason, setReason] = useState("手動鎖股");
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>鎖股資料夾</h2>
            <small>底部觀察、強勢第2波與手動追蹤</small>
          </div>
        </div>
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            action(() => api("watchlist", "POST", { stock_id: id, reason }));
          }}
        >
          <label>
            股票代號
            <input
              value={id}
              onChange={(e) => setId(e.target.value)}
              required
              placeholder="例如 8054"
            />
          </label>
          <label>
            入選理由
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button className="primary" disabled={busy}>
            加入鎖股
          </button>
        </form>
        {error && <Notice>{error}</Notice>}
        {!data?.length ? (
          <Empty text="尚未加入鎖股。可手動加入，或執行掃描自動收錄底部觀察訊號。" />
        ) : (
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label="鎖股清單，可橫向捲動"
          >
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>入選理由</th>
                  <th>收盤</th>
                  <th>相對強弱</th>
                  <th>最新訊號</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.map((x: Data) => (
                  <tr key={x.key}>
                    <td>
                      <Link href={"/stock/" + x.key}>
                        {x.key} {x.name}
                      </Link>
                    </td>
                    <td>
                      {x.reason}
                      <small>
                        {x.active === false
                          ? "趨勢轉空，已移出候選"
                          : x.automatic
                            ? "自動入選"
                            : "手動入選"}
                      </small>
                    </td>
                    <td>{x.scan.close || "資料不足"}</td>
                    <td>{pct(x.scan.relative_strength)}</td>
                    <td>
                      {x.scan.signals
                        ?.map((s: Data) => s.name)
                        .slice(0, 2)
                        .join("、") || "等待突破"}
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(() => api("watchlist/" + x.key, "DELETE"))
                        }
                      >
                        移除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
function StockPage({ sid, action, busy }: Actions & { sid: string }) {
  const [period, setPeriod] = useState("day");
  const [end, setEnd] = useState("");
  useEffect(() => {
    setEnd(new URLSearchParams(window.location.search).get("end") || "");
  }, [sid]);
  const { data, error } = useLoad(
    `stock/${sid}?period=${period}${end ? "&end=" + end : ""}`,
  );
  if (error) return <Notice>{error}</Notice>;
  if (!data) return <div className="empty">正在讀取個股資料…</div>;
  const last = data.bars.at(-1);
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>
              {sid} {data.stock.name}{" "}
              <Tag>{data.stock.market.toUpperCase()}</Tag>
            </h2>
            <small>
              {data.stock.industry} · {data.data_quality.last_date || "尚無日K"}
            </small>
          </div>
          <button
            disabled={busy}
            onClick={() =>
              action(() => api("watchlist", "POST", { stock_id: sid }))
            }
          >
            ＋加入鎖股
          </button>
        </div>
        {data.data_quality.warning && (
          <Notice>{data.data_quality.warning}</Notice>
        )}
        <div className="stockquote">
          <strong>{last?.raw_close?.toFixed(2) || "—"}</strong>
          <span className={last?.change >= 0 ? "up" : "down"}>
            {pct(last?.change)}
          </span>
          <span className="muted">成交量 {money(last?.volume / 1000)} 張</span>
        </div>
        <div className="tabs">
          {[
            ["day", "日線"],
            ["week", "週線"],
            ["month", "月線"],
          ].map(([v, l]) => (
            <button
              key={v}
              className={period === v ? "selected" : ""}
              onClick={() => setPeriod(v)}
            >
              {l}
            </button>
          ))}
        </div>
        {data.bars.length ? (
          <Chart
            bars={data.bars}
            signals={data.historical_signals || data.signals}
            gaps={data.gaps}
          />
        ) : (
          <Empty text="此股票尚無歷史日K，可在資料管理輸入代號進行回補。" />
        )}
        <div className="chips">
          <Tag>MA5</Tag>
          <Tag>MA10</Tag>
          <Tag>MA20</Tag>
          <Tag>MA60</Tag>
          <Tag>量：張</Tag>
        </div>
      </div>
      <div className="two-col">
        <div className="panel">
          <h2>六六大順與選股評量</h2>
          <p className="muted">
            以日線檢查股票池與每日工作；日週月評量另見下表。
          </p>
          <Checks rows={data.checks} />
        </div>
        <div>
          <div className="panel">
            <h2>觸發規則</h2>
            {data.signals.length ? (
              data.signals.map((x: Data) => (
                <div className="signal" key={x.id}>
                  <b>{x.name}</b>
                  {x.approximate && <Tag>數值近似</Tag>}
                  <p>{x.reason}</p>
                  <small>
                    {x.id} · Part{x.chapter}
                  </small>
                </div>
              ))
            ) : (
              <p className="muted">未觸發進場或警示條件。</p>
            )}
          </div>
          <div className="panel">
            <h2>缺口與封口狀態</h2>
            {data.gaps.slice(-5).map((x: Data) => (
              <div className="signal" key={x.date}>
                <b>
                  {x.date} {x.direction === "up" ? "向上" : "向下"}缺口
                </b>
                <p>
                  {x.lower.toFixed(2)} — {x.upper.toFixed(2)} · {x.status}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="panel">
        <h2>4基10技・日週月評量表</h2>
        <Checks rows={data.assessment?.fundamental || []} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>評量項目</th>
                <th>目前狀態</th>
                <th>判讀依據</th>
              </tr>
            </thead>
            <tbody>
              {data.assessment?.technical.map((x: Data) => (
                <tr key={x.name}>
                  <td>{x.name}</td>
                  <td>
                    {x.value == null
                      ? "資料不足"
                      : typeof x.value === "number"
                        ? x.value.toLocaleString("zh-TW", {
                            maximumFractionDigits: 2,
                          })
                        : x.value}
                  </td>
                  <td>{x.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel">
        <h2>基本面與籌碼資料</h2>
        <div className="two-col">
          {Object.entries(data.context).map(([key, value]) => (
            <details key={key}>
              <summary>
                {
                  (
                    {
                      fundamentals: "月營收",
                      financials: "財報",
                      chips_daily: "三大法人",
                      margin_daily: "融資融券",
                    } as Data
                  )[key]
                }{" "}
                · {(value as Data[]).length} 筆
              </summary>
              <pre>{JSON.stringify(value, null, 2)}</pre>
            </details>
          ))}
        </div>
      </div>
    </>
  );
}
function Backtest({ action, busy }: Actions) {
  const rules = useLoad("rules"),
    settings = useLoad("settings"),
    runs = useLoad("backtests");
  const initializedBroker = useRef(false);
  const [result, setResult] = useState<Data>(null),
    [form, setForm] = useState<Data>({
      stock_ids: "2330,2317,2454",
      start: "2024-01-01",
      end: new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Taipei" }),
      rule_id: "L-ENTRY-4",
      extra_rule_ids: [],
      stop_method: "fixed",
      direction: "long",
      exit_mode: "swing",
      max_positions: 2,
      capital_model: "fixed",
      allocation: 0.7,
      market_filter: true,
      elimination_filter: true,
      allow_unadjusted: false,
      broker_profile_id: "default",
      slippage: 0.001,
      sell_tax_rate: 0.003,
      annual_short_borrow_rate: 0.03,
    });
  const set = (k: string, v: Data) =>
    setForm((previous: Data) => ({ ...previous, [k]: v }));
  useEffect(() => {
    if (settings.data && !initializedBroker.current) {
      initializedBroker.current = true;
      setForm((previous: Data) => ({
        ...previous,
        broker_profile_id: settings.data.backtest.broker_profile_id,
      }));
    }
  }, [settings.data]);
  if (settings.error || rules.error)
    return <Notice>{settings.error || rules.error}</Notice>;
  if (!settings.data || !rules.data)
    return <div className="empty">讀取策略規則與券商設定中…</div>;
  async function run() {
    const resp = await action(() =>
      api("backtests", "POST", {
        ...form,
        stock_ids: form.stock_ids
          .split(",")
          .map((x: string) => x.trim())
          .filter(Boolean),
        rule_ids: [...new Set([form.rule_id, ...form.extra_rule_ids])],
        initial_capital: settings.data?.backtest.initial_capital || 300000,
      }),
    );
    if (resp?.run_id) {
      try {
        setResult(await api("backtests/" + resp.run_id));
      } catch {}
    }
  }
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>組合策略，驗證紀律</h2>
            <small>
              收盤訊號次日成交 · 本金{" "}
              {money(settings.data?.backtest.initial_capital || 300000)} 元
            </small>
          </div>
          <button className="primary" disabled={busy} onClick={run}>
            {busy ? "計算中…" : "執行回測"}
          </button>
          <button
            disabled={busy}
            onClick={() =>
              action(() =>
                api("backtest-comparison", "POST", {
                  base: {
                    ...form,
                    stock_ids: form.stock_ids
                      .split(",")
                      .map((x: string) => x.trim())
                      .filter(Boolean),
                    rule_ids: [
                      ...new Set([form.rule_id, ...form.extra_rule_ids]),
                    ],
                    initial_capital:
                      settings.data?.backtest.initial_capital || 300000,
                  },
                  stop_ratios: [0.03, 0.05, 0.07],
                  exit_modes: ["swing", "long", "kline"],
                }),
              )
            }
          >
            比較3種停損 × 3種出場
          </button>
        </div>
        <div className="form-grid">
          <label>
            股票池（逗號分隔）
            <input
              value={form.stock_ids}
              onChange={(e) => set("stock_ids", e.target.value)}
            />
          </label>
          <label>
            開始日期
            <input
              type="date"
              value={form.start}
              onChange={(e) => set("start", e.target.value)}
            />
          </label>
          <label>
            結束日期
            <input
              type="date"
              value={form.end}
              onChange={(e) => set("end", e.target.value)}
            />
          </label>
          <label>
            進場規則
            <select
              value={form.rule_id}
              onChange={(e) => set("rule_id", e.target.value)}
            >
              {rules.data
                ?.filter((x: Data) => x.direction === form.direction)
                .map((x: Data) => (
                  <option key={x.id} value={x.id}>
                    {x.id} · {x.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            方向
            <select
              value={form.direction}
              onChange={(e) => {
                setForm({
                  ...form,
                  direction: e.target.value,
                  extra_rule_ids: [],
                  rule_id:
                    e.target.value === "long" ? "L-ENTRY-4" : "S-ENTRY-4",
                });
              }}
            >
              <option value="long">做多</option>
              <option value="short">做空（研究模擬）</option>
            </select>
          </label>
          <label>
            出場模組
            <select
              value={form.exit_mode}
              onChange={(e) => set("exit_mode", e.target.value)}
            >
              {[
                ["swing", "短線守MA5"],
                ["long", "長線守MA20"],
                ["hot", "飆股續抱"],
                ["scale", "三均線分批"],
                ["kline", "K線戰法"],
                ["ma5", "MA5單一均線"],
                ["ma10", "MA10單一均線"],
              ].map(([v, l]) => (
                <option value={v} key={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            停損設定方法
            <select
              value={form.stop_method}
              onChange={(e) => set("stop_method", e.target.value)}
            >
              {[
                ["fixed", "固定比例（依設定）"],
                ["kline", "訊號K低／高點"],
                ["trend", "已確認轉折低／高點"],
                ["ma", "訊號日MA5"],
                ["support", "突破頸線／支阻"],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            最多持有檔數
            <input
              type="number"
              min="1"
              max="5"
              value={form.max_positions}
              onChange={(e) => set("max_positions", +e.target.value)}
            />
          </label>
          <label>
            券商費率
            <select
              value={form.broker_profile_id}
              onChange={(e) => set("broker_profile_id", e.target.value)}
            >
              {settings.data?.broker_profiles.map((x: Data) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            資金模型
            <select
              value={form.capital_model}
              onChange={(e) => set("capital_model", e.target.value)}
            >
              <option value="fixed">固定投入比例</option>
              <option value="market">大盤水位表</option>
            </select>
          </label>
          <label>
            固定投入比例 %
            <input
              type="number"
              min="1"
              max="90"
              value={form.allocation * 100}
              onChange={(e) => set("allocation", +e.target.value / 100)}
            />
          </label>
          <label>
            單邊滑價 %
            <input
              type="number"
              min="0"
              step=".01"
              value={form.slippage * 100}
              onChange={(e) => set("slippage", +e.target.value / 100)}
            />
          </label>
          <label>
            賣出稅率 %
            <input
              type="number"
              min="0"
              step=".01"
              value={form.sell_tax_rate * 100}
              onChange={(e) => set("sell_tax_rate", +e.target.value / 100)}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.market_filter}
              onChange={(e) => set("market_filter", e.target.checked)}
            />
            啟用大盤濾網
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.elimination_filter}
              onChange={(e) => set("elimination_filter", e.target.checked)}
            />
            啟用淘汰法可計算項（未知項須人工核對）
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.allow_unadjusted}
              onChange={(e) => set("allow_unadjusted", e.target.checked)}
            />
            允許未驗證還原價（僅研究）
          </label>
        </div>
        <details>
          <summary>組合更多進場規則（任一成立）</summary>
          <div className="form-grid">
            {rules.data
              ?.filter(
                (x: Data) =>
                  x.direction === form.direction && x.id !== form.rule_id,
              )
              .map((x: Data) => (
                <label className="checkbox" key={x.id}>
                  <input
                    type="checkbox"
                    checked={form.extra_rule_ids.includes(x.id)}
                    onChange={(e) =>
                      set(
                        "extra_rule_ids",
                        e.target.checked
                          ? [...form.extra_rule_ids, x.id]
                          : form.extra_rule_ids.filter(
                              (id: string) => id !== x.id,
                            ),
                      )
                    }
                  />
                  {x.name}
                </label>
              ))}
          </div>
        </details>
      </div>
      {result && (
        <>
          <div className="panel">
            <h2>樣本外期間</h2>
            <p className="muted">
              {result.out_of_sample?.label || "期間資料不足，尚無樣本外结果。"}
            </p>
            {result.out_of_sample && (
              <div className="stats">
                <Stat
                  label="樣本外總報酬"
                  value={pct(result.out_of_sample.summary.total_return)}
                />
                <Stat
                  label="樣本外最大回撤"
                  value={pct(result.out_of_sample.summary.max_drawdown)}
                />
                <Stat
                  label="樣本外勝率"
                  value={pct(result.out_of_sample.summary.win_rate)}
                />
                <Stat
                  label="樣本外交易次數"
                  value={money(result.out_of_sample.summary.trades)}
                />
              </div>
            )}
          </div>
          <div className="stats">
            <Stat label="總報酬" value={pct(result.summary.total_return)} />
            <Stat label="最大回撤" value={pct(result.summary.max_drawdown)} />
            <Stat label="勝率" value={pct(result.summary.win_rate)} />
            <Stat label="交易筆數" value={money(result.summary.trades)} />
          </div>
          <div className="panel">
            <h2>資金曲線</h2>
            <Curve rows={result.equity} />
            <Notice>
              {result.execution}
              <br />
              {result.warnings.join(" ")}
            </Notice>
            <button
              onClick={() => {
                const blob = new Blob([JSON.stringify(result, null, 2)], {
                  type: "application/json",
                });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "backtest.json";
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              下載完整結果
            </button>
          </div>
          <div className="panel">
            <h2>5種獲利方程式對照</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>書中年次數</th>
                    <th>目標勝率</th>
                    <th>書中年獲利</th>
                    <th>實際年化次數</th>
                    <th>實際勝率</th>
                    <th>實際年化報酬</th>
                  </tr>
                </thead>
                <tbody>
                  {result.benchmarks.map((x: Data, i: number) => (
                    <tr key={i}>
                      <td>{x.trades}</td>
                      <td>{pct(x.win_rate)}</td>
                      <td>{pct(x.book_return)}</td>
                      <td>{x.actual_trades_per_year.toFixed(1)}</td>
                      <td>{pct(x.actual_win_rate)}</td>
                      <td>{pct(x.actual_annual_return)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <small>
              書中報酬為简化加總，與含資金配置、成本及複利的實際回測不同。
            </small>
          </div>
          <div className="panel">
            <h2>逐筆交易</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>股票</th>
                    <th>進場日</th>
                    <th>出場日</th>
                    <th>進／出還原價格</th>
                    <th>淨損益</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((x: Data, i: number) => (
                    <tr key={i}>
                      <td>
                        <Link
                          href={"/stock/" + x.stock_id + "?end=" + x.exit_date}
                        >
                          {x.stock_id}
                        </Link>
                      </td>
                      <td>{x.entry_date}</td>
                      <td>{x.exit_date}</td>
                      <td>
                        {x.entry_price.toFixed(2)} / {x.exit_price.toFixed(2)}
                      </td>
                      <td className={x.net_pnl >= 0 ? "up" : "down"}>
                        {money(x.net_pnl)}
                      </td>
                      <td>{x.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
      <div className="panel">
        <h2>已保存回測與策略比較</h2>
        {runs.data?.length ? (
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label="已保存回測與策略比較，可橫向捲動"
          >
            <table>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>策略停損</th>
                  <th>區間</th>
                  <th>報酬</th>
                  <th>回撤</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.data.map((x: Data) => (
                  <tr key={x.id}>
                    <td>
                      {x.params.exit_mode} · {x.params.rule_ids?.join(",")}
                    </td>
                    <td>
                      {x.params.stop_method || "fixed"} ·{" "}
                      {pct(
                        x.params.settings_snapshot?.risk.strategy_stop_ratio,
                      )}
                    </td>
                    <td>
                      {x.params.start} — {x.params.end}
                    </td>
                    <td>{pct(x.summary.total_return)}</td>
                    <td>{pct(x.summary.max_drawdown)}</td>
                    <td>
                      <button
                        onClick={() =>
                          action(async () => {
                            setResult(await api("backtests/" + x.id));
                            return null;
                          })
                        }
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">執行多組策略後，會在這裡保留結果供比較。</p>
        )}
      </div>
    </>
  );
}
function Portfolio({ action, busy }: Actions) {
  const { data, error } = useLoad("portfolio");
  const alerts = useLoad("alerts");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Data>({
    stock_id: "",
    entry_date: new Date().toLocaleDateString("sv-SE", {
      timeZone: "Asia/Taipei",
    }),
    entry_price: "",
    shares: "1000",
    direction: "long",
    stop_price: "",
    exit_mode: "swing",
    scaled_fraction: 0,
  });
  const [month, setMonth] = useState(
      new Date()
        .toLocaleDateString("sv-SE", { timeZone: "Asia/Taipei" })
        .slice(0, 7),
    ),
    [ret, setRet] = useState("");
  const set = (k: string, v: Data) =>
    setForm((previous: Data) => ({ ...previous, [k]: v }));
  return (
    <>
      <div className="stats">
        <Stat label="持股投入" value={"NT$ " + money(data?.invested)} />
        <Stat label="未實現損益" value={"NT$ " + money(data?.unrealized_pnl)} />
        <Stat label="目前投入比例" value={pct(data?.allocation)} />
        <Stat
          label="每月目標"
          value={pct(data?.target.monthly_target_return)}
          note="初階目標管理"
        />
      </div>
      <div className="panel">
        <div className="panel-head">
          <h2>持股與出場紀律</h2>
          <button
            className="primary"
            disabled={busy}
            onClick={() => action(() => api("portfolio/review", "POST"))}
          >
            檢查持股與通知
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action(() =>
              api(
                editingId ? "portfolio/" + editingId : "portfolio",
                editingId ? "PUT" : "POST",
                {
                  ...form,
                  entry_price: +form.entry_price,
                  shares: +form.shares,
                  stop_price: form.stop_price ? +form.stop_price : null,
                },
              ),
            ).then((saved) => {
              if (saved) setEditingId(null);
            });
          }}
        >
          <div className="form-grid">
            <label>
              股票代號
              <input
                required
                value={form.stock_id}
                onChange={(e) => set("stock_id", e.target.value)}
              />
            </label>
            <label>
              進場日期
              <input
                type="date"
                required
                value={form.entry_date}
                onChange={(e) => set("entry_date", e.target.value)}
              />
            </label>
            <label>
              進場價格
              <input
                type="number"
                required
                min=".01"
                step=".01"
                value={form.entry_price}
                onChange={(e) => set("entry_price", e.target.value)}
              />
            </label>
            <label>
              股數
              <input
                type="number"
                required
                min="1"
                value={form.shares}
                onChange={(e) => set("shares", e.target.value)}
              />
            </label>
            <label>
              方向
              <select
                value={form.direction}
                onChange={(e) => set("direction", e.target.value)}
              >
                <option value="long">多單</option>
                <option value="short">空單</option>
              </select>
            </label>
            <label>
              策略停損價格（選填）
              <input
                type="number"
                min=".01"
                step=".01"
                value={form.stop_price}
                onChange={(e) => set("stop_price", e.target.value)}
                placeholder="空白採設定比例"
              />
            </label>
            <label>
              出場模組
              <select
                value={form.exit_mode}
                onChange={(e) => set("exit_mode", e.target.value)}
              >
                <option value="swing">短線</option>
                <option value="long">長線</option>
                <option value="hot">飆股</option>
                <option value="kline">K線戰法</option>
                <option value="scale">三均線分批</option>
                <option value="ma5">MA5單一均線</option>
                <option value="ma10">MA10單一均線</option>
              </select>
            </label>
            {form.exit_mode === "scale" && (
              <label>
                已減碼比例 %
                <input
                  type="number"
                  min="0"
                  max="99"
                  value={(form.scaled_fraction || 0) * 100}
                  onChange={(e) =>
                    set("scaled_fraction", +e.target.value / 100)
                  }
                />
              </label>
            )}
            <button className="primary" disabled={busy}>
              {editingId ? "保存持股修改" : "新增持股"}
            </button>
            {editingId && (
              <button type="button" onClick={() => setEditingId(null)}>
                取消編輯
              </button>
            )}
          </div>
        </form>
        {error && <Notice>{error}</Notice>}
        {!data?.rows.length ? (
          <Empty text="尚無持股。輸入实际進場資料後，系統依每日收盤檢查出場規則。" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>進場價 / 股數</th>
                  <th>報酬</th>
                  <th>建議動作</th>
                  <th>監控</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((x: Data) => (
                  <tr key={x.id}>
                    <td>
                      <Link href={"/stock/" + x.stock_id}>
                        {x.stock_id} {x.name}
                      </Link>
                    </td>
                    <td>
                      {x.entry_price} / {money(x.shares)}
                    </td>
                    <td className={x.return >= 0 ? "up" : "down"}>
                      {pct(x.return)}
                    </td>
                    <td>
                      <b>
                        {{
                          hold: "續抱",
                          reduce: "減碼",
                          exit: "出場",
                          restore: "補回建議",
                        }[
                          x.action?.action as
                            "hold" | "reduce" | "exit" | "restore"
                        ] || "資料不足"}
                      </b>
                      <small>{x.action?.reason}</small>
                    </td>
                    <td>
                      {x.trapped_warning && <Tag>跌幅超過5%</Tag>}
                      {x.slow_stock && <Tag>牛步股換股提示</Tag>}
                      {x.add_on_hint && <Tag>可觀察加碼位置</Tag>}
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() => {
                          setEditingId(x.id);
                          setForm({
                            stock_id: x.stock_id,
                            entry_date: x.entry_date,
                            entry_price: x.entry_price,
                            shares: x.shares,
                            direction: x.direction,
                            stop_price: x.stop_price || "",
                            exit_mode: x.exit_mode,
                            scaled_fraction: x.scaled_fraction || 0,
                          });
                        }}
                      >
                        編輯
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(() => api("portfolio/" + x.id, "DELETE"))
                        }
                      >
                        移除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="two-col">
        <div className="panel">
          <h2>每月目標管理</h2>
          <small>
            輸入含已實現損益的實際帳戶月報酬，避免僅用現有持股推估。
          </small>
          <form
            className="form-row"
            onSubmit={(e) => {
              e.preventDefault();
              action(() =>
                api("monthly-return/" + month, "PUT", { return: +ret / 100 }),
              );
            }}
          >
            <label>
              月份
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                required
              />
            </label>
            <label>
              實際報酬 %
              <input
                type="number"
                step=".01"
                value={ret}
                onChange={(e) => setRet(e.target.value)}
                required
              />
            </label>
            <button disabled={busy}>保存</button>
          </form>
          {data?.monthly_returns.map((x: Data) => (
            <div className="rank" key={x.key}>
              <span>{x.key}</span>
              <strong>{pct(x.return)}</strong>
              <Tag>
                達成率 {pct(x.return / data.target.monthly_target_return)}
              </Tag>
            </div>
          ))}
        </div>
        <div className="panel">
          <h2>LINE 通知紀錄</h2>
          <button
            disabled={busy}
            onClick={() =>
              action(async () => {
                const r = await api("notifications/preview", "POST");
                alert(
                  r.length
                    ? r.map((x: Data) => x.text).join("\n")
                    : "目前沒有待發通知",
                );
                return null;
              })
            }
          >
            預覽待發通知
          </button>
          {alerts.data?.slice(0, 8).map((x: Data) => (
            <div className="signal" key={x.key}>
              <b>{x.text}</b>
              <small>
                {x.status} · {x.date}
              </small>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
function Rules() {
  const { data, error } = useLoad("rules");
  const [q, setQ] = useState(""),
    [note, setNote] = useState("");
  const rows = data?.filter((x: Data) =>
    (x.id + x.name + x.chapter).includes(q),
  );
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>每條訊號都有理由與出處</h2>
            <small>
              數值近似會明確標示；原圖尚未完成黃金測試時不宣稱精準重現。
            </small>
          </div>
          <input
            aria-label="搜尋規則"
            placeholder="搜尋規則、型態或章節"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="chips">
          {Array.from({ length: 11 }, (_, i) => i + 2).map((i) => (
            <button
              key={i}
              onClick={() =>
                api("notes/Part" + String(i).padStart(2, "0")).then((x) =>
                  setNote(x.text),
                )
              }
            >
              Part {i}
            </button>
          ))}
        </div>
        {note && (
          <details open>
            <summary>書本規則筆記</summary>
            <pre className="note-text">{note}</pre>
          </details>
        )}
        {error && <Notice>{error}</Notice>}
        <div className="rule-grid">
          {rows?.map((x: Data) => (
            <article key={x.id}>
              <div className="between">
                <code>{x.id}</code>
                <Tag kind={x.approximate ? "neutral" : "success"}>
                  {x.approximate ? "數值近似" : "明確條件"}
                </Tag>
              </div>
              <h3>{x.name}</h3>
              <p>{x.description}</p>
              <small>
                Part {x.chapter} ·{" "}
                {x.direction === "long"
                  ? "做多"
                  : x.direction === "short"
                    ? "做空"
                    : "警示"}
              </small>
            </article>
          ))}
        </div>
      </div>
    </>
  );
}
function Settings({ action, busy }: Actions) {
  const { data, setData, error } = useLoad("settings");
  if (error) return <Notice>{error}</Notice>;
  if (!data) return <div className="empty">讀取設定中…</div>;
  const update = (key: string, value: Data) =>
    setData({ ...data, [key]: value });
  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>你的策略預設</h2>
            <small>設定保存至資料庫；每次回測另留完整參數快照。</small>
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={() => action(() => api("settings", "PUT", data))}
          >
            保存設定
          </button>
        </div>
        <div className="form-grid">
          <label>
            回測初始資金（新臺幣）
            <input
              type="number"
              min="1"
              value={data.backtest.initial_capital}
              onChange={(e) =>
                update("backtest", {
                  ...data.backtest,
                  initial_capital: +e.target.value,
                })
              }
            />
          </label>
          <label>
            目標管理階段
            <select
              value={data.target_management.stage}
              onChange={(e) => {
                const stage = e.target.value;
                update("target_management", {
                  stage,
                  monthly_target_return:
                    stage === "beginner"
                      ? 0.02
                      : stage === "advanced"
                        ? 0.05
                        : 0.0833,
                });
              }}
            >
              <option value="beginner">初階 · 月2%</option>
              <option value="advanced">進階 · 月5%</option>
              <option value="ultimate">終極 · 月8.33%</option>
            </select>
          </label>
          <label>
            最大虧損上限 %
            <input
              type="number"
              min=".1"
              max="99"
              step=".1"
              value={data.risk.max_loss_ratio * 100}
              onChange={(e) =>
                update("risk", {
                  ...data.risk,
                  max_loss_ratio: +e.target.value / 100,
                })
              }
            />
          </label>
          <label>
            策略停損預設 %
            <input
              type="number"
              min=".1"
              max="99"
              step=".1"
              value={(data.risk.strategy_stop_ratio || 0.05) * 100}
              onChange={(e) =>
                update("risk", {
                  ...data.risk,
                  strategy_stop_ratio: +e.target.value / 100,
                })
              }
            />
          </label>
          <label>
            日均量期間（交易日）
            <input
              type="number"
              min="1"
              max="240"
              value={data.stock_pool.volume_filter.lookback_trading_days}
              onChange={(e) =>
                update("stock_pool", {
                  ...data.stock_pool,
                  volume_filter: {
                    ...data.stock_pool.volume_filter,
                    lookback_trading_days: +e.target.value,
                  },
                })
              }
            />
          </label>
          <label>
            最低股價（元）
            <input
              type="number"
              min="0"
              value={data.scanner.minimum_price}
              onChange={(e) =>
                update("scanner", {
                  ...data.scanner,
                  minimum_price: +e.target.value,
                })
              }
            />
          </label>
          <label>
            總投入上限 %
            <input
              type="number"
              min="1"
              max="90"
              value={data.scanner.max_allocation * 100}
              onChange={(e) =>
                update("scanner", {
                  ...data.scanner,
                  max_allocation: +e.target.value / 100,
                })
              }
            />
          </label>
          <label>
            最低日均量（張）
            <input
              type="number"
              min="0"
              value={data.stock_pool.volume_filter.minimum_lots}
              onChange={(e) =>
                update("stock_pool", {
                  ...data.stock_pool,
                  volume_filter: {
                    ...data.stock_pool.volume_filter,
                    minimum_lots: +e.target.value,
                  },
                })
              }
            />
          </label>
          {[
            ["exclude_full_delivery", "排除全額交割"],
            ["exclude_disposition", "排除處置股"],
            ["exclude_etf", "排除ETF"],
            ["exclude_ky", "排除KY"],
          ].map(([k, l]) => (
            <label className="checkbox" key={k}>
              <input
                type="checkbox"
                checked={data.stock_pool[k]}
                onChange={(e) =>
                  update("stock_pool", {
                    ...data.stock_pool,
                    [k]: e.target.checked,
                  })
                }
              />
              {l}
            </label>
          ))}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={data.notifications.enabled}
              onChange={(e) =>
                update("notifications", {
                  ...data.notifications,
                  enabled: e.target.checked,
                })
              }
            />
            啟用 LINE 通知（需本機憑證）
          </label>
        </div>
        <Notice>
          策略停損先觸發先出場；最大虧損比例作為最後上限。LINE
          金鑰由本機環境設定，不會顯示或保存於這個表單。
        </Notice>
      </div>
      <div className="panel">
        <h2>規則參數</h2>
        <div className="form-grid">
          {[
            ["body_threshold", "進場K實體比例", 0.001],
            ["attack_volume_ratio", "攻擊量倍數", 0.1],
            ["explosive_volume_ratio", "爆量倍數", 0.1],
            ["range_width", "盤整寬度比例", 0.01],
            ["tangle_spread", "均線糾結價差比例", 0.001],
            ["range_days", "箱型觀察交易日", 1],
          ].map(([k, label, step]) => (
            <label key={String(k)}>
              {label}
              <input
                type="number"
                min={step}
                step={step}
                value={data.rule_params[String(k)]}
                onChange={(e) =>
                  update("rule_params", {
                    ...data.rule_params,
                    [String(k)]: +e.target.value,
                  })
                }
              />
            </label>
          ))}
        </div>
        <small>
          比例以小數輸入，例如0.02＝2%；修改後須保存設定，回測會記錄快照。
        </small>
      </div>
      <div className="panel">
        <div className="panel-head">
          <h2>多券商手續費方案</h2>
          <button
            onClick={() =>
              update("broker_profiles", [
                ...data.broker_profiles,
                {
                  id: "broker-" + Date.now(),
                  name: "新券商",
                  commission_base_rate: 0.001425,
                  commission_discount_multiplier: 0.28,
                  minimum_commission: 20,
                },
              ])
            }
          >
            ＋新增券商
          </button>
        </div>
        {data.broker_profiles.map((p: Data, i: number) => {
          const set = (k: string, v: Data) =>
            update(
              "broker_profiles",
              data.broker_profiles.map((x: Data, j: number) =>
                i === j ? { ...x, [k]: v } : x,
              ),
            );
          return (
            <div className="broker" key={p.id}>
              <label>
                券商名稱
                <input
                  value={p.name}
                  onChange={(e) => set("name", e.target.value)}
                />
              </label>
              <label>
                原始手續費率 %
                <input
                  type="number"
                  min="0"
                  step=".0001"
                  value={p.commission_base_rate * 100}
                  onChange={(e) =>
                    set("commission_base_rate", +e.target.value / 100)
                  }
                />
              </label>
              <label>
                折數（2.8折填2.8）
                <input
                  type="number"
                  min="0"
                  max="10"
                  step=".1"
                  value={p.commission_discount_multiplier * 10}
                  onChange={(e) =>
                    set("commission_discount_multiplier", +e.target.value / 10)
                  }
                />
              </label>
              <label>
                最低手續費（元）
                <input
                  type="number"
                  min="0"
                  value={p.minimum_commission ?? 20}
                  onChange={(e) => set("minimum_commission", +e.target.value)}
                />
              </label>
              <span>
                實際{" "}
                {(
                  p.commission_base_rate *
                  p.commission_discount_multiplier *
                  100
                ).toFixed(4)}
                %
              </span>
              <button
                disabled={
                  data.broker_profiles.length === 1 ||
                  p.id === data.backtest.broker_profile_id
                }
                onClick={() =>
                  update(
                    "broker_profiles",
                    data.broker_profiles.filter((x: Data) => x.id !== p.id),
                  )
                }
              >
                刪除
              </button>
            </div>
          );
        })}
        <label>
          預設券商
          <select
            value={data.backtest.broker_profile_id}
            onChange={(e) =>
              update("backtest", {
                ...data.backtest,
                broker_profile_id: e.target.value,
              })
            }
          >
            {data.broker_profiles.map((p: Data) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </>
  );
}
function DataPage({ status, action, busy }: Actions & { status: Data }) {
  const [ids, setIds] = useState("2330,2317,2454"),
    [years, setYears] = useState(10);
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setInterval(
      () => window.dispatchEvent(new Event("refresh-data")),
      10000,
    );
    return () => clearInterval(timer);
  }, []);
  const coverage = status?.coverage
    .filter((x: Data) => !search || x.id.includes(search))
    .slice(0, 100);
  return (
    <>
      <div className="stats">
        <Stat label="股票清單" value={money(status?.stocks)} />
        <Stat label="日K筆數" value={money(status?.bars)} />
        <Stat label="有歷史資料股票" value={money(status?.coverage.length)} />
        <Stat
          label="LINE 連線設定"
          value={status?.line_configured ? "已設定" : "未設定"}
        />
      </div>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>全市場10年回補進度</h2>
            <small>
              逐檔保存；額度或網路失敗等待後續跑。停止不會刪除資料。
            </small>
          </div>
          <div className="chips">
            <button
              disabled={busy}
              onClick={() => action(() => api("bulk/start", "POST"))}
            >
              啟動／續跑
            </button>
            <button
              disabled={busy}
              onClick={() => action(() => api("bulk/stop", "POST"))}
            >
              停止回補
            </button>
          </div>
        </div>
        <p>
          {status?.bulk?.status || "尚未開始"} · 完成 {status?.bulk?.done || 0}{" "}
          / {status?.bulk?.total || status?.stocks || 0} 檔 · 目前{" "}
          {status?.bulk?.stock_id || "—"}
        </p>
        {status?.bulk?.error && (
          <Notice>{status.bulk.error} · 稍後自動重試</Notice>
        )}
        <progress
          max={status?.bulk?.total || 1}
          value={status?.bulk?.done || 0}
        />
        {status?.quality && (
          <p className="muted">
            品質檢查：
            {
              status.quality.rows.filter(
                (x: Data) =>
                  x.unverified_bars ||
                  x.rejected_dates?.length ||
                  x.missing_trading_dates.length ||
                  x.suspicious_moves.length,
              ).length
            }{" "}
            檔需要核對 · {status.quality.updated_at}
          </p>
        )}
      </div>
      <div className="panel">
        <div className="panel-head">
          <div>
            <h2>資料抓取與品質</h2>
            <small>
              進度可追蹤，失敗可重跑；資料抓取與回測在背景依序執行。
            </small>
          </div>
          <div className="chips">
            <button
              disabled={busy}
              onClick={() =>
                action(() => api("ingest", "POST", { command: "list" }))
              }
            >
              更新股票清單
            </button>
            <button
              disabled={busy}
              onClick={() =>
                action(() => api("ingest", "POST", { command: "daily" }))
              }
            >
              更新當日日K與狀態
            </button>
          </div>
        </div>
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            action(() =>
              api("ingest", "POST", {
                command: "history",
                stock_ids: ids
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
                years,
              }),
            );
          }}
        >
          <label>
            回補股票（逗號分隔）
            <input
              value={ids}
              onChange={(e) => setIds(e.target.value)}
              placeholder="留空回補全部股票"
            />
          </label>
          <label>
            歷史年數
            <input
              type="number"
              min="1"
              max="20"
              value={years}
              onChange={(e) => setYears(+e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            開始回補
          </button>
        </form>
        <Notice>
          免費來源有額度限制；使用除權息及減資參考價建立還原因子，取得失敗會標示未驗證並拒絕該區間回測。缺漏股票不會被誤認為沒有訊號。
        </Notice>
        <label>
          搜尋股票資料
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="股票代號；每次顯示前100筆"
          />
        </label>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>筆數</th>
                <th>開始</th>
                <th>最新</th>
                <th>還原價驗證</th>
              </tr>
            </thead>
            <tbody>
              {coverage?.map((x: Data) => (
                <tr key={x.id}>
                  <td>
                    <Link href={"/stock/" + x.id}>{x.id}</Link>
                  </td>
                  <td>{money(x.rows)}</td>
                  <td>{x.first}</td>
                  <td>{x.last}</td>
                  <td>
                    <Tag kind={x.verified === x.rows ? "success" : "neutral"}>
                      {x.verified}/{x.rows}
                    </Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel">
        <h2>背景工作</h2>
        {status?.jobs.map((x: Data) => (
          <div className="signal" key={x.key}>
            <b>
              {x.kind} <Tag>{x.status}</Tag>
            </b>
            <small>{x.created_at || x.finished_at}</small>
            {x.error && <p>{x.error}</p>}
          </div>
        ))}
      </div>
    </>
  );
}
