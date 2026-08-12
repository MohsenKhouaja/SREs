"use client";

import {ArrowLeft, ArrowRight} from "lucide-react";
import {useEffect} from "react";

export type PrototypeVariant = {key: string; name: string};

export function PrototypeSwitcher({variants, current, onSelect}: {variants: PrototypeVariant[]; current: string; onSelect: (key: string) => void}) {
  const index = Math.max(0, variants.findIndex((variant) => variant.key === current));

  function cycle(offset: number) {
    onSelect(variants[(index + offset + variants.length) % variants.length].key);
  }

  useEffect(() => {
    function handleKeydown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft") cycle(-1);
      if (event.key === "ArrowRight") cycle(1);
    }
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  });

  if (process.env.NODE_ENV === "production") return null;

  const active = variants[index];
  return <div className="prototype-switcher" aria-label="Prototype variant switcher">
    <button type="button" onClick={() => cycle(-1)} aria-label="Previous prototype variant"><ArrowLeft size={16} /></button>
    <span><strong>{active.key}</strong><span aria-hidden="true"> — </span>{active.name}</span>
    <button type="button" onClick={() => cycle(1)} aria-label="Next prototype variant"><ArrowRight size={16} /></button>
  </div>;
}
