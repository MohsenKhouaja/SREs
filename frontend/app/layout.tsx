import type {Metadata} from "next";
import {AppShell} from "@/components/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: {default: "SREs · Evidence before action", template: "%s · SREs"},
  description: "Evidence-first incident response with accountable human approval.",
  icons: {icon: "/brand/logo.png"},
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body><a className="skip-link" href="#main-content">Skip to content</a><AppShell>{children}</AppShell></body></html>;
}
