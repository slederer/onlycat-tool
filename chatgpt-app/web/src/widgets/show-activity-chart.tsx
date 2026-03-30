import "@/index.css";

import { useEffect } from "react";
import { mountWidget, useLayout, useWidgetState } from "skybridge/web";
import { useCallTool, useToolInfo } from "../helpers.js";

const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => `${i}`);
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function heatmapColor(value: number, max: number, dark: boolean): string {
  if (value === 0) return dark ? "#1e293b" : "#f1f5f9";
  const intensity = Math.min(value / Math.max(max, 1), 1);
  const r = Math.round(255 * intensity);
  const g = Math.round(107 * intensity);
  const b = Math.round(53 * intensity);
  return `rgb(${r}, ${g}, ${b})`;
}

type ViewType = "hourly" | "heatmap" | "comparison";

function ShowActivityChart() {
  const { isSuccess, output, isPending } = useToolInfo<"show-activity-chart">();
  const { callTool: switchView, isPending: isSwitching } = useCallTool("show-activity-chart");
  const [view, setView] = useWidgetState<ViewType>("hourly");
  const { theme } = useLayout();
  const isDark = theme === "dark";

  useEffect(() => {
    if (isSuccess && output) {
      setView(output.structuredContent.view as ViewType);
    }
  }, [isSuccess, output, setView]);

  if (isPending || !isSuccess || !output) {
    return <div className="loading">Loading charts...</div>;
  }

  const data = output.structuredContent;
  const hourly: number[] = data.hourlyPattern;
  const maxHourly = Math.max(...hourly, 1);
  const heatmap: number[][] = data.heatmap;
  const maxHeat = Math.max(...heatmap.flat(), 1);

  function goToView(v: ViewType) {
    setView(v);
    switchView({ view: v }, { onSuccess: () => {} });
  }

  return (
    <div
      className={`container ${theme}`}
      data-llm={`Activity chart: ${view} view. Events today: ${data.eventsToday}. Peak hour: ${data.peakHour ?? "N/A"}.`}
    >
      <div className="header">
        <div className="header-title">📊 Activity</div>
        <div style={{ display: "flex", gap: 4 }}>
          {(["hourly", "heatmap", "comparison"] as ViewType[]).map((v) => (
            <button
              key={v}
              className="btn"
              style={{
                opacity: view === v ? 1 : 0.5,
                background: view === v ? "var(--accent)" : "transparent",
                color: view === v ? "white" : "var(--accent)",
              }}
              onClick={() => goToView(v)}
              disabled={isSwitching}
            >
              {v === "hourly" ? "24h" : v === "heatmap" ? "Week" : "vs"}
            </button>
          ))}
        </div>
      </div>

      {view === "hourly" && (
        <div className="card">
          <div className="card-title">
            Hourly Pattern (30 days){" "}
            {data.peakHour !== null && <span>· Peak: {data.peakHour}:00</span>}
          </div>
          <div className="bar-chart">
            {hourly.map((count, h) => (
              <div
                key={h}
                className="bar"
                style={{ height: `${(count / maxHourly) * 100}%` }}
                title={`${h}:00 — ${count} events`}
              >
                {h % 6 === 0 && <span className="bar-label">{h}h</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {view === "heatmap" && (
        <div className="card">
          <div className="card-title">Weekly Heatmap (30 days)</div>
          <div className="heatmap">
            <div /> {/* empty corner */}
            {HOUR_LABELS.map((h) => (
              <div
                key={h}
                style={{
                  textAlign: "center",
                  fontSize: 8,
                  color: "var(--text-muted)",
                }}
              >
                {Number(h) % 6 === 0 ? h : ""}
              </div>
            ))}
            {heatmap.map((row, dayIdx) => (
              <>
                <div key={`label-${dayIdx}`} className="heatmap-label">
                  {DAY_LABELS[dayIdx]}
                </div>
                {row.map((val, hourIdx) => (
                  <div
                    key={`${dayIdx}-${hourIdx}`}
                    className="heatmap-cell"
                    style={{ background: heatmapColor(val, maxHeat, isDark) }}
                    title={`${DAY_LABELS[dayIdx]} ${hourIdx}:00 — ${val} events`}
                  />
                ))}
              </>
            ))}
          </div>
        </div>
      )}

      {view === "comparison" && data.comparison && (
        <div className="card">
          <div className="card-title">This Week vs Last Week</div>
          <div className="stat-grid">
            <div className="stat">
              <div className="stat-value">{data.comparison.this_week ?? 0}</div>
              <div className="stat-label">This Week</div>
            </div>
            <div className="stat">
              <div className="stat-value">{data.comparison.last_week ?? 0}</div>
              <div className="stat-label">Last Week</div>
            </div>
            <div className="stat">
              <div
                className="stat-value"
                style={{
                  color:
                    (data.comparison.change_pct ?? 0) >= 0
                      ? "var(--green)"
                      : "var(--red)",
                }}
              >
                {(data.comparison.change_pct ?? 0) >= 0 ? "+" : ""}
                {data.comparison.change_pct ?? 0}%
              </div>
              <div className="stat-label">Change</div>
            </div>
          </div>
        </div>
      )}

      <div className="footer">
        <span>{data.eventsToday} events today</span>
        <span>{data.totalEvents} total</span>
      </div>
    </div>
  );
}

export default ShowActivityChart;

mountWidget(<ShowActivityChart />);
