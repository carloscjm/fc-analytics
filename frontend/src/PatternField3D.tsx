import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PatternRole, TeamPattern } from "./backend";
import { GOAL_HEIGHT, GOAL_WIDTH, LENGTH, PENALTY_SPOTS, WIDTH, pitchLines } from "./pitch";

export type CameraMode = "top" | "3d";

interface Props {
  pattern: TeamPattern | null;
  color: string;
  mode: CameraMode;
  showHeat: boolean;
}

const MARGIN = 6;
const PX_PER_M = 14;
const FOLLOW_RATE = 6;

/** Campo em metros → cena: origem no centro, x para a direita, z para quem assiste. */
function toScene(x: number, y: number, height = 0): THREE.Vector3 {
  return new THREE.Vector3(x - LENGTH / 2, height, y - WIDTH / 2);
}

function pitchTexture(): THREE.CanvasTexture {
  const w = Math.round((LENGTH + 2 * MARGIN) * PX_PER_M);
  const h = Math.round((WIDTH + 2 * MARGIN) * PX_PER_M);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#2f7a3a";
  ctx.fillRect(0, 0, w, h);
  const stripes = 14;
  const stripeW = (LENGTH / stripes) * PX_PER_M;
  for (let i = 0; i < stripes; i += 2) {
    ctx.fillStyle = "#348541";
    ctx.fillRect(MARGIN * PX_PER_M + i * stripeW, MARGIN * PX_PER_M, stripeW, WIDTH * PX_PER_M);
  }
  const px = (x: number, y: number): [number, number] => [(x + MARGIN) * PX_PER_M, (y + MARGIN) * PX_PER_M];
  ctx.strokeStyle = "rgba(255,255,255,0.9)";
  ctx.lineWidth = 0.14 * PX_PER_M;
  ctx.lineJoin = "round";
  for (const line of pitchLines(32)) {
    ctx.beginPath();
    line.forEach(([x, y], i) => {
      const [u, v] = px(x, y);
      if (i === 0) ctx.moveTo(u, v);
      else ctx.lineTo(u, v);
    });
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  for (const [x, y] of PENALTY_SPOTS) {
    const [u, v] = px(x, y);
    ctx.beginPath();
    ctx.arc(u, v, 0.25 * PX_PER_M, 0, Math.PI * 2);
    ctx.fill();
  }
  // Sentido do ataque, escrito na faixa de grama além da lateral de cá.
  const [, ay] = px(LENGTH / 2, WIDTH + MARGIN / 2);
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.font = `600 ${Math.round(2.4 * PX_PER_M)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("sentido do ataque  →", w / 2, ay);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

function goal(side: 0 | 1): THREE.Group {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color: "#f8fafc", roughness: 0.4 });
  const post = new THREE.CylinderGeometry(0.08, 0.08, GOAL_HEIGHT, 8);
  const bar = new THREE.CylinderGeometry(0.08, 0.08, GOAL_WIDTH, 8);
  const x = side === 0 ? 0 : LENGTH;
  for (const dy of [-GOAL_WIDTH / 2, GOAL_WIDTH / 2]) {
    const mesh = new THREE.Mesh(post, material);
    mesh.position.copy(toScene(x, WIDTH / 2 + dy, GOAL_HEIGHT / 2));
    group.add(mesh);
  }
  const crossbar = new THREE.Mesh(bar, material);
  crossbar.rotation.x = Math.PI / 2;
  crossbar.position.copy(toScene(x, WIDTH / 2, GOAL_HEIGHT));
  group.add(crossbar);
  return group;
}

/** Mapa de calor como textura semitransparente na cor do time. */
function heatTexture(pattern: TeamPattern, color: string): THREE.CanvasTexture {
  const { nx, ny, values } = pattern.heat;
  const small = document.createElement("canvas");
  small.width = nx;
  small.height = ny;
  const sctx = small.getContext("2d")!;
  const c = new THREE.Color(color);
  const image = sctx.createImageData(nx, ny);
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const v = values[j * nx + i] ?? 0;
      const k = (j * nx + i) * 4;
      image.data[k] = Math.round(c.r * 255);
      image.data[k + 1] = Math.round(c.g * 255);
      image.data[k + 2] = Math.round(c.b * 255);
      image.data[k + 3] = Math.round(Math.pow(v, 0.7) * 190);
    }
  }
  sctx.putImageData(image, 0, 0);
  // Ampliado com suavização: as células de 5 m viram manchas contínuas.
  const big = document.createElement("canvas");
  big.width = nx * 24;
  big.height = ny * 24;
  const bctx = big.getContext("2d")!;
  bctx.imageSmoothingEnabled = true;
  bctx.imageSmoothingQuality = "high";
  bctx.filter = "blur(10px)";
  bctx.drawImage(small, 0, 0, big.width, big.height);
  const texture = new THREE.CanvasTexture(big);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Ordem estável das posições entre atualizações: por linha e, dentro dela, da esquerda para a direita. */
function ordered(roles: PatternRole[]): PatternRole[] {
  return [...roles].sort((a, b) => a.line - b.line || a.y - b.y);
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  bodies: THREE.Mesh<THREE.CylinderGeometry, THREE.MeshStandardMaterial>[];
  zones: THREE.Mesh<THREE.CircleGeometry, THREE.MeshBasicMaterial>[];
  targets: THREE.Vector3[];
  zoneScales: THREE.Vector2[];
  lines: THREE.Group;
  heat: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
}

function placeCamera(state: SceneState, mode: CameraMode, width: number, height: number): void {
  const { camera, controls } = state;
  const aspect = width / Math.max(1, height);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  if (mode === "top") {
    const needH = (WIDTH + 2 * MARGIN) / 2 / Math.tan(fov / 2);
    const needW = (LENGTH + 2 * MARGIN) / 2 / (Math.tan(fov / 2) * aspect);
    camera.position.set(0, Math.max(needH, needW), 0.01);
  } else {
    const scale = Math.max(1, 1.47 / aspect);
    camera.position.set(0, 72 * scale, 104 * scale);
  }
  controls.target.set(0, 0, mode === "top" ? 0 : 6);
  controls.update();
}

/** Campo 3D com o padrão de um time: posições médias, linhas da formação e mapa de calor. */
export function PatternField3D({ pattern, color, mode, showHeat }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<SceneState | null>(null);
  const modeRef = useRef(mode);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0f1a12");
    const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.minDistance = 20;
    controls.maxDistance = 260;
    scene.add(new THREE.AmbientLight("#ffffff", 1.6));
    const sun = new THREE.DirectionalLight("#ffffff", 1.6);
    sun.position.set(-30, 80, 40);
    scene.add(sun);

    const field = new THREE.Mesh(
      new THREE.PlaneGeometry(LENGTH + 2 * MARGIN, WIDTH + 2 * MARGIN),
      new THREE.MeshStandardMaterial({ map: pitchTexture(), roughness: 1 }),
    );
    field.rotation.x = -Math.PI / 2;
    scene.add(field);
    scene.add(goal(0), goal(1));

    const heat = new THREE.Mesh(
      new THREE.PlaneGeometry(LENGTH, WIDTH),
      new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }),
    );
    heat.rotation.x = -Math.PI / 2;
    heat.position.y = 0.02;
    heat.visible = false;
    scene.add(heat);

    const lines = new THREE.Group();
    scene.add(lines);

    const state: SceneState = {
      renderer,
      scene,
      camera,
      controls,
      bodies: [],
      zones: [],
      targets: [],
      zoneScales: [],
      lines,
      heat,
    };
    const bodyGeometry = new THREE.CylinderGeometry(1.15, 1.15, 2.0, 24);
    const zoneGeometry = new THREE.CircleGeometry(1, 40);
    for (let i = 0; i < 10; i++) {
      const body = new THREE.Mesh(bodyGeometry, new THREE.MeshStandardMaterial({ roughness: 0.55 }));
      body.visible = false;
      const zone = new THREE.Mesh(
        zoneGeometry,
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.22, depthWrite: false }),
      );
      zone.rotation.x = -Math.PI / 2;
      zone.visible = false;
      scene.add(body, zone);
      state.bodies.push(body);
      state.zones.push(zone);
      state.targets.push(new THREE.Vector3());
      state.zoneScales.push(new THREE.Vector2(1, 1));
    }
    stateRef.current = state;

    const resize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(1, h);
      camera.updateProjectionMatrix();
      placeCamera(state, modeRef.current, w, h);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);

    let frame = 0;
    let last = performance.now();
    const animate = () => {
      frame = requestAnimationFrame(animate);
      const now = performance.now();
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      const k = 1 - Math.exp(-FOLLOW_RATE * dt);
      state.bodies.forEach((body, i) => {
        body.position.lerp(state.targets[i], k);
        const zone = state.zones[i];
        zone.position.set(body.position.x, 0.03, body.position.z);
        zone.scale.x += (state.zoneScales[i].x - zone.scale.x) * k;
        zone.scale.y += (state.zoneScales[i].y - zone.scale.y) * k;
      });
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      renderer.dispose();
      host.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  useEffect(() => {
    modeRef.current = mode;
    const state = stateRef.current;
    const host = hostRef.current;
    if (state && host) placeCamera(state, mode, host.clientWidth, host.clientHeight);
  }, [mode]);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const roles = pattern ? ordered(pattern.roles) : [];
    const first = state.bodies.every((b) => !b.visible);

    state.bodies.forEach((body, i) => {
      const role = roles[i];
      const zone = state.zones[i];
      if (!role) {
        body.visible = false;
        zone.visible = false;
        return;
      }
      state.targets[i].copy(toScene(role.x, role.y, 1.0));
      // Mancha = onde esse jogador costuma ficar (1 desvio padrão em cada direção, no mínimo 2 m).
      state.zoneScales[i].set(Math.max(2, role.sx), Math.max(2, role.sy));
      if (first) {
        body.position.copy(state.targets[i]);
        zone.scale.set(state.zoneScales[i].x, state.zoneScales[i].y, 1);
      }
      body.material.color.set(color);
      zone.material.color.set(color);
      body.visible = true;
      zone.visible = true;
    });

    // Linhas da formação: liga as posições de cada linha, da esquerda para a direita.
    for (const child of [...state.lines.children]) {
      state.lines.remove(child);
      (child as THREE.Line).geometry.dispose();
    }
    if (pattern) {
      const byLine = new Map<number, PatternRole[]>();
      for (const r of roles) byLine.set(r.line, [...(byLine.get(r.line) ?? []), r]);
      for (const group of byLine.values()) {
        if (group.length < 2) continue;
        const pts = group.sort((a, b) => a.y - b.y).map((r) => toScene(r.x, r.y, 0.06));
        state.lines.add(
          new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(pts),
            new THREE.LineBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.75 }),
          ),
        );
      }
    }

    state.heat.material.map?.dispose();
    if (pattern && showHeat) {
      state.heat.material.map = heatTexture(pattern, color);
      state.heat.material.needsUpdate = true;
      state.heat.visible = true;
    } else {
      state.heat.material.map = null;
      state.heat.visible = false;
    }
  }, [pattern, color, showHeat]);

  return <div ref={hostRef} className="map3d" />;
}
