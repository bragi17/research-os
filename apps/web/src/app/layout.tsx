import type { Metadata } from "next";
import "./globals.css";
import AnimatedBackground from "@/components/AnimatedBackground";
import WorkspaceHeader from "@/components/WorkspaceHeader";
import LeftResearchTree from "@/components/LeftResearchTree";

export const metadata: Metadata = {
  title: "Research OS",
  description: "AI-powered research orchestration platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen">
        <AnimatedBackground />

        {/* Workspace Header */}
        <WorkspaceHeader />

        {/* Three-panel layout */}
        <div className="relative z-10 flex" style={{ height: "calc(100vh - 56px)" }}>
          {/* Left sidebar: Research tree */}
          <LeftResearchTree />

          {/* Main content area */}
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
