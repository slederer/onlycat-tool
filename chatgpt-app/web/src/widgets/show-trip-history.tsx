import "@/index.css";

import { mountWidget, useLayout } from "skybridge/web";
import { useToolInfo } from "../helpers.js";

function formatDuration(mins: number): string {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-FR", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function ShowTripHistory() {
  const { isSuccess, output, isPending } = useToolInfo<"show-trip-history">();
  const { theme } = useLayout();

  if (isPending || !isSuccess || !output) {
    return <div className="loading">Loading trips...</div>;
  }

  const data = output.structuredContent;

  return (
    <div
      className={`container ${theme}`}
      data-llm={`Trip history: ${data.totalTrips} total trips. Avg duration: ${data.avgDurationMinutes}m. Longest: ${data.longestTripMinutes}m.`}
    >
      <div className="header">
        <div className="header-title">
          🚶 Trips
          {data.oniStatus === "outside" && data.currentTripStart && (
            <span className="status-badge status-outside">Out now</span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-value">{data.totalTrips}</div>
            <div className="stat-label">Total</div>
          </div>
          <div className="stat">
            <div className="stat-value">{formatDuration(data.avgDurationMinutes)}</div>
            <div className="stat-label">Avg Duration</div>
          </div>
          <div className="stat">
            <div className="stat-value">{formatDuration(data.longestTripMinutes)}</div>
            <div className="stat-label">Longest</div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-value">{data.tripsToday}</div>
            <div className="stat-label">Today</div>
          </div>
          <div className="stat">
            <div className="stat-value">{formatDuration(data.timeOutsideTodayMinutes)}</div>
            <div className="stat-label">Outside Today</div>
          </div>
          <div className="stat" />
        </div>
      </div>

      {data.recentTrips.length > 0 && (
        <div className="card">
          <div className="card-title">Recent Trips</div>
          <ul className="trip-list">
            {data.recentTrips.map((trip: any, i: number) => (
              <li key={i} className="trip-item">
                <div>
                  <div className="trip-time">{formatDate(trip.leftAt)}</div>
                  <div style={{ fontSize: 12 }}>
                    {formatTime(trip.leftAt)} → {formatTime(trip.returnedAt)}
                  </div>
                </div>
                <span className="trip-duration">
                  {formatDuration(trip.durationMinutes)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ShowTripHistory;

mountWidget(<ShowTripHistory />);
