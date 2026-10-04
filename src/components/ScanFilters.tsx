"use client";
import { useEffect, useState } from "react";
type Filter = {
  minChange: number;
  minVolumeRatio: number;
  eligibleOnly: boolean;
  rulePrefix: string;
};
export default function ScanFilters({
  onChange,
}: {
  onChange: (f: Filter) => void;
}) {
  const [filter, setFilter] = useState<Filter>({
    minChange: -100,
    minVolumeRatio: 0,
    eligibleOnly: false,
    rulePrefix: "",
  });
  const [presets, setPresets] = useState<any[]>([]),
    [name, setName] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/scan-presets")
      .then((r) => r.json())
      .then(setPresets)
      .catch(() => {});
  }, []);
  function update(f: Filter) {
    setFilter(f);
    onChange(f);
  }
  async function save() {
    const r = await fetch("/api/scan-presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, filters: filter }),
    });
    const x = await r.json();
    if (!r.ok) {
      setError(x.detail);
      return;
    }
    setPresets(await (await fetch("/api/scan-presets")).json());
    setError("已保存條件");
  }
  return (
    <div>
      <div className="form-grid">
        <label>
          最低當日漲幅 %
          <input
            type="number"
            value={filter.minChange}
            onChange={(e) => update({ ...filter, minChange: +e.target.value })}
          />
        </label>
        <label>
          最低攻擊量比
          <input
            type="number"
            step=".1"
            min="0"
            value={filter.minVolumeRatio}
            onChange={(e) =>
              update({ ...filter, minVolumeRatio: +e.target.value })
            }
          />
        </label>
        <label>
          方法
          <select
            value={filter.rulePrefix}
            onChange={(e) => update({ ...filter, rulePrefix: e.target.value })}
          >
            <option value="">所有訊號</option>
            <option value="L-ENTRY">8種進場</option>
            <option value="L-HW">高勝率型態</option>
            <option value="L-2ND">飆股第2波</option>
            <option value="L-BOTTOM">底部反轉</option>
            <option value="P-">33種圖像</option>
            <option value="M-">12口訣</option>
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filter.eligibleOnly}
            onChange={(e) =>
              update({ ...filter, eligibleOnly: e.target.checked })
            }
          />
          只看必要濾網通過
        </label>
        <label>
          自訂條件名稱
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button disabled={!name.trim()} onClick={save}>
          保存掃描條件
        </button>
      </div>
      <div className="chips">
        {presets.map((x) => (
          <button key={x.key} onClick={() => update(x.filters)}>
            {x.name}
          </button>
        ))}
      </div>
      {error && <small role="status">{error}</small>}
    </div>
  );
}
