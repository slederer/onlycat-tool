import { McpServer } from "skybridge/server";
import { z } from "zod";

const API_BASE = process.env.ONLYCAT_API_URL || "https://onlycat-tool.fly.dev";

async function fetchApi(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

const server = new McpServer(
  {
    name: "onlycat",
    version: "0.1.0",
  },
  {
    capabilities: {},
    instructions:
      "OnlyCat monitors Oni, an orange female cat in Paris. " +
      "Use these tools to check her status, activity, trips, contraband incidents, and visitor cats. " +
      "Indoor Motion = cat leaving, Outdoor Motion = cat entering. " +
      "Contraband = prey brought inside.",
  },
)
  // --- Oni Status Widget ---
  .registerWidget(
    "show-oni-status",
    { description: "Oni's Cat Status Dashboard" },
    {
      description:
        "Show Oni's current status: location (inside/outside), last event, current trip info, and quick stats",
      inputSchema: {},
      _meta: { "openai/widgetAccessible": true },
    },
    async () => {
      const a = await fetchApi("/api/analytics");

      const structuredContent = {
        location: a.oni_status?.status || "unknown",
        lastDirection: a.oni_status?.direction || null,
        lastEvent: a.oni_status?.last_event || null,
        currentTripStart: a.trips?.current_trip_start || null,
        eventsToday: a.summary?.events_today || 0,
        avgPerDay: a.summary?.avg_per_day || 0,
        totalEvents: a.summary?.total_events || 0,
        deviceConnected: a.device_connected || false,
        estimatedReturn: a.prediction?.estimated_return || null,
        badges: a.badges || [],
        oniStats: a.pets?.oni || {},
        contraband: {
          daysSince: a.contraband?.days_since ?? null,
          cleanStreak: a.records?.current_contraband_streak || 0,
        },
      };

      return {
        structuredContent,
        content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }],
        isError: false,
      };
    },
  )

  // --- Activity Chart Widget ---
  .registerWidget(
    "show-activity-chart",
    { description: "Oni's Activity Charts" },
    {
      description:
        "Show interactive activity charts: hourly patterns, weekly heatmap, and weekly comparison",
      inputSchema: {
        view: z
          .enum(["hourly", "heatmap", "comparison"])
          .optional()
          .default("hourly")
          .describe("Chart type to display"),
      },
      _meta: { "openai/widgetAccessible": true },
    },
    async ({ view }) => {
      const a = await fetchApi("/api/analytics");

      const structuredContent = {
        view,
        hourlyPattern: a.pets?.oni?.hourly_pattern || Array(24).fill(0),
        peakHour: a.pets?.oni?.most_active_hour ?? null,
        heatmap: a.heatmap || Array(7).fill(Array(24).fill(0)),
        comparison: a.comparison || {},
        eventsToday: a.summary?.events_today || 0,
        totalEvents: a.summary?.total_events || 0,
        timeline: a.timeline || [],
      };

      return {
        structuredContent,
        content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }],
        isError: false,
      };
    },
  )

  // --- Trip History Widget ---
  .registerWidget(
    "show-trip-history",
    { description: "Oni's Trip History" },
    {
      description: "Show Oni's outdoor trips: recent trips with durations, stats, and patterns",
      inputSchema: {},
      _meta: { "openai/widgetAccessible": true },
    },
    async () => {
      const a = await fetchApi("/api/analytics");

      const structuredContent = {
        recentTrips: (a.trips?.recent || []).map((t: any) => ({
          leftAt: t.left_at,
          returnedAt: t.returned_at,
          durationMinutes: t.duration_minutes,
        })),
        totalTrips: a.trips?.total_trips || 0,
        tripsToday: a.trips?.trips_today || 0,
        avgDurationMinutes: a.trips?.avg_duration_minutes || 0,
        longestTripMinutes: a.trips?.longest_duration_minutes || 0,
        timeOutsideTodayMinutes: a.trips?.time_outside_today_minutes || 0,
        currentTripStart: a.trips?.current_trip_start || null,
        oniStatus: a.oni_status?.status || "unknown",
      };

      return {
        structuredContent,
        content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }],
        isError: false,
      };
    },
  )

  // --- Contraband Report Widget ---
  .registerWidget(
    "show-contraband-report",
    { description: "Oni's Contraband (Prey) Report" },
    {
      description:
        "Show contraband/prey incident report: clean streak, frequency, hourly patterns",
      inputSchema: {},
      _meta: { "openai/widgetAccessible": true },
    },
    async () => {
      const a = await fetchApi("/api/analytics");

      const structuredContent = {
        daysSince: a.contraband?.days_since ?? null,
        lastIncident: a.contraband?.last_timestamp || null,
        thisWeek: a.contraband?.this_week || 0,
        thisMonth: a.contraband?.this_month || 0,
        hourlyPattern: a.contraband?.by_hour || Array(24).fill(0),
        cleanStreak: a.records?.current_contraband_streak || 0,
        longestStreak: a.records?.longest_contraband_streak || 0,
      };

      return {
        structuredContent,
        content: [{ type: "text" as const, text: JSON.stringify(structuredContent) }],
        isError: false,
      };
    },
  );

server.run();

export type AppType = typeof server;
