"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, PlaySquare, Layers, FileText } from "lucide-react";
import { motion } from "framer-motion";

const navItems = [
  { name: "Playground", href: "/playground", icon: PlaySquare },
  { name: "Pipelines", href: "/pipelines", icon: Layers },
  { name: "Evaluations", href: "/evaluations", icon: Activity },
  { name: "Documents", href: "/documents", icon: FileText },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 glass border-r border-white/10 flex flex-col h-full relative z-20">
      <div className="p-6">
        <h1 className="text-2xl font-bold text-gradient tracking-tight">NeuroFlow</h1>
        <p className="text-xs text-white/50 mt-1 uppercase tracking-widest font-semibold">Intelligence Ops</p>
      </div>

      <nav className="flex-1 px-4 space-y-2 mt-4">
        {navItems.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link key={item.name} href={item.href}>
              <div
                className={`relative flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 group ${
                  isActive ? "text-white" : "text-white/60 hover:text-white hover:bg-white/5"
                }`}
              >
                {isActive && (
                  <motion.div
                    layoutId="sidebar-active"
                    className="absolute inset-0 bg-primary/20 border border-primary/30 rounded-lg -z-10"
                    initial={false}
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
                <item.icon size={18} className={isActive ? "text-primary" : "group-hover:text-white"} />
                <span className="font-medium text-sm">{item.name}</span>
              </div>
            </Link>
          );
        })}
      </nav>
      
      <div className="p-4 border-t border-white/10 text-xs text-white/40 text-center">
        v2.0.0-beta
      </div>
    </aside>
  );
}
