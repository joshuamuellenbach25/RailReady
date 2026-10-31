import { useEffect, useState } from "react";

/**
 * Letterbox fit: inner viewport of aspect iW:iH centred in the panel, s = min(pW/iW, pH/iH).
 * Returns {left, top, width, height} in CSS px relative to the panel (null until measured).
 */
export default function useAspectFit(panelRef, iW, iH) {
  const [fit, setFit] = useState(null);
  useEffect(() => {
    const el = panelRef.current;
    if (!el || !(iW > 0 && iH > 0)) return undefined;
    let raf = 0;
    const measure = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const pW = el.clientWidth;
        const pH = el.clientHeight;
        if (!pW || !pH) return;
        const s = Math.min(pW / iW, pH / iH);
        const width = Math.floor(iW * s);
        const height = Math.floor(iH * s);
        const next = { left: Math.floor((pW - width) / 2), top: Math.floor((pH - height) / 2), width, height };
        setFit((f) => (f && f.left === next.left && f.top === next.top && f.width === next.width && f.height === next.height ? f : next));
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("orientationchange", measure);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("orientationchange", measure);
    };
  }, [panelRef, iW, iH]);
  return fit;
}
