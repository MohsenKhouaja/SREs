"use client";

import Link from "next/link";
import Image from "next/image";
import {usePathname} from "next/navigation";
import useSWR from "swr";
import {Activity, CheckSquare2, History, Radar} from "lucide-react";
import {apiFetch} from "@/lib/api";
import {clsx} from "clsx";
import type {ReactNode} from "react";

const navigation = [
  {href: "/investigations", label: "Investigations", icon: History},
  {href: "/lab", label: "Incident lab", icon: Radar},
  {href: "/approvals", label: "Approvals", icon: CheckSquare2},
];

export function classifySystemStatus(data?: Record<string, string>) {
  if (!data) return "checking";
  const values = Object.values(data);
  if (values.length > 0 && values.every((value) => value === "healthy" || value === "configured")) return "operational";
  if (values.some((value) => value === "unhealthy")) return "degraded";
  return "partial";
}

function SystemIndicator() {
  const {data} = useSWR<Record<string, string>>("/system/status", (path: string) => apiFetch(path), {refreshInterval: 10000});
  const state = classifySystemStatus(data);
  return <div className={clsx("system-indicator", `system-${state}`)} title={data ? Object.entries(data).map(([key, value]) => `${key}: ${value}`).join("\n") : "Checking dependencies"}><Activity size={15} aria-hidden="true" /><span>{state === "checking" ? "Checking system" : `System ${state}`}</span></div>;
}

export function AppShell({children}: {children: ReactNode}) {
  const pathname = usePathname();
  if (pathname === "/") return <div className="landing-shell">{children}</div>;
  const active = navigation.find((item) => pathname.startsWith(item.href));
  const routeTitle = pathname.startsWith("/investigation/") ? "Investigation detail" : active?.label || "SREs";
  return <div className="app-shell">
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="SREs home"><span className="brand-mark"><Image src="/brand/logo.png" alt="" width={24} height={24} /></span><span><strong>SREs</strong><small>Incident response</small></span></Link>
      <nav aria-label="Primary navigation">
        {navigation.map(({href, label, icon: Icon}) => <Link key={href} href={href} className={clsx("nav-link", pathname.startsWith(href) && "is-active")}><Icon size={18} aria-hidden="true" /><span>{label}</span></Link>)}
      </nav>
      <div className="sidebar-note"><span className="live-pulse" aria-hidden="true" /><span>Evidence streams live</span></div>
    </aside>
    <div className="app-frame">
      <header className="topbar"><div><span className="breadcrumb">SREs /</span> {routeTitle}</div><SystemIndicator /></header>
      <main id="main-content">{children}</main>
    </div>
  </div>;
}
