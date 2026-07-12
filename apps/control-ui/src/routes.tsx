import {
  BarChartOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  FunctionOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import type { ReactNode } from "react";

export type AppRoute =
  | "dashboard"
  | "research-pipeline"
  | "factors-strategies"
  | "experiments"
  | "reports"
  | "agent-canvas";

export const ROUTE_PATHS: Record<AppRoute, string> = {
  dashboard: "/dashboard",
  "research-pipeline": "/research/pipeline",
  "factors-strategies": "/research/factors-strategies",
  experiments: "/research/experiments",
  reports: "/research/reports",
  "agent-canvas": "/agents/canvas",
};

export const LEGACY_REDIRECTS: Record<string, string> = {
  "/": "/dashboard",
  "/overview": "/dashboard",
  "/agent-console": "/agents/canvas",
  "/connections": "/agents/canvas?panel=connections",
  "/workflows": "/agents/canvas?panel=workflows",
  "/audit-log": "/agents/canvas?panel=audit",
  "/settings": "/agents/canvas?panel=settings",
  "/external-workspaces": "/agents/canvas?panel=tools",
  "/research-lab": "/research/pipeline",
  "/factor-library": "/research/factors-strategies?tab=factors",
  "/strategy-registry": "/research/factors-strategies?tab=strategies",
  "/backtest-center": "/research/experiments",
  "/risk-center": "/dashboard?panel=risk",
  "/approvals": "/dashboard?panel=approvals",
  "/paper-trading": "/dashboard?panel=portfolio",
};

export const PRIMARY_NAV: Array<{ key: AppRoute; label: string; icon: ReactNode }> = [
  { key: "dashboard", label: "工作台", icon: <DashboardOutlined /> },
  { key: "research-pipeline", label: "策略研究", icon: <ExperimentOutlined /> },
  { key: "agent-canvas", label: "智能体管理", icon: <RobotOutlined /> },
];

export const RESEARCH_NAV: Array<{ key: AppRoute; label: string; icon: ReactNode }> = [
  { key: "research-pipeline", label: "研究管线", icon: <ExperimentOutlined /> },
  { key: "factors-strategies", label: "因子和策略", icon: <FunctionOutlined /> },
  { key: "experiments", label: "实验与回测", icon: <BarChartOutlined /> },
  { key: "reports", label: "研究报告", icon: <FileTextOutlined /> },
];

export function normalizePath(pathname: string) {
  const clean = pathname.replace(/\/$/, "") || "/";
  return LEGACY_REDIRECTS[clean] ?? clean;
}

export function routeFromLocation(): AppRoute {
  const normalized = normalizePath(window.location.pathname);
  const pathOnly = normalized.split("?")[0];
  return (Object.entries(ROUTE_PATHS).find(([, path]) => path === pathOnly)?.[0] as AppRoute | undefined) ?? "dashboard";
}

export function pathForRoute(route: AppRoute) {
  return ROUTE_PATHS[route] ?? "/dashboard";
}

export function primaryRouteFor(route: AppRoute): AppRoute {
  if (route === "agent-canvas") return "agent-canvas";
  if (["research-pipeline", "factors-strategies", "experiments", "reports"].includes(route)) return "research-pipeline";
  return "dashboard";
}
