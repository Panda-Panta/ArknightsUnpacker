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

function loadEnemy(config) {
  return new Promise((resolve, reject) => {
    const loader = new PIXI.Loader();
    loader.onError.add(reject);
    loader.add('enemy', config.skeleton, {
      metadata: {spineSkeletonScale: config.skeletonScale},
    });
    loader.load((_, resources) => {
      if (!resources.enemy.spineData) {
        reject(new Error('Spine data missing'));
        return;
      }
      const sprite = new PIXI.spine.Spine(resources.enemy.spineData);
      sprite.autoUpdate = false;
      sprite.state.setAnimation(0, config.clip, true);
      sprite.position.set(origin, origin);
      sprite.scale.set(resolution);
      const surface = new PIXI.Application({
        width: actorCanvas, height: actorCanvas, autoStart: false,
        antialias: true, backgroundAlpha: 0, preserveDrawingBuffer: true,
      });
      surface.stage.addChild(sprite);
      resolve({sprite, surface, version: resources.enemy.spineData.version});
    });
  });
}

function routeAt(points, distance) {
  let direction = -1;
  for (let i = 1; i < points.length; i++) {
    const [x, y] = points[i - 1];
    const [nextX, nextY] = points[i];
    const step = Math.hypot(nextX - x, nextY - y);
    if (nextX !== x) direction = Math.sign(nextX - x);
    if (step && distance < step) {
      const part = distance / step;
      return [x + (nextX - x) * part, y + (nextY - y) * part, direction];
    }
    distance -= step;
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

async function main() {
  const [run, layout] = await Promise.all(
    ['fixture.json', 'scene-layout.json'].map(path => fetch(path).then(r => r.json())),
  );
  const loader = new GLTFLoader();
  const [map, enemy, lighting, footShadow, ...props] = await Promise.all([
    loader.loadAsync(layout.asset),
    loadEnemy(run),
    loadBattleLighting(layout),
    new THREE.TextureLoader().loadAsync(layout.actorShadow.texture),
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

  const texture = new THREE.CanvasTexture(enemy.surface.view);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  const size = actorCanvas / resolution * run.graphicScale * (layout.actorScale ?? 1);
  const actorMaterial = new THREE.MeshBasicMaterial({
    map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide,
  });
  applySpineDepth(actorMaterial, layout.actorBaseline ?? 0);
  const avatar = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    actorMaterial,
  );
  avatar.rotation.x = Math.PI / 6;
  scene.add(avatar);
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(...layout.actorShadow.size),
    new THREE.MeshBasicMaterial({
      map: footShadow, transparent: true, depthWrite: false, opacity: layout.actorShadow.opacity,
    }),
  );
  shadow.renderOrder = -1;
  scene.add(shadow);
  const worldOrigin = new THREE.Vector3().fromArray(layout.origin);
  const columns = new THREE.Vector3().fromArray(layout.columns);
  const rows = new THREE.Vector3().fromArray(layout.rows);
  const actorOffset = new THREE.Vector3().fromArray(layout.actorOffset ?? [0, 0, 0]);
  const shadowOffset = new THREE.Vector3().fromArray(layout.actorShadow.offset);

  function render(time) {
    const elapsed = time - run.spawn;
    const position = elapsed >= 0 ? routeAt(run.path, elapsed * run.moveSpeed) : null;
    avatar.visible = shadow.visible = Boolean(position);
    if (position) {
      avatar.position.copy(worldOrigin).addScaledVector(columns, position[0])
        .addScaledVector(rows, position[1]);
      shadow.position.copy(avatar.position).add(shadowOffset);
      avatar.position.add(actorOffset);
      enemy.sprite.scale.x = resolution * position[2];
      const track = enemy.sprite.state.getCurrent(0);
      track.trackTime = elapsed * run.clipSpeed;
      enemy.sprite.update(0);
      enemy.surface.renderer.render(enemy.surface.stage);
      texture.needsUpdate = true;
    }
    renderer.render(scene, camera);
  }

  if (capture) {
    const count = Number(capture);
    const start = Number(query.get('start') ?? 0);
    const fps = Number(query.get('fps') ?? 30);
    for (let i = 0; i < count; i++) {
      render(start + i / fps);
      const blob = await new Promise(resolve => renderer.domElement.toBlob(resolve, 'image/png'));
      await post('/frame/' + i, blob);
    }
    await post('/done', JSON.stringify({
      scene: layout.asset,
      clip: run.clip,
      version: enemy.version,
      camera: layout.camera,
      spawn: run.spawn,
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
  slider.max = String(run.spawn + run.path.reduce((distance, point, i, path) => {
    if (!i) return distance;
    return distance + Math.hypot(point[0]-path[i-1][0], point[1]-path[i-1][1]);
  }, 0) / run.moveSpeed + 1);
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
