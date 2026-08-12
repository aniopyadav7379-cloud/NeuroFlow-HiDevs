import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/shared/Sidebar";

// Deliberately NOT next/font/google: this environment's network egress
// is restricted to package registries (npm/pypi/github), not
// fonts.googleapis.com, so a Google Fonts fetch would fail at build
// time. System font stacks (declared in tailwind.config.ts) give a
// clean technical sans/mono pairing with zero external dependency.

export const metadata: Metadata = {
  title: "NeuroFlow Console",
  description: "Observe and tune NeuroFlow's RAG pipelines",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="flex bg-canvas font-sans text-ink antialiased">
        <Providers>
          <Sidebar />
          <main className="h-screen flex-1 overflow-y-auto">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
