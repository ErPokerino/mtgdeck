import React, { useCallback, useEffect, useRef, useState } from "react";
import { GripVertical, GripHorizontal, RotateCcw } from "lucide-react";

interface ResizableSplitPaneProps {
  storageKey: string;
  defaultLeftPct?: number;
  minLeftPct?: number;
  maxLeftPct?: number;
  direction?: "horizontal" | "vertical";
  left?: React.ReactNode;
  right?: React.ReactNode;
  leftPane?: React.ReactNode;
  rightPane?: React.ReactNode;
  className?: string;
}

export const ResizableSplitPane: React.FC<ResizableSplitPaneProps> = ({
  storageKey,
  defaultLeftPct = 42,
  minLeftPct = 22,
  maxLeftPct = 78,
  direction = "horizontal",
  left,
  right,
  leftPane,
  rightPane,
  className = "",
}) => {
  const firstNode = left ?? leftPane;
  const secondNode = right ?? rightPane;
  const containerRef = useRef<HTMLDivElement>(null);
  const [leftPct, setLeftPct] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(`split_${storageKey}`);
      if (saved) {
        const parsed = parseFloat(saved);
        if (
          !Number.isNaN(parsed) &&
          parsed >= minLeftPct &&
          parsed <= maxLeftPct
        ) {
          return parsed;
        }
      }
    } catch {
      // ignore storage errors
    }
    return defaultLeftPct;
  });

  const [isDragging, setIsDragging] = useState(false);

  const savePct = useCallback(
    (val: number) => {
      const clamped = Math.min(
        maxLeftPct,
        Math.max(minLeftPct, Math.round(val * 10) / 10),
      );
      setLeftPct(clamped);
      try {
        localStorage.setItem(`split_${storageKey}`, String(clamped));
      } catch {
        // ignore
      }
    },
    [maxLeftPct, minLeftPct, storageKey],
  );

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      if (direction === "horizontal") {
        const relX = e.clientX - rect.left;
        const pct = (relX / Math.max(1, rect.width)) * 100;
        savePct(pct);
      } else {
        const relY = e.clientY - rect.top;
        const pct = (relY / Math.max(1, rect.height)) * 100;
        savePct(pct);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.body.style.cursor =
      direction === "horizontal" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isDragging, direction, savePct]);

  const isHoriz = direction === "horizontal";

  return (
    <div
      ref={containerRef}
      className={`flex ${isHoriz ? "flex-col lg:flex-row" : "flex-col"} w-full ${className}`}
    >
      {/* Left / Top Pane */}
      <div
        style={
          isHoriz
            ? { width: `calc(${leftPct}% - 6px)` }
            : { height: `calc(${leftPct}% - 6px)` }
        }
        className={`${isHoriz ? "max-lg:!w-full" : ""} min-w-0 shrink-0 transition-[width,height] duration-75 ease-out`}
      >
        {firstNode}
      </div>

      {/* Interactive Resizer Handle */}
      <div
        onMouseDown={() => setIsDragging(true)}
        onDoubleClick={() => savePct(defaultLeftPct)}
        title="Trascina per ridimensionare i riquadri (Doppio click per ripristinare)"
        className={`group relative flex items-center justify-center shrink-0 select-none ${
          isHoriz
            ? "hidden lg:flex w-3 cursor-col-resize mx-0.5 self-stretch"
            : "h-3 cursor-row-resize my-0.5 w-full"
        }`}
      >
        <div
          className={`${
            isHoriz ? "w-[2px] h-full" : "h-[2px] w-full"
          } rounded-full transition-colors ${
            isDragging
              ? "bg-[#C8AA6E] shadow-[0_0_8px_#C8AA6E]"
              : "bg-[#1E2638] group-hover:bg-[#C8AA6E]/70"
          }`}
        />
        <div
          className={`absolute z-20 flex items-center justify-center rounded-md border transition-all ${
            isHoriz ? "w-4 h-10 flex-col" : "h-4 w-10 flex-row"
          } ${
            isDragging
              ? "bg-[#C8AA6E] text-[#090B10] border-[#F3E5C8] scale-105"
              : "bg-[#121826] text-slate-400 border-[#26324B] group-hover:text-[#F3E5C8] group-hover:border-[#C8AA6E]/60"
          }`}
        >
          {isHoriz ? (
            <GripVertical className="w-3 h-3" />
          ) : (
            <GripHorizontal className="w-3 h-3" />
          )}
        </div>

        {/* Quick Preset Pill on Hover */}
        {isHoriz && (
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="opacity-0 group-hover:opacity-100 pointer-events-none group-hover:pointer-events-auto transition-opacity absolute top-2 z-30 flex items-center gap-0.5 px-1.5 py-0.5 rounded-md bg-[#0D111A]/95 border border-[#2B3856] shadow-xl text-[9px] font-mono-tech text-slate-300"
          >
            <button
              type="button"
              onClick={() => savePct(30)}
              className="px-1 py-0.5 rounded hover:bg-[#1E2942] hover:text-[#F3E5C8] cursor-pointer"
            >
              30%
            </button>
            <button
              type="button"
              onClick={() => savePct(defaultLeftPct)}
              className="px-1 py-0.5 rounded hover:bg-[#1E2942] hover:text-[#F3E5C8] cursor-pointer flex items-center gap-0.5"
              title="Reset proporzioni"
            >
              <RotateCcw className="w-2.5 h-2.5" />
            </button>
            <button
              type="button"
              onClick={() => savePct(65)}
              className="px-1 py-0.5 rounded hover:bg-[#1E2942] hover:text-[#F3E5C8] cursor-pointer"
            >
              65%
            </button>
          </div>
        )}
      </div>

      {/* Right / Bottom Pane */}
      <div
        style={
          isHoriz
            ? { width: `calc(${100 - leftPct}% - 6px)` }
            : { height: `calc(${100 - leftPct}% - 6px)` }
        }
        className={`${isHoriz ? "max-lg:!w-full" : ""} min-w-0 flex-1 transition-[width,height] duration-75 ease-out`}
      >
        {secondNode}
      </div>
    </div>
  );
};
