import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "NeuroFlow",
  description: "Intelligence Operations for RAG Systems",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} text-foreground bg-background antialiased flex h-screen overflow-hidden`}>
        <Sidebar />
        <main className="flex-1 overflow-y-auto relative z-10">
          {children}
        </main>
      </body>
    </html>
  );
}
