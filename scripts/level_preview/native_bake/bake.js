const cellSize = 256;
const anchor = [128, 192];
const padding = 5;

async function send(path, body) {
  const response = await fetch(path, {method: 'POST', body});
  if (!response.ok) throw new Error(`Could not write ${path}: ${response.status}`);
}

async function bake() {
  const response = await fetch('config');
  const {actors, actorScale} = await response.json();
  const loader = new PIXI.Loader();
  const assetNames = new Map();
  const actorNames = new Map();
  for (const [name, config] of Object.entries(actors)) {
    const key = `${config.skeletonScale}:${config.skeleton}`;
    if (!assetNames.has(key)) {
      const resource = `actor-${assetNames.size}`;
      const url = config.skeleton.split('/').map(encodeURIComponent).join('/');
      loader.add(resource, url, {metadata: {spineSkeletonScale: config.skeletonScale}});
      assetNames.set(key, resource);
    }
    actorNames.set(name, assetNames.get(key));
  }
  const resources = await new Promise((resolve, reject) => {
    loader.onError.add((error, _, resource) => reject(new Error(`${resource?.url}: ${error.message}`)));
    loader.load((_, loaded) => resolve(loaded));
  });
  const renderer = new PIXI.Renderer({width: cellSize, height: cellSize, backgroundAlpha: 0,
    antialias: true, preserveDrawingBuffer: true});
  const index = {};
  for (const [name, config] of Object.entries(actors)) {
    const data = resources[actorNames.get(name)]?.spineData;
    if (!data) throw new Error(`Missing original Spine data for ${name}`);
    const sprite = new PIXI.spine.Spine(data);
    sprite.autoUpdate = false;
    sprite.position.set(...anchor);
    if (config.initialSkin) sprite.skeleton.setSkinByName(config.initialSkin);
    const clips = [clip('move', config.clip, config.clipSpeed, config.clipLoop)];
    if (config.idleClip) clips.push(clip('idle', config.idleClip, config.idleClipSpeed, config.idleClipLoop));
    const attack = config.periodicAttack;
    if (attack?.phases?.length) {
      attack.phases.forEach((phase, index) => {
        clips.push(clip(`attack-${index}`, phase.clip, phase.clipSpeed, phase.loop ?? false));
      });
    } else if (attack) {
      clips.push(clip('attack', attack.clip, attack.clipSpeed, attack.loop ?? false));
    }

    function clip(mode, animation, speed, loop) {
      speed ??= 1;
      loop ??= true;
      const source = data.findAnimation(animation);
      if (!source || !Number.isFinite(speed) || speed <= 0) {
        throw new Error(`${name}: 原版 Spine 动作不可用 ${animation}`);
      }
      const duration = source.duration / speed || 1 / 24;
      // A finite action must hold its actual final pose after the clip ends.
      const frames = Math.max(1, Math.min(120, Math.ceil(duration * 24) + (loop ? 0 : 1)));
      const intervals = loop ? frames : Math.max(1, frames - 1);
      return {mode, animation, speed, loop, duration, frames, fps: intervals / duration};
    }

    function applyClip({animation, loop, speed, fps, frames}, each) {
      sprite.state.clearTrack(0);
      const track = sprite.state.setAnimation(0, animation, loop);
      for (let i = 0; i < frames; i++) {
        sprite.skeleton.setToSetupPose();
        track.trackTime = (i / fps) * speed;
        sprite.update(0);
        each(i);
      }
    }

    let pixelsPerUnit = 100;
    for (const spec of clips) {
      applyClip(spec, () => {
        const bounds = sprite.getLocalBounds();
        const limits = [[anchor[0] - padding, -bounds.left], [cellSize - anchor[0] - padding, bounds.right],
          [anchor[1] - padding, -bounds.top], [cellSize - anchor[1] - padding, bounds.bottom]];
        for (const [pixels, distance] of limits) {
          if (distance > 0) pixelsPerUnit = Math.min(pixelsPerUnit, pixels / distance);
        }
      });
    }
    // Reserve room around deforming meshes whose cached bounds can lag one pose.
    pixelsPerUnit *= 0.90;
    sprite.scale.set(pixelsPerUnit);
    const size = cellSize / pixelsPerUnit * (config.actorPlane ? 1 : config.graphicScale * actorScale);
    const actor = {size: [size, size], anchor, offset: config.actorOffset, spineVersion: data.version};
    for (const spec of clips) {
      const {mode, animation, duration, fps, frames, loop} = spec;
      const columns = Math.min(8, frames);
      const atlas = document.createElement('canvas');
      atlas.width = columns * cellSize;
      atlas.height = Math.ceil(frames / columns) * cellSize;
      const context = atlas.getContext('2d');
      applyClip(spec, i => {
        renderer.render(sprite);
        context.drawImage(renderer.view, (i % columns) * cellSize, Math.floor(i / columns) * cellSize);
      });
      const file = `${name}-${mode}.png`;
      const png = await new Promise(resolve => atlas.toBlob(resolve, 'image/png'));
      if (!png) throw new Error(`Could not encode ${file}`);
      await send(`atlas/${encodeURIComponent(file)}`, png);
      actor[mode] = {file, frameWidth: cellSize, frameHeight: cellSize, columns, frames, fps, duration, loop, animation};
    }
    index[name] = actor;
  }
  await send('done', JSON.stringify(index));
}

bake().catch(error => send('error', error.message ?? String(error)));
