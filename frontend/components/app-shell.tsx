"use client";

import Link from "next/link";
import {usePathname} from "next/navigation";
import useSWR from "swr";
import {Activity, CheckSquare2, History, Radar, Settings, ShieldAlert} from "lucide-react";
import {apiFetch} from "@/lib/api";
import {clsx} from "clsx";
import type {ReactNode} from "react";

const navigation = [
  {href: "/", label: "Investigations", icon: History},
  {href: "/simulate", label: "Simulate", icon: Radar},
  {href: "/approvals", label: "Approvals", icon: CheckSquare2},
  {href: "/settings", label: "Settings", icon: Settings},
];

function SystemIndicator() {
  const {data} = useSWR<Record<string, string>>("/system/status", (path: string) => apiFetch(path), {refreshInterval: 10000});
  const values = Object.values(data || {});
  const state = !data ? "checking" : values.every((value) => value === "healthy") ? "operational" : values.some((value) => value === "unhealthy") ? "degraded" : "partial";
  return <div className={clsx("system-indicator", `system-${state}`)} title={data ? Object.entries(data).map(([key, value]) => `${key}: ${value}`).join("\n") : "Checking dependencies"}><Activity size={15} aria-hidden="true" /><span>{state === "checking" ? "Checking system" : `System ${state}`}</span></div>;
}

export function AppShell({children}: {children: ReactNode}) {
  const pathname = usePathname();
  const active = navigation.find((item) => item.href === "/" ? pathname === "/" : pathname.startsWith(item.href));
  const routeTitle = pathname.startsWith("/investigation/") ? "Investigation detail" : active?.label || "Wayfinder";
  return <div className="app-shell">
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="Wayfinder home"><span className="brand-mark"><ShieldAlert size={19} aria-hidden="true" /></span><span><strong>Wayfinder</strong><small>Incident response</small></span></Link>
      <nav aria-label="Primary navigation">
        {navigation.map(({href, label, icon: Icon}) => <Link key={href} href={href} className={clsx("nav-link", (href === "/" ? pathname === "/" : pathname.startsWith(href)) && "is-active")}><Icon size={18} aria-hidden="true" /><span>{label}</span></Link>)}
      </nav>
      <div className="sidebar-note"><span className="live-pulse" aria-hidden="true" /><span>Evidence streams live</span></div>
    </aside>
    <div className="app-frame">
      <header className="topbar"><div><span className="breadcrumb">Wayfinder /</span> {routeTitle}</div><SystemIndicator /></header>
      <main id="main-content">{children}</main>
    </div>
  </div>;
}
