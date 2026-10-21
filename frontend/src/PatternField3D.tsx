import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PatternRole, TeamPattern } from "./backend";
import { GOAL_HEIGHT, GOAL_WIDTH, LENGTH, PENALTY_SPOTS, WIDTH, pitchLines } from "./pitch";

export type CameraMode = "top" | "3d";

/** Um time desenhado no campo. `mirror` gira o padrão (que vem sempre atacando para a direita) para o outro lado. */
export interface PatternLayer {
  pattern: TeamPattern | null;
  color: string;
  mirror: boolean;
}

/** De quem é cada gol. O ataque vai sempre da esquerda para a direita. */
export interface FieldEnds {
  /** gol de quem ataca */
  left: { label: string; color: string };
  /** gol de quem defende */
  right: { label: string; color: string };
  /** frase na lateral de cá, por exemplo "Time A ataca → Time B defende" */
  center: string;
}

interface Props {
  layers: PatternLayer[];
  mode: CameraMode;
  showHeat: boolean;
  ends: FieldEnds;
}

const MAX_LAYERS = 2;
const ROLES = 10;

const MARGIN = 6;
const PX_PER_M = 14;
const FOLLOW_RATE = 6;

/** Campo em metros → cena: origem no centro, x para a direita, z para quem assiste. */
function toScene(x: number, y: number, height = 0): THREE.Vector3 {
  return new THREE.Vector3(x - LENGTH / 2, height, y - WIDTH / 2);
}

function pitchTexture(ends: FieldEnds): THREE.CanvasTexture {
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
  // Faixas atrás de cada gol na cor do dono, com o nome escrito: deixa claro de quem é cada gol.
  const band = MARGIN * PX_PER_M;
  const font = (m: number) => `700 ${Math.round(m * PX_PER_M)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (const [end, x0, angle] of [
    [ends.left, 0, -Math.PI / 2],
    [ends.right, w - band, Math.PI / 2],
  ] as const) {
    ctx.globalAlpha = 0.75;
    ctx.fillStyle = end.color;
    ctx.fillRect(x0, 0, band, h);
    ctx.globalAlpha = 1;
    ctx.save();
    ctx.translate(x0 + band / 2, h / 2);
    ctx.rotate(angle);
    ctx.font = font(2.6);
    ctx.lineWidth = 0.5 * PX_PER_M;
    ctx.strokeStyle = "rgba(0,0,0,0.55)";
    ctx.strokeText(end.label.toUpperCase(), 0, 0);
    ctx.fillStyle = "#ffffff";
    ctx.fillText(end.label.toUpperCase(), 0, 0);
    ctx.restore();
  }
  // Quem ataca e quem defende, escrito na faixa de grama além da lateral de cá.
  const [, ay] = px(LENGTH / 2, WIDTH + MARGIN / 2);
  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.font = font(2.4);
  ctx.fillText(ends.center, w / 2, ay);
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
function heatTexture(pattern: TeamPattern, color: string, mirror: boolean): THREE.CanvasTexture {
  const { nx, ny } = pattern.heat;
  const values = mirror ? [...pattern.heat.values].reverse() : pattern.heat.values;
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

// ---------------------------------------------------------------------------
// Jogador em 3D feito de formas simples: cabeça, tronco com camisa, braços,
// calção, pernas, meiões e chuteiras. Fica de frente para o gol que ataca (+x).
// ---------------------------------------------------------------------------

// Bem maior que o real (1,8 m), para dar para ver cada jogador com o campo inteiro na tela.
// Visto de cima o jogador mostra só cabeça e ombros, então ele cresce um pouco mais.
const PLAYER_SCALE: Record<CameraMode, number> = { top: 3.4, "3d": 2.6 };
const SKIN = "#c99a74";
const HAIR = "#2b211c";
const BOOT = "#151515";

interface PlayerFigure {
  group: THREE.Group;
  jersey: THREE.MeshStandardMaterial;
  shorts: THREE.MeshStandardMaterial;
  socks: THREE.MeshStandardMaterial;
}

const geometryCache: Record<string, THREE.BufferGeometry> = {};
function geo(key: string, make: () => THREE.BufferGeometry): THREE.BufferGeometry {
  return (geometryCache[key] ??= make());
}

const sharedMaterials = {
  skin: new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.7 }),
  hair: new THREE.MeshStandardMaterial({ color: HAIR, roughness: 0.9 }),
  boot: new THREE.MeshStandardMaterial({ color: BOOT, roughness: 0.5 }),
};

function makePlayer(): PlayerFigure {
  const jersey = new THREE.MeshStandardMaterial({ roughness: 0.6 });
  const shorts = new THREE.MeshStandardMaterial({ roughness: 0.6 });
  const socks = new THREE.MeshStandardMaterial({ roughness: 0.7 });
  const group = new THREE.Group();
  const add = (mesh: THREE.Mesh, x: number, y: number, z: number, rz = 0, rx = 0) => {
    mesh.position.set(x, y, z);
    mesh.rotation.z = rz;
    mesh.rotation.x = rx;
    group.add(mesh);
    return mesh;
  };

  // Pernas (coxa e canela), meiões e chuteiras.
  for (const side of [-1, 1]) {
    const z = side * 0.11;
    add(new THREE.Mesh(geo("thigh", () => new THREE.CapsuleGeometry(0.075, 0.32, 4, 10)), sharedMaterials.skin), 0, 0.72, z);
    add(new THREE.Mesh(geo("shin", () => new THREE.CapsuleGeometry(0.06, 0.3, 4, 10)), socks), 0, 0.32, z);
    add(new THREE.Mesh(geo("boot", () => new THREE.BoxGeometry(0.26, 0.08, 0.11)), sharedMaterials.boot), 0.06, 0.05, z);
  }
  // Calção e camisa.
  add(new THREE.Mesh(geo("shorts", () => new THREE.CylinderGeometry(0.2, 0.23, 0.24, 14)), shorts), 0, 0.93, 0);
  add(new THREE.Mesh(geo("torso", () => new THREE.CapsuleGeometry(0.19, 0.38, 6, 14)), jersey), 0, 1.3, 0);
  // Ombros e braços (manga na cor da camisa, antebraço de pele).
  for (const side of [-1, 1]) {
    const z = side * 0.27;
    add(new THREE.Mesh(geo("sleeve", () => new THREE.CapsuleGeometry(0.065, 0.16, 4, 10)), jersey), 0, 1.44, z, 0, side * 0.18);
    add(new THREE.Mesh(geo("forearm", () => new THREE.CapsuleGeometry(0.05, 0.26, 4, 10)), sharedMaterials.skin), 0.02, 1.13, side * 0.31, 0, side * 0.1);
  }
  // Pescoço, cabeça e cabelo.
  add(new THREE.Mesh(geo("neck", () => new THREE.CylinderGeometry(0.06, 0.07, 0.08, 10)), sharedMaterials.skin), 0, 1.62, 0);
  add(new THREE.Mesh(geo("head", () => new THREE.SphereGeometry(0.12, 18, 14)), sharedMaterials.skin), 0, 1.76, 0);
  const hair = add(
    new THREE.Mesh(geo("hair", () => new THREE.SphereGeometry(0.125, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2)), sharedMaterials.hair),
    -0.01,
    1.79,
    0,
  );
  hair.rotation.z = 0.15;

  group.scale.setScalar(PLAYER_SCALE["3d"]);
  return { group, jersey, shorts, socks };
}

/** Calção e meião um pouco mais escuros que a camisa, para dar contraste. */
function paint(figure: PlayerFigure, color: string): void {
  const base = new THREE.Color(color);
  figure.jersey.color.copy(base);
  figure.shorts.color.copy(base).multiplyScalar(0.55);
  figure.socks.color.copy(base).multiplyScalar(0.8);
}

// Cor de cada setor nas linhas da formação.
export const SECTOR_COLORS = { defesa: "#2f7bff", meio: "#facc15", ataque: "#ef4444" } as const;
const sectorMaterials = {
  defesa: new THREE.LineBasicMaterial({ color: SECTOR_COLORS.defesa }),
  meio: new THREE.LineBasicMaterial({ color: SECTOR_COLORS.meio }),
  ataque: new THREE.LineBasicMaterial({ color: SECTOR_COLORS.ataque }),
};

function sectorOf(line: number, lineCount: number): keyof typeof sectorMaterials {
  if (line === 0) return "defesa";
  if (line === lineCount - 1) return "ataque";
  return "meio";
}

/** Ordem estável das posições entre atualizações: por linha e, dentro dela, da esquerda para a direita. */
function ordered(roles: PatternRole[]): PatternRole[] {
  return [...roles].sort((a, b) => a.line - b.line || a.y - b.y);
}

/** Gira 180° no campo: quem atacava para a direita passa a atacar para a esquerda. */
function mirrored(role: PatternRole): PatternRole {
  return { ...role, x: LENGTH - role.x, y: WIDTH - role.y };
}

interface SceneState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  figures: PlayerFigure[];
  targets: THREE.Vector3[];
  lines: THREE.Group;
  heats: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>[];
  field: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshStandardMaterial>;
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
    const scale = Math.max(1, 1.47 / aspect) * 1.1; // folga para as faixas atrás dos gols
    camera.position.set(0, 72 * scale, 104 * scale);
  }
  controls.target.set(0, 0, mode === "top" ? 0 : 6);
  controls.update();
}

/** Campo 3D com o padrão de um time: posições médias, linhas da formação e mapa de calor. */
export function PatternField3D({ layers, mode, showHeat, ends }: Props) {
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
      new THREE.MeshStandardMaterial({ roughness: 1 }),
    );
    field.rotation.x = -Math.PI / 2;
    scene.add(field);
    scene.add(goal(0), goal(1));

    const heats = Array.from({ length: MAX_LAYERS }, (_, i) => {
      const heat = new THREE.Mesh(
        new THREE.PlaneGeometry(LENGTH, WIDTH),
        new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }),
      );
      heat.rotation.x = -Math.PI / 2;
      heat.position.y = 0.02 + i * 0.005;
      heat.visible = false;
      scene.add(heat);
      return heat;
    });

    const lines = new THREE.Group();
    scene.add(lines);

    const state: SceneState = {
      renderer,
      scene,
      camera,
      controls,
      figures: [],
      targets: [],
      lines,
      heats,
      field,
    };
    for (let i = 0; i < ROLES * MAX_LAYERS; i++) {
      const figure = makePlayer();
      figure.group.visible = false;
      scene.add(figure.group);
      state.figures.push(figure);
      state.targets.push(new THREE.Vector3());
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
      state.figures.forEach((figure, i) => {
        figure.group.position.lerp(state.targets[i], k);
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

  const endsKey = JSON.stringify(ends);
  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const material = state.field.material;
    material.map?.dispose();
    material.map = pitchTexture(ends);
    material.needsUpdate = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endsKey]);

  useEffect(() => {
    modeRef.current = mode;
    const state = stateRef.current;
    const host = hostRef.current;
    if (state && host) placeCamera(state, mode, host.clientWidth, host.clientHeight);
    state?.figures.forEach((f) => f.group.scale.setScalar(PLAYER_SCALE[mode]));
  }, [mode]);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const first = state.figures.every((f) => !f.group.visible);

    for (const child of [...state.lines.children]) {
      state.lines.remove(child);
      (child as THREE.Line).geometry.dispose();
    }

    for (let layerIndex = 0; layerIndex < MAX_LAYERS; layerIndex++) {
      const layer = layers[layerIndex];
      const pattern = layer?.pattern ?? null;
      const roles = pattern ? ordered(pattern.roles).map((r) => (layer.mirror ? mirrored(r) : r)) : [];

      for (let k = 0; k < ROLES; k++) {
        const i = layerIndex * ROLES + k;
        const figure = state.figures[i];
        const role = roles[k];
        if (!role || !layer) {
          figure.group.visible = false;
          continue;
        }
        state.targets[i].copy(toScene(role.x, role.y, 0));
        if (first || !figure.group.visible) figure.group.position.copy(state.targets[i]);
        // De frente para o gol que ataca: quem foi girado (o time que defende) olha para a esquerda.
        figure.group.rotation.y = layer.mirror ? Math.PI : 0;
        paint(figure, layer.color);
        figure.group.visible = true;
      }

      // Linhas da formação: liga as posições de cada linha, de um lado ao outro,
      // em azul (defesa), amarelo (meio-campo) ou vermelho (ataque).
      if (pattern && layer) {
        const byLine = new Map<number, PatternRole[]>();
        for (const r of roles) byLine.set(r.line, [...(byLine.get(r.line) ?? []), r]);
        const lineCount = Math.max(...roles.map((r) => r.line)) + 1;
        for (const [line, group] of byLine) {
          const material = sectorMaterials[sectorOf(line, lineCount)];
          const sorted = group.sort((a, b) => a.y - b.y);
          // Sozinho na linha (um centroavante, por exemplo): um traço curto, para a cor aparecer.
          const pts =
            sorted.length > 1
              ? sorted.map((r) => toScene(r.x, r.y, 0.04))
              : [toScene(sorted[0].x, sorted[0].y - 2.5, 0.04), toScene(sorted[0].x, sorted[0].y + 2.5, 0.04)];
          state.lines.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), material));
        }
      }

      const heat = state.heats[layerIndex];
      heat.material.map?.dispose();
      if (pattern && layer && showHeat) {
        heat.material.map = heatTexture(pattern, layer.color, layer.mirror);
        heat.material.needsUpdate = true;
        heat.visible = true;
      } else {
        heat.material.map = null;
        heat.visible = false;
      }
    }
  }, [layers, showHeat]);

  return <div ref={hostRef} className="map3d" />;
}
