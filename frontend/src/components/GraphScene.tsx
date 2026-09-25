import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import SpriteText from "three-spritetext";
import { colorOf, groupOf } from "../lib/palette";
import type { GraphLink, GraphNode } from "../lib/types";
import { useStore } from "../state/store";

type FG = ForceGraphMethods<GraphNode, GraphLink>;

interface NodeVisual {
  core: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  halo: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>;
  ring?: THREE.Mesh<THREE.TorusGeometry, THREE.MeshBasicMaterial>;
  label: SpriteText;
  baseColor: THREE.Color;
  alwaysLabel: boolean;
}

const BG = "#070a12";
const WHITE = new THREE.Color("#ffffff");
const LINK_BASE = "#34405c";
const LINK_DIM = "#161c2b";
const LINK_HOT = "#9fd3ff";
const IDLE_ROTATE_MS = 15000;

const endId = (end: string | GraphNode) => (typeof end === "object" ? end.id : end);
const radiusOf = (n: GraphNode) => (n.type === "Paper" ? 5 : 1.6 + Math.min(4, Math.sqrt(n.degree) * 0.6));
const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function makeStarfield(): THREE.Points {
  const count = 2500;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    // points on a thick spherical shell far outside the graph
    const r = 1800 + Math.random() * 1600;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions.set([r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi)], i * 3);
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const mat = new THREE.PointsMaterial({ color: 0x8fa3c8, size: 2.2, sizeAttenuation: true, transparent: true, opacity: 0.55 });
  return new THREE.Points(geom, mat);
}

export function GraphScene() {
  const graph = useStore((s) => s.graph);
  const highlight = useStore((s) => s.highlight);
  const focusId = useStore((s) => s.focusId);
  const flyTo = useStore((s) => s.flyTo);
  const hiddenGroups = useStore((s) => s.hiddenGroups);
  const minDegree = useStore((s) => s.minDegree);
  const streaming = useStore((s) => s.streaming);
  const focus = useStore((s) => s.focus);

  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<FG | undefined>(undefined);
  const visuals = useRef(new Map<string, NodeVisual>());
  const hoverRef = useRef<string | null>(null);
  const lastInteraction = useRef(0);
  const framed = useRef(false);
  const [size, setSize] = useState({ width: 800, height: 600 });

  // Stable data object: the simulation mutates nodes/links in place, so never rebuild it on filter changes.
  const data = useMemo(
    () => (graph ? { nodes: graph.nodes.map((n) => ({ ...n })), links: graph.links.map((l) => ({ ...l })) } : { nodes: [], links: [] }),
    [graph],
  );
  const labelThreshold = useMemo(() => {
    const degrees = data.nodes.filter((n) => n.type !== "Paper").map((n) => n.degree).sort((a, b) => b - a);
    return degrees[Math.min(degrees.length - 1, 14)] ?? Infinity; // label roughly the top 15 entities
  }, [data]);

  // ---------------------------------------------------------------- sizing
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.max(200, Math.floor(width)), height: Math.max(200, Math.floor(height)) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---------------------------------------------------------------- scene setup: stars, bloom, orbit
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const stars = makeStarfield();
    const scene = fg.scene();
    scene.add(stars);
    // An opaque scene background keeps the bloom composer from washing the transparent canvas grey.
    scene.background = new THREE.Color(BG);
    // Fallback framing in case the engine is reheated before it ever stops.
    const frameTimer = window.setTimeout(() => {
      if (!framed.current) {
        framed.current = true;
        fg.zoomToFit(900, 50);
      }
    }, 9000);
    // Threshold above the background/link luminance so only nodes (and particles) glow.
    const bloom = new UnrealBloomPass(new THREE.Vector2(size.width, size.height), 0.9, 0.45, 0.35);
    fg.postProcessingComposer().addPass(bloom);
    const controls = fg.controls() as { autoRotate: boolean; autoRotateSpeed: number; addEventListener: (e: string, cb: () => void) => void };
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.35;
    controls.addEventListener("start", () => {
      lastInteraction.current = performance.now();
      controls.autoRotate = false;
    });
    fg.d3Force("charge")?.strength?.(-60);
    const onVisibility = () => (document.hidden ? fg.pauseAnimation() : fg.resumeAnimation());
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(frameTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      scene.remove(stars);
      fg.postProcessingComposer().removePass(bloom);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph !== null]);

  // ---------------------------------------------------------------- node objects (built once per node)
  const nodeThreeObject = useCallback(
    (node: GraphNode) => {
      const r = radiusOf(node);
      const baseColor = new THREE.Color(colorOf(node.type));
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(r, 20, 14),
        new THREE.MeshBasicMaterial({ color: baseColor.clone(), transparent: true, opacity: 0.95 }),
      );
      const halo = new THREE.Mesh(
        new THREE.SphereGeometry(r * 1.9, 16, 12),
        new THREE.MeshBasicMaterial({ color: baseColor.clone(), transparent: true, opacity: 0.08, depthWrite: false }),
      );
      const group = new THREE.Group();
      group.add(halo, core);
      let ring: NodeVisual["ring"];
      if (node.type === "Paper") {
        // secondary (shape) encoding for papers, independent of colour
        ring = new THREE.Mesh(
          new THREE.TorusGeometry(r * 1.6, 0.35, 8, 48),
          new THREE.MeshBasicMaterial({ color: baseColor.clone(), transparent: true, opacity: 0.6 }),
        );
        ring.rotation.x = Math.PI / 2.4;
        group.add(ring);
      }
      const label = new SpriteText(node.label.length > 48 ? `${node.label.slice(0, 46)}…` : node.label, 3.2, "#d7deee");
      label.fontFace = "Inter, system-ui, sans-serif";
      label.backgroundColor = "rgba(7,10,18,0.55)";
      label.padding = 1.2;
      label.borderRadius = 2;
      label.position.set(0, r + 5, 0);
      const alwaysLabel = node.type === "Paper" || node.degree >= labelThreshold;
      label.visible = alwaysLabel;
      group.add(label);
      visuals.current.set(node.id, { core, halo, ring, label, baseColor, alwaysLabel });
      return group;
    },
    [labelThreshold],
  );

  // ---------------------------------------------------------------- highlight styling
  const active = highlight.nodes.size > 0 || focusId !== null;
  useEffect(() => {
    const lit = new Set(highlight.nodes);
    if (focusId) lit.add(focusId);
    for (const [id, v] of visuals.current) {
      const on = lit.has(id);
      const dim = active && !on;
      v.core.material.opacity = dim ? 0.14 : 0.95;
      v.core.material.color.copy(v.baseColor).lerp(WHITE, on ? 0.35 : 0);
      v.halo.material.opacity = dim ? 0.02 : on ? 0.22 : 0.08;
      if (v.ring) v.ring.material.opacity = dim ? 0.1 : 0.6;
      v.label.visible = on || (!active && v.alwaysLabel) || id === hoverRef.current;
    }
  }, [highlight, focusId, active, data]);

  // ---------------------------------------------------------------- pulse animation for latest tool hits
  useEffect(() => {
    if (!highlight.pulse.size) return;
    let raf = 0;
    const tick = () => {
      const t = (performance.now() - highlight.pulseAt) / 1000;
      const fade = Math.max(0, 1 - t / 4);
      for (const id of highlight.pulse) {
        const v = visuals.current.get(id);
        if (v) v.halo.scale.setScalar(1 + fade * 0.9 * (0.5 + 0.5 * Math.sin(t * 7)));
      }
      if (fade > 0) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      for (const id of highlight.pulse) visuals.current.get(id)?.halo.scale.setScalar(1);
    };
  }, [highlight.pulse, highlight.pulseAt]);

  // ---------------------------------------------------------------- camera: fly to touched nodes
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !flyTo) return;
    const controls = fg.controls() as { autoRotate: boolean };
    controls.autoRotate = false;
    lastInteraction.current = performance.now();
    const ids = new Set(flyTo.nodeIds);
    if (ids.size === 0) {
      fg.zoomToFit(1200, 40);
      return;
    }
    const targets = data.nodes.filter((n) => ids.has(n.id) && n.x !== undefined);
    if (targets.length === 1) {
      const n = targets[0];
      const dist = 170;
      const len = Math.hypot(n.x!, n.y!, n.z!) || 1;
      const k = 1 + dist / len;
      fg.cameraPosition({ x: n.x! * k, y: n.y! * k, z: n.z! * k }, { x: n.x!, y: n.y!, z: n.z! }, 1400);
    } else if (targets.length > 1) {
      fg.zoomToFit(1400, 60, (n) => ids.has(n.id));
    }
  }, [flyTo, data]);

  // ---------------------------------------------------------------- resume idle rotation
  useEffect(() => {
    const id = window.setInterval(() => {
      const fg = fgRef.current;
      if (!fg || streaming || focusId) return;
      if (performance.now() - lastInteraction.current > IDLE_ROTATE_MS) (fg.controls() as { autoRotate: boolean }).autoRotate = true;
    }, 2000);
    return () => window.clearInterval(id);
  }, [streaming, focusId]);

  // ---------------------------------------------------------------- filtering (visibility, not data changes)
  const nodeVisible = useCallback(
    (n: GraphNode) => !hiddenGroups.has(groupOf(n.type)) && (n.type === "Paper" || n.degree >= minDegree),
    [hiddenGroups, minDegree],
  );
  const visibleIds = useMemo(() => new Set(data.nodes.filter(nodeVisible).map((n) => n.id)), [data, nodeVisible]);
  const linkVisible = useCallback(
    (l: GraphLink) => visibleIds.has(endId(l.source)) && visibleIds.has(endId(l.target)),
    [visibleIds],
  );

  const hot = (l: GraphLink) => highlight.links.has(l.id);
  const linkColor = useCallback(
    (l: GraphLink) => (hot(l) ? LINK_HOT : active ? LINK_DIM : LINK_BASE),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [highlight, active],
  );
  const linkWidth = useCallback((l: GraphLink) => (hot(l) ? 1.1 : 0), [highlight]); // eslint-disable-line react-hooks/exhaustive-deps
  const linkParticles = useCallback((l: GraphLink) => (hot(l) ? 4 : 0), [highlight]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodeLabel = useCallback(
    (n: GraphNode) =>
      `<div class="graph-tooltip"><strong>${escapeHtml(n.label)}</strong><span>${n.type}${
        n.type === "Paper" ? (n.year ? ` · ${n.year}` : "") : ` · ${n.n_papers ?? 0} paper${n.n_papers === 1 ? "" : "s"}`
      }</span></div>`,
    [],
  );

  const onNodeHover = useCallback(
    (n: GraphNode | null) => {
      const prev = hoverRef.current;
      hoverRef.current = n?.id ?? null;
      if (containerRef.current) containerRef.current.style.cursor = n ? "pointer" : "grab";
      for (const id of [prev, hoverRef.current]) {
        const v = id ? visuals.current.get(id) : undefined;
        if (v) v.label.visible = id === hoverRef.current || (!active && v.alwaysLabel) || highlight.nodes.has(id!) || id === focusId;
      }
    },
    [active, highlight, focusId],
  );

  return (
    <div ref={containerRef} className="graph-scene" aria-label="Knowledge graph (3D)">
      {graph && (
        <ForceGraph3D<GraphNode, GraphLink>
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={data}
          backgroundColor={BG}
          showNavInfo={false}
          controlType="orbit"
          nodeThreeObject={nodeThreeObject}
          nodeVisibility={nodeVisible}
          nodeLabel={nodeLabel}
          linkVisibility={linkVisible}
          linkColor={linkColor}
          linkWidth={linkWidth}
          linkOpacity={0.55}
          linkDirectionalParticles={linkParticles}
          linkDirectionalParticleWidth={1.8}
          linkDirectionalParticleSpeed={0.007}
          linkDirectionalParticleColor={() => LINK_HOT}
          warmupTicks={60}
          cooldownTime={6000}
          onEngineStop={() => {
            if (!framed.current) {
              framed.current = true;
              fgRef.current?.zoomToFit(900, 50);
            }
          }}
          onNodeHover={onNodeHover}
          onNodeClick={(n) => focus(n.id)}
          onBackgroundClick={() => focus(null, false)}
        />
      )}
    </div>
  );
}
