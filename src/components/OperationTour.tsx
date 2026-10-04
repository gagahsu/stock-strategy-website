"use client";
import { useEffect, useRef, useState } from "react";

type Step = {
  title: string;
  text: string;
  selector?: string;
  heading?: string;
};
const guides: Record<string, Step[]> = {
  scan: [
    {
      title: "先看市場，再找候選",
      text: "查看大盤狀態與建議投入比例，再確認已掃描股票數。候選只涵蓋目前已載入且符合必要條件的股票。",
      selector: ".stats",
    },
    {
      title: "更新收盤訊號",
      text: "「執行全市場掃描」會建立背景工作。等待完成後，使用做多、做空與待確認分頁查看結果；資料日期請以頁面顯示為準。",
      heading: "收盤後訊號",
    },
    {
      title: "縮小範圍與保存條件",
      text: "設定漲幅、量比、規則與必要濾網，再為常用條件命名並保存。這裡是在篩選掃描結果，日均量門檻則在偏好設定調整。",
      selector: ".scan-filters",
    },
    {
      title: "核對候選，不直接下單",
      text: "點股票代號進入個股診斷，檢查K線、觸發理由與未知項。確認後加入鎖股；收盤後工作區可協助逐項檢視。",
      heading: "收盤後工作",
    },
  ],
  settings: [
    {
      title: "先設定你的資金與風險",
      text: "預設本金30萬元、月目標2%。最大虧損上限可調，策略停損先觸發先出場，上限作最後防線。日均量期間與門檻也在這裡調整。",
      heading: "你的策略預設",
    },
    {
      title: "調整型態門檻",
      text: "規則參數用小數比例，例如0.02代表2%。調整後需要保存設定；每次回測會另留參數快照，方便比較。",
      heading: "規則參數",
    },
    {
      title: "設定各家券商成本",
      text: "可新增券商方案，分別填原始費率、折數與最低手續費。回測時再選用方案。最後按「保存設定」套用變更。",
      heading: "多券商手續費方案",
    },
  ],
  data: [
    {
      title: "先確認資料是否足夠",
      text: "檢查日K筆數、涵蓋股票與LINE設定。缺資料、來源失敗或未驗證還原價會限制掃描與回測，不能當作沒有訊號。",
      selector: ".stats",
    },
    {
      title: "回補可以停止與續跑",
      text: "「啟動／續跑」會按已保存進度回補。「停止回補」保留資料。來源額度不足時會等待重試；完成檔數才代表真正完成的進度。",
      heading: "全市場10年回補進度",
    },
    {
      title: "更新與指定個股回補",
      text: "可更新股票清單、當日日K，或填入股票代號回補歷史。表格顯示日期範圍與還原價驗證，背景工作區可查看處理結果。",
      heading: "資料抓取與品質",
    },
  ],
  stock: [
    {
      title: "閱讀個股K線",
      text: "日、週、月分頁切換圖表週期；預設顯示最近120根。可開關訊號名稱，搭配均線、轉折與缺口觀察，避免只看單一箭頭。",
      selector: ".chart-controls",
    },
    {
      title: "核對選股條件",
      text: "六六大順與選股評量列出通過、未通過及未知的理由。未知項需要人工查證，不能視為通過。",
      heading: "六六大順與選股評量",
    },
    {
      title: "看觸發理由與資料限制",
      text: "檢查觸發規則、缺口狀態與基本面日期。圖像規則含明列的數值近似；適合持續觀察的股票可用頁首「加入鎖股」保存。",
      heading: "觸發規則",
    },
  ],
  watchlist: [
    {
      title: "建立自己的觀察清單",
      text: "可以手動輸入股票代號加入鎖股，也可以在個股頁加入。清單記錄觀察理由與訊號；點代號回到個股診斷。",
      heading: "鎖股資料夾",
    },
    {
      title: "持續確認，符合條件再評估",
      text: "鎖股代表追蹤候選，不代表已持有或已成交。收盤後核對最新K線與條件，失去觀察價值時可移除。",
    },
  ],
  backtest: [
    {
      title: "組合回測條件",
      text: "填股票池與日期，選進場規則、方向、停損、出場與券商費率。收盤訊號採次日成交，第一版不包含當沖。",
      heading: "組合策略，驗證紀律",
    },
    {
      title: "執行或比較策略",
      text: "「執行回測」計算單一組合；比較按鈕會比較3種停損與3種出場。這些操作由你按下才執行，導覽不會啟動工作。",
      selector: '[data-tour="page"] .panel-head',
    },
    {
      title: "同時看風險與資料品質",
      text: "結果出現後，檢查報酬、回撤、逐筆交易、樣本外與方程式對照。未驗證資料及回測限制需一起閱讀，不能只挑報酬最高的一組。",
    },
    {
      title: "重看已保存結果",
      text: "已保存回測表格的「查看」可重開結果，便於核對不同參數。手機上的寬表格可在表格區域左右捲動。",
      heading: "已保存回測與策略比較",
    },
  ],
  portfolio: [
    {
      title: "登錄實際持股批次",
      text: "輸入股票、進場日期、價格與股數，再選策略及停損。新增、編輯與減碼只更新追蹤紀錄，網站不會替你送券商委託。",
      heading: "持股與出場紀律",
    },
    {
      title: "追蹤風險與月目標",
      text: "查看策略出場、虧損超過5%的警示與牛步股提示；每月目標管理可記錄實際報酬並對照月2%、5%或8.33%階段。",
      heading: "每月目標管理",
    },
    {
      title: "核對通知結果",
      text: "LINE憑證需要在本機環境設定，再啟用通知。通知紀錄可查看佇列與送達狀態，未設定憑證時不能視為已送出。",
      heading: "LINE 通知紀錄",
    },
  ],
  rules: [
    {
      title: "找到規則與出處",
      text: "用搜尋框輸入規則ID或名稱，也可按Part分頁篩選。每張規則卡會顯示出處、方向與判讀說明。",
      selector: '[aria-label="搜尋規則"]',
    },
    {
      title: "區分規則條件與近似",
      text: "閱讀實際數值條件及限制；標示「數值近似」的型態尚不能宣稱逐圖精準重現。把這裡當作核對訊號理由的說明書。",
      heading: "每條訊號都有理由與出處",
    },
  ],
};

export default function OperationTour({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const key = path === "/" ? "scan" : path.split("/")[1];
  const steps: Step[] = [
    {
      title: "從這裡開始",
      text: "第一次使用建議依序：偏好設定 → 資料管理 → 今日掃描 → 個股診斷 → 鎖股清單。接著用策略回測檢驗，再到持股追蹤記錄實際部位。導覽不會修改資料或執行交易。",
      selector: '[aria-label="主要導覽"]',
    },
    {
      title: "快速查詢股票",
      text: "在搜尋框輸入股票代號，例如2330，按查詢即可開啟個股診斷。任何頁面上方都可重開「操作導覽」，查看該頁的步驟。",
      selector: ".search",
    },
    ...(guides[key] || guides.scan),
  ];
  const step = steps[index];
  const close = () => setOpen(false);

  useEffect(() => {
    setOpen(false);
    setIndex(0);
  }, [path]);
  useEffect(() => {
    if (open) {
      dialog.current?.showModal();
      nextButton.current?.focus();
    } else dialog.current?.close();
  }, [open]);
  useEffect(() => {
    if (open) nextButton.current?.focus();
  }, [index, open]);
  useEffect(() => {
    if (!open) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    let lastTarget: Element | null = null;
    let frame = 0;
    const update = () => {
      const target = step.selector
        ? document.querySelector(step.selector)
        : step.heading
          ? Array.from(document.querySelectorAll('[data-tour="page"] h2'))
              .find((x) => x.textContent?.includes(step.heading!))
              ?.closest(".panel-head") ||
            Array.from(document.querySelectorAll('[data-tour="page"] h2')).find(
              (x) => x.textContent?.includes(step.heading!),
            )
          : null;
      if (target && target !== lastTarget) {
        lastTarget = target;
        target.scrollIntoView({
          block: "center",
          inline: "nearest",
          behavior: "instant",
        });
      }
      let r = target?.getBoundingClientRect();
      const card = dialog.current
        ?.querySelector(".tour-card")
        ?.getBoundingClientRect();
      if (
        r &&
        card &&
        r.bottom > card.top - 16 &&
        r.top < card.bottom &&
        r.right > card.left
      ) {
        window.scrollBy({ top: r.bottom - card.top + 16, behavior: "instant" });
        r = target?.getBoundingClientRect();
      }
      if (!r || !r.width || !r.height) {
        setRect(null);
        return;
      }
      const left = Math.max(8, r.left - 5),
        top = Math.max(8, r.top - 5);
      setRect({
        left,
        top,
        width: Math.max(0, Math.min(innerWidth - 8, r.right + 5) - left),
        height: Math.max(0, Math.min(innerHeight - 8, r.bottom + 5) - top),
      });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(
      document.querySelector('[data-tour="page"]') || document.body,
      { childList: true, subtree: true },
    );
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      document.body.style.overflow = originalOverflow;
    };
  }, [open, index, path]);

  return (
    <>
      <button
        className="tour-launch"
        onClick={() => {
          setIndex(0);
          setOpen(true);
        }}
      >
        操作導覽
      </button>
      <dialog
        ref={dialog}
        className="operation-tour"
        aria-labelledby="tour-title"
        aria-describedby="tour-description"
        onCancel={close}
        onClose={close}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const buttons = Array.from(
            dialog.current?.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ) || [],
          );
          const first = buttons[0],
            last = buttons[buttons.length - 1];
          if (!first || !last) return;
          const focused = document.activeElement;
          if (
            !dialog.current?.contains(focused) ||
            (!event.shiftKey && focused === last)
          ) {
            event.preventDefault();
            first.focus();
          } else if (event.shiftKey && focused === first) {
            event.preventDefault();
            last.focus();
          }
        }}
      >
        {open && (
          <>
            {rect && (
              <div className="tour-highlight" aria-hidden="true" style={rect} />
            )}
            <section className="tour-card">
              <div className="tour-top">
                <span>
                  操作導覽 · {index + 1} / {steps.length}
                </span>
                <button onClick={close} aria-label="關閉操作導覽">
                  關閉
                </button>
              </div>
              <div aria-live="polite" aria-atomic="true">
                <h2 id="tour-title">{step.title}</h2>
                <p id="tour-description">{step.text}</p>
              </div>
              <div className="tour-progress" aria-hidden="true">
                {steps.map((_, i) => (
                  <span key={i} className={i <= index ? "complete" : ""} />
                ))}
              </div>
              <div className="tour-actions">
                <button
                  onClick={() => setIndex((x) => x - 1)}
                  disabled={index === 0}
                >
                  上一步
                </button>
                <button onClick={close}>略過導覽</button>
                <button
                  className="primary"
                  ref={nextButton}
                  autoFocus
                  onClick={() =>
                    index === steps.length - 1
                      ? close()
                      : setIndex((x) => x + 1)
                  }
                >
                  {index === steps.length - 1 ? "完成導覽" : "下一步"}
                </button>
              </div>
            </section>
          </>
        )}
      </dialog>
    </>
  );
}
