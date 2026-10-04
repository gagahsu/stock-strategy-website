"use client";
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  Time,
} from "lightweight-charts";
type Bar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  ma60?: number;
  pivot_high5?: number;
  pivot_low5?: number;
  key_red_mid?: number;
  key_black_mid?: number;
  support_line5?: number;
  resistance_line5?: number;
};
export default function Chart({
  bars,
  signals = [],
  gaps = [],
  kind = "candles",
}: {
  bars: Bar[];
  signals?: { date: string; name: string; direction: string }[];
  gaps?: {
    upper_high: number;
    upper: number;
    lower: number;
    lower_bottom: number;
  }[];
  kind?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [showNames, setShowNames] = useState(false);
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      height: 390,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#556473",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#f1f4f6" },
        horzLines: { color: "#f1f4f6" },
      },
      rightPriceScale: { borderColor: "#e0e6eb" },
      timeScale: { borderColor: "#e0e6eb" },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#d3514d",
      downColor: "#299477",
      borderVisible: false,
      wickUpColor: "#d3514d",
      wickDownColor: "#299477",
    });
    candles.setData(
      bars.map((x) => ({
        time: x.date as Time,
        open: x.open,
        high: x.high,
        low: x.low,
        close: x.close,
      })),
    );
    const last = bars.at(-1)!;
    [last.pivot_high5, last.pivot_low5].forEach((price, i) => {
      if (price != null)
        candles.createPriceLine({
          price,
          color: i ? "#79a98e" : "#a99079",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: i ? "轉折支撐" : "轉折壓力",
        });
    });
    const gap = gaps.at(-1);
    [last.key_red_mid, last.key_black_mid].forEach((price, i) => {
      if (price != null)
        candles.createPriceLine({
          price,
          color: i ? "#71a18b" : "#c89789",
          lineWidth: 1,
          lineStyle: 3,
          axisLabelVisible: false,
          title: i ? "大量黑K 1/2" : "大量紅K 1/2",
        });
    });
    (["support_line5", "resistance_line5"] as const).forEach((key, i) => {
      const line = chart.addSeries(LineSeries, {
        color: i ? "#9ba9b455" : "#73948a55",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        bars
          .filter((x) => x[key] != null && x[key]! > 0)
          .map((x) => ({ time: x.date as Time, value: x[key]! })),
      );
    });
    if (gap)
      (["upper_high", "upper", "lower", "lower_bottom"] as const).forEach(
        (key, i) =>
          candles.createPriceLine({
            price: gap[key],
            color: "#b2a3c4",
            lineWidth: 1,
            lineStyle: 3,
            axisLabelVisible: false,
            title: ["缺口上高", "缺口上沿", "缺口下沿", "缺口下底"][i],
          }),
      );
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      bars.map((x) => ({
        time: x.date as Time,
        value: x.volume / 1000,
        color: x.close >= x.open ? "#d3514d55" : "#29947755",
      })),
    );
    const colors = ["#bf932f", "#579bc1", "#805bae", "#bba3a3"];
    (["ma5", "ma10", "ma20", "ma60"] as const).forEach((key, i) => {
      const line = chart.addSeries(LineSeries, {
        color: colors[i],
        lineWidth: 1,
        title: key.toUpperCase(),
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        bars
          .filter((x) => x[key] != null)
          .map((x) => ({ time: x.date as Time, value: x[key]! })),
      );
    });
    const available = new Set(bars.map((x) => x.date));
    const unique = [
      ...new Map(
        signals.filter((x) => available.has(x.date)).map((x) => [x.date, x]),
      ).values(),
    ].sort((a, b) => a.date.localeCompare(b.date));
    createSeriesMarkers(
      candles,
      unique.map(
        (x) =>
          ({
            time: x.date as Time,
            position: x.direction === "long" ? "belowBar" : "aboveBar",
            color: x.direction === "long" ? "#d3514d" : "#299477",
            shape: x.direction === "long" ? "arrowUp" : "arrowDown",
            text: showNames ? x.name : "",
          }) as const,
      ),
    );
    if (showAll || bars.length <= 120) chart.timeScale().fitContent();
    else chart.timeScale().setVisibleLogicalRange({ from: bars.length - 120, to: bars.length + 3 });
    return () => chart.remove();
  }, [bars, signals, gaps, kind, showNames, showAll]);
  return <>
    <div className="row"><label className="checkbox"><input type="checkbox" checked={showNames} onChange={(e) => setShowNames(e.target.checked)} />顯示訊號名稱</label><button onClick={() => setShowAll(!showAll)}>{showAll ? "最近120根K線" : "顯示完整期間"}</button><span className="muted">紅箭頭：多方訊號 · 綠箭頭：空方訊號；可拖曳與縮放</span></div>
    <div ref={ref} className="chart" aria-label="股票K線與均線圖" />
  </>;
}
