import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { MapInfo, MapPlayer } from "./backend";
import { GOAL_HEIGHT, GOAL_WIDTH, LENGTH, PENALTY_SPOTS, WIDTH, pitchLines } from "./pitch";

export type CameraMode = "top" | "3d";

interface Props {
  map: MapInfo | null;
  colors: [string, string];
  mode: CameraMode;
  showIds: boolean;
  showView: boolean;
}

const MARGIN = 6; // metros de grama em volta das linhas
const PX_PER_M = 14;
const REFEREE = "#f59e0b";
const GOALKEEPER_RING = "#a855f7";
const UNKNOWN = "#9ca3af";
const BALL = "#facc15";
const FOLLOW_RATE = 9; // quanto maior, mais rápido o boneco chega à nova posição

/** Na vista de cima o rótulo fica acima do boneco na tela (para o lado do campo de lá); na 3D, acima da cabeça. */
function placeLabel(label: THREE.Sprite, mode: CameraMode): void {
  if (mode === "top") {
    label.position.set(0, 2.2, -2.3);
    label.scale.set(2.8, 1.4, 1);
  } else {
    label.position.set(0, 3.3, 0);
    label.scale.set(3.2, 1.6, 1);
  }
}

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
  // Faixas do gramado
  const stripes = 14;
  const stripeW = (LENGTH / stripes) * PX_PER_M;
  for (let i = 0; i < stripes; i += 2) {
    ctx.fillStyle = "#348541";
    ctx.fillRect((MARGIN * PX_PER_M) + i * stripeW, MARGIN * PX_PER_M, stripeW, WIDTH * PX_PER_M);
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
  const net = new THREE.Mesh(
    new THREE.PlaneGeometry(GOAL_WIDTH, GOAL_HEIGHT),
    new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.18, side: THREE.DoubleSide }),
  );
  net.rotation.y = Math.PI / 2;
  net.position.copy(toScene(x + (side === 0 ? -1.5 : 1.5), WIDTH / 2, GOAL_HEIGHT / 2));
  group.add(net);
  return group;
}

const labelCache = new Map<string, THREE.Texture>();
function labelTexture(text: string): THREE.Texture {
  const cached = labelCache.get(text);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "rgba(11,13,10,0.75)";
  ctx.beginPath();
  ctx.roundRect(8, 8, 112, 48, 14);
  ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.font = "600 34px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 64, 34);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  labelCache.set(text, texture);
  return texture;
}

interface Figure {
  group: THREE.Group;
  body: THREE.Mesh<THREE.CylinderGeometry, THREE.MeshStandardMaterial>;
  ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  label: THREE.Sprite;
  target: THREE.Vector3;
  fresh: boolean;
}

function playerColor(p: MapPlayer, colors: [string, string]): string {
  if (p.t === 0 || p.t === 1) return colors[p.t];
  if (p.l.includes("árbitro")) return REFEREE;
  if (p.l === "goleiro") return GOALKEEPER_RING;
  return UNKNOWN;
}

function playerKey(p: MapPlayer): string {
  return p.id !== null ? `id${p.id}` : `g${Math.round(p.x)}_${Math.round(p.y)}`;
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  figures: Map<string, Figure>;
  bodyGeometry: THREE.CylinderGeometry;
  ringGeometry: THREE.RingGeometry;
  ball: THREE.Mesh;
  ballTarget: THREE.Vector3;
  trail: THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>;
  view: THREE.Mesh<THREE.ShapeGeometry, THREE.MeshBasicMaterial>;
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
    // Como a câmera principal da TV, um pouco mais alta: o campo inteiro cabe na largura.
    const scale = Math.max(1, 1.47 / aspect);
    camera.position.set(0, 72 * scale, 104 * scale);
  }
  controls.target.set(0, 0, mode === "top" ? 0 : 6);
  controls.update();
}

/** Mapa 3D do campo com os jogadores, a bola e a área que a câmera da TV mostra. */
export function FieldMap3D({ map, colors, mode, showIds, showView }: Props) {
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

    const view = new THREE.Mesh(
      new THREE.ShapeGeometry(new THREE.Shape()),
      new THREE.MeshBasicMaterial({
        color: "#ffffff",
        transparent: true,
        opacity: 0.12,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );
    view.rotation.x = Math.PI / 2;
    view.position.y = 0.03;
    scene.add(view);

    const ball = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 20, 14),
      new THREE.MeshStandardMaterial({ color: BALL, emissive: BALL, emissiveIntensity: 0.4 }),
    );
    ball.visible = false;
    scene.add(ball);
    const trail = new THREE.Line(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: BALL, transparent: true, opacity: 0.7 }),
    );
    scene.add(trail);

    const state: SceneState = {
      renderer,
      scene,
      camera,
      controls,
      figures: new Map(),
      bodyGeometry: new THREE.CylinderGeometry(1.05, 1.05, 1.9, 24),
      ringGeometry: new THREE.RingGeometry(1.35, 1.75, 28),
      ball,
      ballTarget: new THREE.Vector3(),
      trail,
      view,
    };
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
      for (const figure of state.figures.values()) {
        if (figure.fresh) {
          figure.group.position.copy(figure.target);
          figure.fresh = false;
        } else {
          figure.group.position.lerp(figure.target, k);
        }
      }
      if (ball.visible) ball.position.lerp(state.ballTarget, k);
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
    if (state && host) {
      placeCamera(state, mode, host.clientWidth, host.clientHeight);
      for (const figure of state.figures.values()) placeLabel(figure.label, mode);
    }
  }, [mode]);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const players = map?.players ?? [];
    const keep = new Set<string>();

    for (const p of players) {
      const key = playerKey(p);
      keep.add(key);
      let figure = state.figures.get(key);
      if (!figure) {
        const body = new THREE.Mesh(state.bodyGeometry, new THREE.MeshStandardMaterial({ roughness: 0.6 }));
        body.position.y = 0.95;
        const ring = new THREE.Mesh(
          state.ringGeometry,
          new THREE.MeshBasicMaterial({ color: GOALKEEPER_RING, side: THREE.DoubleSide, transparent: true }),
        );
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.04;
        const label = new THREE.Sprite(new THREE.SpriteMaterial({ depthTest: false, transparent: true }));
        placeLabel(label, modeRef.current);
        const group = new THREE.Group();
        group.add(body, ring, label);
        state.scene.add(group);
        figure = { group, body, ring, label, target: new THREE.Vector3(), fresh: true };
        state.figures.set(key, figure);
      }
      figure.target.copy(toScene(p.x, p.y));
      figure.body.material.color.set(playerColor(p, colors));
      figure.body.material.transparent = p.g;
      figure.body.material.opacity = p.g ? 0.3 : 1;
      figure.ring.visible = p.l === "goleiro";
      figure.ring.material.opacity = p.g ? 0.3 : 1;
      figure.label.visible = showIds && p.id !== null && !p.g;
      if (figure.label.visible) {
        const texture = labelTexture(String(p.id));
        if (figure.label.material.map !== texture) {
          figure.label.material.map = texture;
          figure.label.material.needsUpdate = true;
        }
      }
    }
    for (const [key, figure] of state.figures) {
      if (keep.has(key)) continue;
      state.scene.remove(figure.group);
      figure.body.material.dispose();
      figure.ring.material.dispose();
      figure.label.material.dispose();
      state.figures.delete(key);
    }

    if (map?.ball) {
      state.ballTarget.copy(toScene(map.ball.x, map.ball.y, 0.55));
      if (!state.ball.visible) state.ball.position.copy(state.ballTarget);
      state.ball.visible = true;
      (state.ball.material as THREE.MeshStandardMaterial).opacity = map.ball.e ? 0.5 : 1;
      (state.ball.material as THREE.MeshStandardMaterial).transparent = map.ball.e;
    } else {
      state.ball.visible = false;
    }
    const trailPoints = (map?.trail ?? []).map(([x, y]) => toScene(x, y, 0.08));
    state.trail.geometry.dispose();
    state.trail.geometry = new THREE.BufferGeometry().setFromPoints(trailPoints);

    state.view.geometry.dispose();
    if (showView && map?.view && map.scene === "ao vivo") {
      // A forma é desenhada no plano x/y e girada para o chão: y da forma = z da cena.
      const shape = new THREE.Shape(map.view.map(([x, y]) => new THREE.Vector2(x - LENGTH / 2, y - WIDTH / 2)));
      state.view.geometry = new THREE.ShapeGeometry(shape);
      state.view.visible = true;
    } else {
      state.view.geometry = new THREE.ShapeGeometry(new THREE.Shape());
      state.view.visible = false;
    }
  }, [map, colors, showIds, showView]);

  return <div ref={hostRef} className="map3d" />;
}
