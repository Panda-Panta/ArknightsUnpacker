import * as THREE from 'three';
import { GLTFLoader } from './three/GLTFLoader.js';
import { applyBattleLighting, loadBattleLighting } from './battle_lighting.js';

const query = new URLSearchParams(location.search);
const capture = query.get('capture');
const post = (path, body) => fetch(path, {method:'POST', body});
const width = 960;
const height = 540;
const resolution = 100;
const actorCanvas = 512;
const origin = 256;

function positive(value) {
  return Number.isFinite(value) && value > 0;
}

function prepareRun(run) {
  const legacy = run.actors === undefined && run.events === undefined;
  const source = legacy ? {enemy: run} : run.actors;
  const entries = legacy ? [{enemyId: 'enemy', time: run.spawn, path: run.path, waits: run.waits}] : run.events;
  if (!source || typeof source !== 'object' || Array.isArray(source) || !Array.isArray(entries)) {
    throw new Error('Invalid preview fixture: expected actors and events');
  }
  const configs = new Map();
  let defaultSpeedCount = 0;
  const events = entries.map((event, index) => {
    const {enemyId, time, path, waits = {}} = event ?? {};
    if (typeof enemyId !== 'string' || !Object.hasOwn(source, enemyId) || !source[enemyId]) {
      throw new Error(`Spawn ${index + 1}: missing original actor resources for ${enemyId}`);
    }
    const config = source[enemyId];
    if (!configs.has(enemyId)) {
      if (typeof config.skeleton !== 'string' || !config.skeleton ||
          typeof config.clip !== 'string' || !config.clip ||
          !positive(config.skeletonScale) || !positive(config.graphicScale) ||
          !positive(config.clipSpeed ?? 1)) {
        throw new Error(`${enemyId}: missing or invalid original Spine resources`);
      }
      configs.set(enemyId, config);
    }
    if (!Number.isFinite(time) || time < 0 || !Array.isArray(path) || !path.length ||
        path.some(point => !Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite))) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid time or route`);
    }
    if (!waits || typeof waits !== 'object' || Array.isArray(waits) ||
        Object.entries(waits).some(([point, seconds]) =>
          !/^(0|[1-9][0-9]*)$/.test(point) || Number(point) >= path.length ||
          !Number.isFinite(seconds) || seconds < 0)) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid route waits`);
    }
    const length = path.reduce((sum, [x, y], i) => i === 0 ? sum :
      sum + Math.hypot(x - path[i - 1][0], y - path[i - 1][1]), 0);
    const speed = event.moveSpeed ?? config.moveSpeed;
    if (speed === undefined || speed === null) defaultSpeedCount++;
    const moveSpeed = speed ?? 1;
    const waitTime = Object.values(waits).reduce((sum, seconds) => sum + seconds, 0);
    const end = time + length / moveSpeed + waitTime;
    if (!positive(moveSpeed) || !Number.isFinite(end) || end <= time) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid speed or empty route`);
    }
    return {enemyId, time, path, waits, moveSpeed, end};
  });
  events.sort((a, b) => a.time - b.time);
  return {configs, events, defaultSpeedCount};
}

async function loadActors(configs) {
  if (!configs.size) return new Map();
  const loader = new PIXI.Loader();
  const assetNames = new Map();
  const actorNames = new Map();
  for (const [id, config] of configs) {
    const key = `${config.skeletonScale}:${config.skeleton}`;
    if (!assetNames.has(key)) {
      const name = `actor-${assetNames.size}`;
      assetNames.set(key, name);
      loader.add(name, config.skeleton, {metadata: {spineSkeletonScale: config.skeletonScale}});
    }
    actorNames.set(id, assetNames.get(key));
  }
  const resources = await new Promise((resolve, reject) => {
    loader.onError.add((error, _, resource) => {
      reject(new Error(`Failed to load original Spine resource ${resource?.url || ''}: ${error.message}`));
    });
    loader.load((_, loaded) => resolve(loaded));
  });
  return new Map(Array.from(configs, ([id, config]) => {
    const data = resources[actorNames.get(id)]?.spineData;
    if (!data) throw new Error(`${id}: Spine data or atlas missing (${config.skeleton})`);
    if (!data.findAnimation(config.clip)) throw new Error(`${id}: Spine animation ${config.clip} missing`);
    const sprite = new PIXI.spine.Spine(data);
    sprite.autoUpdate = false;
    sprite.position.set(origin, origin);
    const track = sprite.state.setAnimation(0, config.clip, true);
    return [id, {config, sprite, track, version: data.version}];
  }));
}

function routeAt({path, waits, moveSpeed}, elapsed) {
  let direction = -1;
  let motionTime = 0;
  for (let i = 0; i < path.length; i++) {
    const [x, y] = path[i];
    const wait = waits[i] ?? 0;
    if (elapsed < wait) return [x, y, direction, motionTime];
    elapsed -= wait;
    if (i + 1 === path.length) break;
    const [nextX, nextY] = path[i + 1];
    const step = Math.hypot(nextX - x, nextY - y) / moveSpeed;
    if (nextX !== x) direction = Math.sign(nextX - x);
    if (elapsed < step) {
      const part = elapsed / step;
      return [x + (nextX - x) * part, y + (nextY - y) * part, direction, motionTime + elapsed];
    }
    elapsed -= step;
    motionTime += step;
  }
  return null;
}

function applySpineDepth(material, baseline) {
  material.onBeforeCompile = shader => {
    shader.uniforms.baselineZ = {value: baseline};
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float baselineZ;')
      .replace('#include <project_vertex>', `#include <project_vertex>
        // Port the AlphaSplit vertex pass from Unity's -Z into this scene's +Z.
        vec4 world = modelMatrix * vec4(transformed, 1.0);
        float dz = world.z - baselineZ;
        world.y += -1.732051 * dz + min(2.309402 * dz, 0.0);
        world.z = max(baselineZ + 4.0 * dz, baselineZ);
        vec4 depthClip = projectionMatrix * viewMatrix * world;
        gl_Position.z = gl_Position.w * (depthClip.z / depthClip.w);
      `);
  };
}

function createActorLayer(scene, layout, footShadow, actors, events) {
  if (!events.length) return () => 0;
  const surface = new PIXI.Application({
    width: actorCanvas, height: actorCanvas, autoStart: false,
    antialias: true, backgroundAlpha: 0, preserveDrawingBuffer: true,
  });
  const worldOrigin = new THREE.Vector3().fromArray(layout.origin);
  const columns = new THREE.Vector3().fromArray(layout.columns);
  const rows = new THREE.Vector3().fromArray(layout.rows);
  const defaultOffset = new THREE.Vector3().fromArray(layout.actorOffset ?? [0, 0, 0]);
  const offsets = new Map(Array.from(actors, ([id, {config}]) => [id,
    config.actorOffset ? new THREE.Vector3().fromArray(config.actorOffset) : defaultOffset,
  ]));
  const shadowOffset = footShadow ? new THREE.Vector3().fromArray(layout.actorShadow.offset) : null;
  const avatarGeometry = new THREE.PlaneGeometry(1, 1);
  const shadowGeometry = footShadow ? new THREE.PlaneGeometry(...layout.actorShadow.size) : null;
  const shadowMaterial = footShadow ? new THREE.MeshBasicMaterial({
    map: footShadow, transparent: true, depthWrite: false, opacity: layout.actorShadow.opacity,
  }) : null;
  const slots = [];

  function addSlot() {
    // The shared Pixi canvas is overwritten for each pose. Give each visible
    // Three mesh its own snapshot and reuse these slots across spawn events.
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = actorCanvas;
    const context = canvas.getContext('2d');
    context.globalCompositeOperation = 'copy';
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.generateMipmaps = false;
    texture.minFilter = THREE.LinearFilter;
    const material = new THREE.MeshBasicMaterial({
      map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide,
    });
    applySpineDepth(material, layout.actorBaseline ?? 0);
    const avatar = new THREE.Mesh(avatarGeometry, material);
    avatar.rotation.x = Math.PI / 6;
    const shadow = footShadow ? new THREE.Mesh(shadowGeometry, shadowMaterial) : null;
    if (shadow) {
      shadow.renderOrder = -1;
      scene.add(shadow);
    }
    scene.add(avatar);
    const slot = {avatar, shadow, context, texture};
    slots.push(slot);
    return slot;
  }

  return time => {
    let visible = 0;
    for (const event of events) {
      if (event.time > time) break;
      if (event.end <= time) continue;
      const position = routeAt(event, time - event.time);
      if (!position) continue;
      const [col, row, direction, motionTime] = position;
      const slot = slots[visible++] ?? addSlot();
      const actor = actors.get(event.enemyId);
      const {sprite, track, config} = actor;
      const {avatar, shadow, context, texture} = slot;
      avatar.visible = true;
      avatar.position.copy(worldOrigin).addScaledVector(columns, col).addScaledVector(rows, row);
      if (shadow) {
        shadow.visible = true;
        shadow.position.copy(avatar.position).add(shadowOffset);
      }
      avatar.position.add(offsets.get(event.enemyId));

      // Evaluate a pose from its own spawn time even after a backward seek or
      // when two instances of this skeleton are drawn in the same frame.
      sprite.skeleton.setToSetupPose();
      track.trackTime = motionTime * (config.clipSpeed ?? 1);
      sprite.update(0);
      const bounds = sprite.getLocalBounds();
      const extent = Math.max(Math.abs(bounds.x), Math.abs(bounds.right),
        Math.abs(bounds.y), Math.abs(bounds.bottom));
      const pixelsPerUnit = Math.min(resolution, (origin - 2) / extent);
      sprite.scale.set(pixelsPerUnit * direction, pixelsPerUnit);
      avatar.scale.setScalar(actorCanvas / pixelsPerUnit * config.graphicScale * (layout.actorScale ?? 1));
      surface.renderer.render(sprite);
      context.drawImage(surface.view, 0, 0);
      texture.needsUpdate = true;
    }
    for (let i = visible; i < slots.length; i++) {
      slots[i].avatar.visible = false;
      if (slots[i].shadow) slots[i].shadow.visible = false;
    }
    return visible;
  };
}

async function main() {
  const [run, layout] = await Promise.all(
    ['fixture.json', 'scene-layout.json'].map(path => fetch(path).then(r => r.json())),
  );
  const {configs, events, defaultSpeedCount} = prepareRun(run);
  const loader = new GLTFLoader();
  const [map, actors, lighting, footShadow, ...props] = await Promise.all([
    loader.loadAsync(layout.asset),
    loadActors(configs),
    loadBattleLighting(layout),
    configs.size && layout.actorShadow ? new THREE.TextureLoader().loadAsync(layout.actorShadow.texture) : null,
    ...layout.props.map(prop => loader.loadAsync(prop.asset)),
  ]);
  const renderer = new THREE.WebGLRenderer({
    antialias: true, preserveDrawingBuffer: true,
  });
  renderer.setSize(width, height);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  document.querySelector('#stage').appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(layout.background || '#201b18');
  const camera = new THREE.PerspectiveCamera(layout.camera.fov, width / height, 0.3, 1000);
  camera.position.fromArray(layout.camera.position);
  camera.lookAt(new THREE.Vector3().fromArray(layout.camera.target));
  const lightingStats = applyBattleLighting(map.scene, lighting);
  scene.add(map.scene);
  props.forEach(({scene: model}, index) => {
    const prop = layout.props[index];
    model.traverse(node => {
      if (!node.isMesh) return;
      if (node.material.userData.unityShader === 'Torappu/Scene/Trap/Shadow') {
        const source = node.material;
        node.material = new THREE.MeshLambertMaterial({
          map: source.map,
          emissiveMap: source.map,
          emissive: 0xffffff,
          emissiveIntensity: source.userData.unityFloats._Ambient,
        });
      }
      if (node.material.userData.unityBlend === 'additive') {
        node.material.blending = THREE.AdditiveBlending;
      }
      if (node.material.transparent) node.material.depthWrite = false;
      node.castShadow = !node.material.transparent;
      node.receiveShadow = !node.material.transparent;
    });
    for (const xyz of prop.positions) {
      const copy = model.clone();
      copy.position.fromArray(xyz);
      scene.add(copy);
    }
  });
  const fill = new THREE.HemisphereLight(0xfff2da, 0x987e67, layout.ambient);
  fill.position.set(0, 0, 1);
  scene.add(fill);
  const sun = new THREE.DirectionalLight(new THREE.Color().fromArray(layout.sun.color), layout.sun.intensity);
  sun.target.position.set(10, 2, 0);
  sun.position.fromArray(layout.sun.rayDirection).multiplyScalar(-30).add(sun.target.position);
  scene.add(sun.target);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {left:-15, right:15, top:12, bottom:-12, near:5, far:55});
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.normalBias = 0.025;
  sun.shadow.autoUpdate = false;
  sun.shadow.needsUpdate = true;
  scene.add(sun);

  const renderActors = createActorLayer(scene, layout, footShadow, actors, events);
  let maxVisibleActors = 0;

  function render(time) {
    maxVisibleActors = Math.max(maxVisibleActors, renderActors(time));
    renderer.render(scene, camera);
  }

  if (capture) {
    const count = Number(capture);
    const start = Number(query.get('start') ?? 0);
    const fps = Number(query.get('fps') ?? 30);
    const format = query.get('format') === 'jpg' ? 'image/jpeg' : 'image/png';
    for (let i = 0; i < count; i++) {
      render(start + i / fps);
      const blob = await new Promise(resolve => renderer.domElement.toBlob(resolve, format, 0.97));
      await post('/frame/' + i, blob);
    }
    const actorDetails = Array.from(actors, ([enemyId, actor]) => ({
      enemyId, clip: actor.config.clip, version: actor.version,
    }));
    await post('/done', JSON.stringify({
      scene: layout.asset,
      clip: actorDetails[0]?.clip ?? null,
      version: actorDetails[0]?.version ?? null,
      camera: layout.camera,
      spawn: events[0]?.time ?? 0,
      events: events.length,
      actors: actorDetails,
      defaultSpeedCount,
      maxVisibleActors,
      start,
      fps,
      actorDepth: 'alpha-split-z-distorted',
      lighting: lightingStats,
    }));
    return;
  }

  const play = document.querySelector('#play');
  const slider = document.querySelector('#time');
  const stamp = document.querySelector('#stamp');
  const lastExit = events.reduce((end, event) => Math.max(end, event.end), 0);
  slider.max = String(Math.max(lastExit, run.duration ?? 0) + 1);
  document.querySelector('footer span').textContent = run.caption ?? layout.asset;
  function seek(time) {
    slider.value = time;
    stamp.value = time.toFixed(2) + ' 秒';
    render(time);
  }
  let startedAt = null;
  let handle;
  function playFrame() {
    const time = Math.min((performance.now() - startedAt) / 1000, Number(slider.max));
    seek(time);
    if (time < Number(slider.max)) {
      handle = requestAnimationFrame(playFrame);
    } else {
      pause();
    }
  }
  function pause() {
    cancelAnimationFrame(handle);
    startedAt = null;
    play.textContent = '播放';
  }
  play.addEventListener('click', () => {
    if (startedAt !== null) {
      pause();
      return;
    }
    if (Number(slider.value) >= Number(slider.max)) seek(0);
    startedAt = performance.now() - Number(slider.value) * 1000;
    play.textContent = '暂停';
    handle = requestAnimationFrame(playFrame);
  });
  slider.addEventListener('input', () => { pause(); seek(Number(slider.value)); });
  play.disabled = false;
  slider.disabled = false;
  seek(0);
}

main().catch(error => {
  document.querySelector('#stamp').textContent = String(error);
  if (capture) post('/error', error.stack || String(error));
});
