"use client";

import { motion } from "framer-motion";

export function AnimatedGauge({ value, label }: { value: number; label: string }) {
  // Value should be between 0 and 1
  const percentage = Math.round(value * 100);
  
  // Color calculation based on value
  let colorClass = "text-red-500";
  let strokeClass = "stroke-red-500";
  if (value > 0.8) {
    colorClass = "text-green-500";
    strokeClass = "stroke-green-500";
  } else if (value >= 0.6) {
    colorClass = "text-yellow-500";
    strokeClass = "stroke-yellow-500";
  }

  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div className="flex flex-col items-center justify-center space-y-2">
      <div className="relative w-20 h-20 flex items-center justify-center">
        {/* Background circle */}
        <svg className="absolute top-0 left-0 w-full h-full transform -rotate-90">
          <circle
            className="stroke-white/10"
            strokeWidth="6"
            fill="transparent"
            r={radius}
            cx="40"
            cy="40"
          />
          {/* Animated progress circle */}
          <motion.circle
            className={strokeClass}
            strokeWidth="6"
            strokeLinecap="round"
            fill="transparent"
            r={radius}
            cx="40"
            cy="40"
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset }}
            transition={{ duration: 1.5, ease: "easeOut" }}
            style={{ strokeDasharray: circumference }}
          />
        </svg>
        <div className={`absolute font-bold text-lg ${colorClass}`}>
          {percentage}%
        </div>
      </div>
      <span className="text-xs text-white/60 font-medium uppercase tracking-wider">{label}</span>
    </div>
  );
}
