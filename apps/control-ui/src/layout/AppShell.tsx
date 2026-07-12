import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { Button, Layout, Menu, Typography } from "antd";
import type { ReactNode } from "react";
import { useState } from "react";
import { PRIMARY_NAV, RESEARCH_NAV, type AppRoute, pathForRoute, primaryRouteFor } from "../routes";

export function AppShell({
  route,
  onRouteChange,
  children,
}: {
  route: AppRoute;
  onRouteChange: (route: AppRoute) => void;
  children: ReactNode;
}) {
  const primary = primaryRouteFor(route);
  const isResearch = primary === "research-pipeline";
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout className="qto-root">
      <Layout.Sider
        className={`qto-sidebar ${collapsed ? "qto-sidebar-collapsed" : ""}`}
        width={220}
        collapsedWidth={72}
        collapsed={collapsed}
        trigger={null}
        theme="light"
      >
        <div className="qto-brand">
          <span className="qto-logo">QT</span>
          <div className="qto-brand-text">
            <Typography.Text strong>Quant Team OS</Typography.Text>
          </div>
          <Button
            className="qto-sidebar-toggle"
            type="text"
            size="small"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
            onClick={() => setCollapsed((value) => !value)}
          />
        </div>
        <Menu
          inlineCollapsed={collapsed}
          mode="inline"
          selectedKeys={[primary]}
          items={PRIMARY_NAV.map((item) => ({ key: item.key, icon: item.icon, label: item.label }))}
          onClick={({ key }) => onRouteChange(key as AppRoute)}
        />
      </Layout.Sider>
      <Layout>
        <div className="qto-mobile-primary">
            {PRIMARY_NAV.map((item) => (
              <Button key={item.key} type={primary === item.key ? "primary" : "text"} icon={item.icon} onClick={() => onRouteChange(item.key)}>
                {item.label}
              </Button>
            ))}
        </div>
        {isResearch ? (
          <nav className="qto-subnav" aria-label="策略研究二级导航">
            {RESEARCH_NAV.map((item) => (
              <Button
                key={item.key}
                type={route === item.key ? "primary" : "text"}
                icon={item.icon}
                href={pathForRoute(item.key)}
                onClick={(event) => {
                  event.preventDefault();
                  onRouteChange(item.key);
                }}
              >
                {item.label}
              </Button>
            ))}
          </nav>
        ) : null}
        <Layout.Content className="qto-content">{children}</Layout.Content>
      </Layout>
    </Layout>
  );
}
