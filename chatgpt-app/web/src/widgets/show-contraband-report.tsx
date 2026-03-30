import "@/index.css";

import { mountWidget, useLayout } from "skybridge/web";
import { useToolInfo } from "../helpers.js";

function ShowContrabandReport() {
  const { isSuccess, output, isPending } = useToolInfo<"show-contraband-report">();
  const { theme } = useLayout();

  if (isPending || !isSuccess || !output) {
    return <div className="loading">Loading contraband report...</div>;
  }

  const data = output.structuredContent;
  const hourly: number[] = data.hourlyPattern;
  const maxHourly = Math.max(...hourly, 1);

  return (
    <div
      className={`container ${theme}`}
      data-llm={`Contraband report: ${data.cleanStreak} day clean streak. This week: ${data.thisWeek}, this month: ${data.thisMonth}.`}
    >
      <div className="header">
        <div className="header-title">🐭 Contraband Report</div>
      </div>

      <div className="card">
        <div className="streak">
          <div className="streak-number">{data.cleanStreak}</div>
          <div className="streak-label">days contraband-free</div>
          {data.longestStreak > 0 && (
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              Record: {data.longestStreak} days
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-value" style={{ color: data.thisWeek > 0 ? "var(--red)" : "var(--green)" }}>
              {data.thisWeek}
            </div>
            <div className="stat-label">This Week</div>
          </div>
          <div className="stat">
            <div className="stat-value" style={{ color: data.thisMonth > 0 ? "var(--red)" : "var(--green)" }}>
              {data.thisMonth}
            </div>
            <div className="stat-label">This Month</div>
          </div>
          <div className="stat">
            <div className="stat-value">{data.daysSince ?? "--"}</div>
            <div className="stat-label">Days Since Last</div>
          </div>
        </div>
      </div>

      {hourly.some((v) => v > 0) && (
        <div className="card">
          <div className="card-title">Risk Hours (last 30 days)</div>
          <div className="bar-chart">
            {hourly.map((count, h) => (
              <div
                key={h}
                className="bar"
                style={{
                  height: `${(count / maxHourly) * 100}%`,
                  background: count > 0 ? "var(--red)" : "var(--border)",
                }}
                title={`${h}:00 — ${count} incidents`}
              >
                {h % 6 === 0 && <span className="bar-label">{h}h</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {data.lastIncident && (
        <div className="footer">
          <span>
            Last incident:{" "}
            {new Date(data.lastIncident).toLocaleDateString("fr-FR", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
        </div>
      )}
    </div>
  );
}

export default ShowContrabandReport;

mountWidget(<ShowContrabandReport />);
