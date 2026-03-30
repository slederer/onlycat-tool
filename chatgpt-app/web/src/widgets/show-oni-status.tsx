import "@/index.css";

import { mountWidget, useLayout } from "skybridge/web";
import { useToolInfo } from "../helpers.js";

function formatTime(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function formatRelative(iso: string | null): string {
  if (!iso) return "--";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function ShowOniStatus() {
  const { isSuccess, output, isPending } = useToolInfo<"show-oni-status">();
  const { theme } = useLayout();

  if (isPending || !isSuccess || !output) {
    return <div className="loading">Loading Oni's status...</div>;
  }

  const data = output.structuredContent;

  const statusClass =
    data.location === "inside"
      ? "status-inside"
      : data.location === "outside"
        ? "status-outside"
        : "status-unknown";

  const statusEmoji = data.location === "inside" ? "🏠" : data.location === "outside" ? "🌳" : "❓";

  return (
    <div
      className={`container ${theme}`}
      data-llm={`Oni is ${data.location}. Events today: ${data.eventsToday}. Clean streak: ${data.contraband.cleanStreak} days.`}
    >
      <div className="header">
        <div className="header-title">
          🐱 Oni
          <span className={`status-badge ${statusClass}`}>
            {statusEmoji} {data.location}
          </span>
        </div>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {data.deviceConnected ? "🟢 Online" : "🔴 Offline"}
        </span>
      </div>

      <div className="card">
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-value">{data.eventsToday}</div>
            <div className="stat-label">Today</div>
          </div>
          <div className="stat">
            <div className="stat-value">{data.avgPerDay}</div>
            <div className="stat-label">Avg/Day</div>
          </div>
          <div className="stat">
            <div className="stat-value">{data.totalEvents}</div>
            <div className="stat-label">Total</div>
          </div>
        </div>
      </div>

      {data.location === "outside" && data.currentTripStart && (
        <div className="card">
          <div className="card-title">Current Trip</div>
          <div style={{ fontSize: 13 }}>
            Left at <strong>{formatTime(data.currentTripStart)}</strong>
            {data.estimatedReturn && (
              <> &middot; Est. return: <strong>{formatTime(data.estimatedReturn)}</strong></>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">Contraband-Free Streak</div>
        <div className="streak">
          <div className="streak-number">{data.contraband.cleanStreak}</div>
          <div className="streak-label">days clean</div>
        </div>
      </div>

      {data.badges.length > 0 && (
        <div className="card">
          <div className="card-title">Badges</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {data.badges.map((b: any) => (
              <span
                key={b.id}
                title={b.desc}
                style={{
                  fontSize: 11,
                  padding: "3px 8px",
                  background: "var(--accent-light)",
                  borderRadius: 12,
                }}
              >
                {b.icon} {b.name}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="footer">
        <span>Last event: {formatRelative(data.lastEvent)}</span>
        <span>{data.lastDirection || ""}</span>
      </div>
    </div>
  );
}

export default ShowOniStatus;

mountWidget(<ShowOniStatus />);
