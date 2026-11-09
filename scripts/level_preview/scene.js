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

function validWaits(waits, pathLength) {
  return waits && typeof waits === 'object' && !Array.isArray(waits) &&
    Object.entries(waits).every(([point, seconds]) =>
      /^(0|[1-9][0-9]*)$/.test(point) && Number(point) < pathLength &&
      Number.isFinite(seconds) && seconds >= 0);
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
    const {enemyId, time, path, waits = {}, hiddenWaits = {}, jumps: jumpIndices = [], patrolStart = null} = event ?? {};
    if (typeof enemyId !== 'string' || !Object.hasOwn(source, enemyId) || !source[enemyId]) {
      throw new Error(`Spawn ${index + 1}: missing original actor resources for ${enemyId}`);
    }
    const config = source[enemyId];
    if (!configs.has(enemyId)) {
      const attack = config.periodicAttack;
      if (typeof config.skeleton !== 'string' || !config.skeleton ||
          typeof config.clip !== 'string' || !config.clip ||
          !positive(config.skeletonScale) || !positive(config.graphicScale) ||
          !positive(config.clipSpeed ?? 1)) {
        throw new Error(`${enemyId}: missing or invalid original Spine resources`);
      }
      if (attack && (typeof attack.clip !== 'string' || !attack.clip || !positive(attack.clipSpeed) ||
          !Number.isFinite(attack.firstAt) || attack.firstAt < 0 || !positive(attack.duration) ||
          !positive(attack.interval) || attack.interval <= attack.duration)) {
        throw new Error(`${enemyId}: invalid original periodic cast timing`);
      }
      const phases = attack?.phases;
      if (phases && (!Array.isArray(phases) || phases[0]?.start !== 0 || phases.some((phase, i) =>
          typeof phase.clip !== 'string' || !phase.clip || !positive(phase.clipSpeed) ||
          !Number.isFinite(phase.start) || phase.start >= attack.duration ||
          (i > 0 && phase.start <= phases[i - 1].start)))) {
        throw new Error(`${enemyId}: invalid original channeling phases`);
      }
      configs.set(enemyId, config);
    }
    if (!Number.isFinite(time) || time < 0 || !Array.isArray(path) || !path.length ||
        path.some(point => !Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite))) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid time or route`);
    }
    if (!validWaits(waits, path.length) || !validWaits(hiddenWaits, path.length)) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid route waits`);
    }
    if (!Array.isArray(jumpIndices) || jumpIndices.some(i => !Number.isInteger(i) || i < 0 || i >= path.length - 1)) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid teleport segments`);
    }
    const jumps = new Set(jumpIndices);
    if (Object.keys(hiddenWaits).some(i => !jumps.has(Number(i)))) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): hidden waits need a reappearance point`);
    }
    const length = path.reduce((sum, [x, y], i) => i === 0 || jumps.has(i - 1) ? sum :
      sum + Math.hypot(x - path[i - 1][0], y - path[i - 1][1]), 0);
    const speed = event.moveSpeed ?? config.moveSpeed;
    if (speed === undefined || speed === null) defaultSpeedCount++;
    const moveSpeed = speed ?? 1;
    const waitTime = [...Object.values(waits), ...Object.values(hiddenWaits)].reduce((sum, seconds) => sum + seconds, 0);
    const routeTime = length / moveSpeed + waitTime;
    if (!positive(moveSpeed) || !positive(routeTime)) {
      throw new Error(`Spawn ${index + 1} (${enemyId}): invalid speed or empty route`);
    }
    let patrol = null;
    if (patrolStart !== null) {
      const last = path.at(-1);
      if (!Number.isInteger(patrolStart) || patrolStart < 0 || patrolStart >= path.length - 1 ||
          !last.every((value, axis) => value === path[patrolStart][axis])) {
        throw new Error(`Spawn ${index + 1} (${enemyId}): invalid patrol loop`);
      }
      const intro = path.slice(0, patrolStart).reduce((sum, [x, y], i) => sum +
        (waits[i] ?? 0) + (hiddenWaits[i] ?? 0) +
        (jumps.has(i) ? 0 : Math.hypot(path[i + 1][0] - x, path[i + 1][1] - y) / moveSpeed), 0);
      const cycle = routeTime - intro;
      if (!positive(cycle)) throw new Error(`Spawn ${index + 1} (${enemyId}): empty patrol loop`);
      patrol = {intro, cycle};
    }
    const end = patrol ? Infinity : event.exitTime ?? time + routeTime;
    return {enemyId, time, path, waits, hiddenWaits, jumps, moveSpeed, end, patrol,
      attack: config.periodicAttack};
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
    const phases = config.periodicAttack?.phases ?? [];
    for (const clip of [config.clip, config.idleClip, config.periodicAttack?.clip, ...phases.map(phase => phase.clip)]) {
      if (clip && !data.findAnimation(clip)) throw new Error(`${id}: Spine animation ${clip} missing`);
    }
    const sprite = new PIXI.spine.Spine(data);
    sprite.autoUpdate = false;
    sprite.position.set(origin, origin);
    if (config.initialSkin) sprite.skeleton.setSkinByName(config.initialSkin);
    const track = sprite.state.setAnimation(0, config.clip, config.clipLoop ?? true);
    return [id, {config, sprite, track, version: data.version}];
  }));
}

function routeAt({path, waits, hiddenWaits, jumps, moveSpeed, patrol}, elapsed) {
  if (patrol && elapsed >= patrol.intro) {
    elapsed = patrol.intro + (elapsed - patrol.intro) % patrol.cycle;
  }
  let direction = -1;
  let motionTime = 0;
  for (let i = 0; i < path.length; i++) {
    const [x, y] = path[i];
    const wait = waits[i] ?? 0;
    if (elapsed < wait) return [x, y, direction, motionTime, elapsed];
    elapsed -= wait;
    const hiddenWait = hiddenWaits[i] ?? 0;
    if (elapsed < hiddenWait) return null;
    elapsed -= hiddenWait;
    if (i + 1 === path.length) break;
    if (jumps.has(i)) continue;
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

function actorClocks(battleAge, attack) {
  if (!attack || battleAge < attack.firstAt) return {routeAge: battleAge};
  const elapsed = battleAge - attack.firstAt;
  const cycles = Math.floor(elapsed / attack.interval);
  const within = elapsed % attack.interval;
  return {
    routeAge: battleAge - cycles * attack.duration - Math.min(within, attack.duration),
    attackTime: within < attack.duration ? within : undefined,
  };
}

function updateActorPose(actor, motionTime, idleTime, attackTime) {
  const {sprite, config} = actor;
  const idle = idleTime !== undefined && config.idleClip;
  const attack = attackTime === undefined ? null : config.periodicAttack;
  const phase = attack?.phases?.findLast(item => item.start <= attackTime) ?? attack;
  const clip = phase?.clip ?? (idle || config.clip);
  const loop = phase ? (phase.loop ?? false) : (idle ? config.idleClipLoop : config.clipLoop) ?? true;
  const seconds = phase ? attackTime - (phase.start ?? 0) : (idle ? idleTime : motionTime);
  const speed = (phase?.clipSpeed ?? (idle ? config.idleClipSpeed : config.clipSpeed)) ?? 1;
  // One sprite is reused across instances and may be evaluated after seeking backwards.
  if (actor.track.animation.name !== clip || actor.track.loop !== loop) {
    sprite.state.clearTrack(0);
    actor.track = sprite.state.setAnimation(0, clip, loop);
  }
  sprite.skeleton.setToSetupPose();
  actor.track.trackTime = seconds * speed;
  sprite.update(0);
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

async function loadActorShadows(layout, configs) {
  const loader = new THREE.TextureLoader();
  const textures = new Map();
  const shadows = await Promise.all([...configs].map(async ([id, config]) => {
    const shadow = config.shadow ?? (config.actorPlane ? null : layout.actorShadow);
    if (!shadow) return null;
    if (!textures.has(shadow.texture)) textures.set(shadow.texture, loader.loadAsync(shadow.texture));
    const map = await textures.get(shadow.texture);
    map.colorSpace = THREE.SRGBColorSpace;
    let geometry;
    if (shadow.vertices) {
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(shadow.vertices.flat(), 3));
      geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 1, 1], 2));
      geometry.setIndex([0, 1, 2, 2, 1, 3]);
    } else {
      geometry = new THREE.PlaneGeometry(...shadow.size).translate(...shadow.offset);
    }
    const color = new THREE.Color().setRGB(...(shadow.color ?? [1, 1, 1]), THREE.SRGBColorSpace);
    const material = new THREE.MeshBasicMaterial({
      map, color, transparent: true, depthWrite: false, side: THREE.DoubleSide, opacity: shadow.opacity,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
    });
    return [id, {geometry, material}];
  }));
  return new Map(shadows.filter(Boolean));
}

function createActorLayer(scene, layout, shadows, actors, events, stationary) {
  if (!events.length && !stationary.length) return () => 0;
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
  const planes = new Map();
  for (const [id, {config}] of actors) {
    if (!config.actorPlane) continue;
    const [x, y] = config.actorPlane.map(axis => new THREE.Vector3().fromArray(axis));
    planes.set(id, new THREE.Matrix4().makeBasis(x, y, new THREE.Vector3().crossVectors(x, y).normalize()));
  }
  const avatarGeometry = new THREE.PlaneGeometry(1, 1);
  const firstShadow = shadows.values().next().value;
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
    const shadow = firstShadow ? new THREE.Mesh(firstShadow.geometry, firstShadow.material) : null;
    if (shadow) {
      shadow.renderOrder = -1;
      scene.add(shadow);
    }
    scene.add(avatar);
    const slot = {avatar, shadow, context, texture};
    slots.push(slot);
    return slot;
  }

  function* visiblePoses(time) {
    for (const event of stationary) {
      if (event.time > time) break;
      yield {actorId: event.actorId, position: event.position, direction: event.direction,
        motionTime: time - event.time, predefined: true};
    }
    for (const event of events) {
      if (event.time > time) break;
      if (event.end <= time) continue;
      const {routeAge, attackTime} = actorClocks(time - event.time, event.attack);
      const position = routeAt(event, routeAge);
      if (!position) continue;
      const [col, row, direction, motionTime, idleTime] = position;
      yield {actorId: event.enemyId, position: [col, row], direction, motionTime, idleTime, attackTime};
    }
  }

  const planeScale = new THREE.Vector3();
  return time => {
    let visible = 0;
    for (const {actorId, position, direction, motionTime, idleTime, attackTime, predefined} of visiblePoses(time)) {
      const slot = slots[visible++] ?? addSlot();
      const actor = actors.get(actorId);
      const {sprite, config} = actor;
      const {avatar, shadow, context, texture} = slot;
      avatar.visible = true;
      if (predefined) avatar.position.fromArray(position);
      else avatar.position.copy(worldOrigin).addScaledVector(columns, position[0]).addScaledVector(rows, position[1]);
      if (shadow) {
        const shape = shadows.get(actorId);
        shadow.visible = Boolean(shape);
        if (shape) {
          shadow.geometry = shape.geometry;
          shadow.material = shape.material;
          shadow.position.copy(avatar.position);
        }
      }
      avatar.position.add(offsets.get(actorId));

      updateActorPose(actor, motionTime, idleTime, attackTime);
      const bounds = sprite.getLocalBounds();
      const extent = Math.max(Math.abs(bounds.x), Math.abs(bounds.right),
        Math.abs(bounds.y), Math.abs(bounds.bottom));
      const pixelsPerUnit = Math.min(resolution, (origin - 2) / extent);
      sprite.scale.set(pixelsPerUnit * direction, pixelsPerUnit);
      const plane = planes.get(actorId);
      avatar.matrixAutoUpdate = !plane;
      if (plane) {
        planeScale.setScalar(actorCanvas / pixelsPerUnit);
        avatar.matrix.copy(plane).scale(planeScale).setPosition(avatar.position);
        avatar.matrixWorldNeedsUpdate = true;
      } else {
        avatar.scale.setScalar(actorCanvas / pixelsPerUnit * config.graphicScale * (layout.actorScale ?? 1));
      }
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
  const stationary = layout.predefinedActors?.events ?? [];
  for (const [id, config] of Object.entries(layout.predefinedActors?.configs ?? {})) configs.set(id, config);
  const loader = new GLTFLoader();
  const [map, actors, lighting, shadows, ...props] = await Promise.all([
    loader.loadAsync(layout.asset),
    loadActors(configs),
    loadBattleLighting(layout),
    loadActorShadows(layout, configs),
    ...layout.props.map(prop => loader.loadAsync(prop.asset)),
  ]);
  const renderer = new THREE.WebGLRenderer({
    antialias: true, preserveDrawingBuffer: Boolean(capture),
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
  map.scene.traverse(node => {
    if (!node.isMesh || !node.userData.unityShadowOnly) return;
    // The shadow pass uses its own depth material.
    node.material = node.material.clone();
    node.material.colorWrite = false;
    node.material.depthWrite = false;
    node.castShadow = true;
  });
  scene.add(map.scene);
  const timedProps = [];
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
    for (const [index, xyz] of prop.positions.entries()) {
      const copy = model.clone();
      copy.position.fromArray(xyz);
      const time = prop.activationTimes?.[index];
      if (time !== undefined) timedProps.push({copy, time});
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

  const renderActors = createActorLayer(scene, layout, shadows, actors, events, stationary);
  let maxVisibleActors = 0;

  function render(time) {
    maxVisibleActors = Math.max(maxVisibleActors, renderActors(time));
    for (const prop of timedProps) {
      const visible = time >= prop.time;
      if (visible === prop.copy.visible) continue;
      prop.copy.visible = visible;
      sun.shadow.needsUpdate = true;
    }
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
  const speed = document.querySelector('#speed');
  const slider = document.querySelector('#time');
  const stamp = document.querySelector('#stamp');
  const lastExit = events.reduce((end, event) => Math.max(end, event.patrol ? event.time : event.end), 0);
  const duration = run.complete === true && Number.isFinite(run.duration)
    ? run.duration : Math.max(lastExit, run.duration ?? 0);
  slider.max = String(duration + 1);
  document.querySelector('footer span').textContent = run.caption ?? layout.asset;
  function seek(time) {
    slider.value = time;
    stamp.value = time.toFixed(2) + ' 秒';
    render(Number.isFinite(run.battleDeadline) ? Math.min(time, run.battleDeadline) : time);
  }
  let startedAt = null;
  let startTime = 0;
  let rate = Number(speed.value);
  let handle;
  function timeAt(now) {
    return Math.min(startTime + Math.max(0, now - startedAt) / 1000 * rate, Number(slider.max));
  }
  function playFrame(now) {
    const time = timeAt(now);
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
    startTime = Number(slider.value);
    startedAt = performance.now();
    play.textContent = '暂停';
    handle = requestAnimationFrame(playFrame);
  });
  speed.addEventListener('change', () => {
    if (startedAt !== null) {
      const now = performance.now();
      startTime = timeAt(now);
      startedAt = now;
    }
    rate = Number(speed.value);
  });
  slider.addEventListener('input', () => { pause(); seek(Number(slider.value)); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pause();
  });
  play.disabled = false;
  speed.disabled = false;
  slider.disabled = false;
  seek(0);
}

main().catch(error => {
  document.querySelector('#stamp').textContent = String(error);
  if (capture) post('/error', error.stack || String(error));
});
