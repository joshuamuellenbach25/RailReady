import { forwardRef, useImperativeHandle, useRef } from "react";

/**
 * Projected 3D pins (HTML buttons over the canvas). Positions are written imperatively every rendered frame by
 * PhotoSceneCanvas via update(); React only re-renders when the pin list / selection changes.
 * Overlap only offsets the label (leader line keeps the true point); the selected pin is drawn on top.
 * Each pin carries data-x/y (CSS px in the inner viewport), data-expected-x/y (u-W, v-H) and data-err for measurement.
 */
const ScenePinLayer = forwardRef(function ScenePinLayer({ sceneTag, pins, selectedId, visible, onSelect, sample }, ref) {
  const els = useRef({});
  const pinsRef = useRef(pins);
  pinsRef.current = pins;

  useImperativeHandle(ref, () => ({
    update(project, W, H) {
      const placed = [];
      const order = [...pinsRef.current].sort((a, b) => (b.item_id === selectedId) - (a.item_id === selectedId) || a.n - b.n);
      for (const p of order) {
        const el = els.current[p.item_id];
        if (!el) continue;
        const s = project(p.xyz);
        if (!s) {
          el.style.display = "none";
          el.dataset.visible = "0";
          continue;
        }
        let dy = 0;
        while (dy > -120 && placed.some((q) => Math.abs(q[0] - s.x) < 26 && Math.abs(q[1] - (s.y + dy)) < 24)) dy -= 24;
        placed.push([s.x, s.y + dy]);
        el.style.display = "";
        el.style.transform = `translate(${s.x}px, ${s.y}px)`;
        el.style.setProperty("--dy", `${dy}px`);
        el.dataset.visible = "1";
        el.dataset.flip = s.y + dy < 44 ? "1" : "0";
        el.dataset.x = s.x.toFixed(2);
        el.dataset.y = s.y.toFixed(2);
        if (p.u != null && p.v != null) {
          const ex = p.u * W;
          const ey = p.v * H;
          el.dataset.expectedX = ex.toFixed(2);
          el.dataset.expectedY = ey.toFixed(2);
          el.dataset.err = Math.hypot(s.x - ex, s.y - ey).toFixed(2);
          const [sw, sh] = sample || [];
          if (sw && sh) {
            // V04: sample-centre reference [(col+0.5)/W, (row+0.5)/H], tolerance half a sample + 2 CSS px
            const cx = ((Math.floor(p.u * sw) + 0.5) / sw) * W;
            const cy = ((Math.floor(p.v * sh) + 0.5) / sh) * H;
            el.dataset.sampleX = cx.toFixed(2);
            el.dataset.sampleY = cy.toFixed(2);
            el.dataset.errSample = Math.hypot(s.x - cx, s.y - cy).toFixed(2);
            el.dataset.tol = (0.5 * Math.max(W / sw, H / sh) + 2).toFixed(2);
          }
        }
      }
    },
  }));

  return (
    <div data-testid="scene-pin-layer" data-scene={sceneTag} aria-hidden={!visible} className={`pointer-events-none absolute inset-0 ${visible ? "" : "hidden"}`}>
      {pins.map((p) => {
        const sel = p.item_id === selectedId;
        return (
          <div key={p.item_id} ref={(el) => (els.current[p.item_id] = el)} data-testid={`scene-pin-${p.item_id}`} data-u={p.u} data-v={p.v}
            className={`rr-pin absolute left-0 top-0 ${sel ? "z-20" : "z-10"}`} style={{ display: "none" }}>
            <span className="rr-pin-dot" />
            <span className="rr-pin-line" />
            <button type="button" data-testid={`scene-marker-${p.item_id}`} aria-label={`Marker ${p.n}: ${p.label}${sel ? " (selected)" : ""}`} aria-pressed={sel}
              onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onSelect(p.item_id); }}
              className={`rr-pin-label pointer-events-auto ${sel ? "rr-pin-sel" : ""}`}>{p.n}</button>
          </div>
        );
      })}
    </div>
  );
});

export default ScenePinLayer;
