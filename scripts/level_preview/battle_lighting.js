import * as THREE from 'three';

const STANDARD = 'Torappu/Scene/StandardRealtimeShadow';
const VERTEX_BLEND = '_HG_VERTEX_COLOR_BLEND_ON';
const METALLIC_GLOSS = '_METALLICGLOSSMAP';
const DEFAULT_LIGHTMAP_MULTIPLIER = 5;

async function loadRawTexture(loader, url, channel = 0) {
  const texture = await loader.loadAsync(url);
  texture.flipY = false;
  texture.premultiplyAlpha = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.channel = channel;
  texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = false;
  texture.needsUpdate = true;
  return texture;
}

const uniformsGLSL = `
uniform sampler2D battleStaticMask;
uniform float battleLightmapMultiplier;
uniform vec4 battleOcclusion;
uniform vec3 battleRayDirection;
uniform vec3 battleMainLight;
uniform vec3 battleColor;
uniform vec3 battleBlendColor;
uniform vec2 battleBlendRange;
uniform float battleBlendStrength;
uniform vec2 battleMetallic;
uniform vec2 battleSmoothness;
uniform bool battleMetallicSplit;
#ifdef BATTLE_METALLIC_GLOSS
uniform sampler2D battleMetallicGloss;
#endif
#ifdef BATTLE_VERTEX_BLEND
varying float battleVertexWeight;
#endif
`;

// Gamma-space forward pass reconstructed from the scene shader's SM4 variant.
// Lighting sums here before conversion to Three's output pipeline.
const lightingGLSL = `
vec3 battleAlbedo = vec3(1.0);
#ifdef USE_MAP
  battleAlbedo = sRGBTransferOETF(vec4(sampledDiffuseColor.rgb, 1.0)).rgb;
#endif
battleAlbedo = mix(battleAlbedo, battleBlendColor, battleWeight) * battleColor;

float battleSpecularMetal = mix(battleMetallic.x, battleMetallic.y, battleWeight);
float battleDiffuseMetal = battleMetallic.x;
float battleGloss = mix(battleSmoothness.x, battleSmoothness.y, battleWeight);
#ifdef BATTLE_METALLIC_GLOSS
  vec4 mg = texture2D(battleMetallicGloss, vMapUv);
  battleDiffuseMetal = mg.r;
  battleSpecularMetal = battleMetallicSplit ? mix(mg.r, mg.g, battleWeight) : mg.r;
  battleGloss *= battleMetallicSplit ? mix(mg.a, mg.b, battleWeight) : mg.a;
#endif

vec3 gameDiffuse = (0.779084 * (1.0 - battleDiffuseMetal)) * battleAlbedo;
vec3 gameSpecular = mix(vec3(0.220916), battleAlbedo, battleSpecularMetal);
vec4 packedBaked = texture2D(lightMap, vLightMapUv);
vec3 gameBaked = packedBaked.rgb * (packedBaked.a * battleLightmapMultiplier);
float gameOcclusion = clamp(dot(texture2D(battleStaticMask, vLightMapUv), battleOcclusion), 0.0, 1.0);
#ifdef BATTLE_DYNAMIC_SHADOW
  gameOcclusion = min(gameOcclusion, getShadowMask());
#endif

vec3 toLight = normalize((viewMatrix * vec4(-battleRayDirection, 0.0)).xyz);
vec3 halfDir = normalize(normalize(vViewPosition) + toLight);
float gameNoL = max(dot(normal, toLight), 0.0);
float gameNoH = clamp(dot(normal, halfDir), 0.0, 1.0);
float gameLoH = clamp(dot(toLight, halfDir), 0.0, 1.0);
float gameRoughness = 1.0 - battleGloss;
float gameR2 = gameRoughness * gameRoughness;
float gameD = gameR2 / (max(gameLoH, 0.32) * (1.5 + gameR2)
  * ((gameR2 * gameR2 - 1.0) * gameNoH * gameNoH + 1.00001));
vec3 gameDirect = (gameDiffuse + gameD * gameSpecular) * gameNoL * battleMainLight * gameOcclusion;
vec3 gameOutgoing = gameDiffuse * gameBaked + gameDirect;
vec3 outgoingLight = sRGBTransferEOTF(vec4(max(gameOutgoing, vec3(0.0)), 1.0)).rgb;
`;

function applyStandard(material, lighting, useBlend) {
  const data = material.userData;
  const colors = data.unityColors ?? {};
  const floats = data.unityFloats ?? {};
  const metalName = data.unityTextures?._MetallicGlossMap?.name;
  const metalMap = data.unityKeywords?.includes(METALLIC_GLOSS)
    ? lighting.metallicGlossMaps[metalName] : null;
  const vec3 = (value, fallback) => new THREE.Vector3().fromArray(value ?? fallback);
  const isSplit = Boolean(floats._MetallicGlossSplit);

  material.vertexColors = false;
  material.lightMap = lighting.lightmap;
  material.toneMapped = false;
  material.customProgramCacheKey = () => `torappu-forward:${useBlend}:${Boolean(metalMap)}:${lighting.dynamicShadow}`;
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, {
      battleStaticMask: { value: lighting.shadowMask },
      battleLightmapMultiplier: { value: lighting.lightmapMultiplier },
      battleOcclusion: { value: lighting.occlusion },
      battleRayDirection: { value: lighting.rayDirection },
      battleMainLight: { value: lighting.mainLight },
      battleColor: { value: vec3(colors._Color, [1, 1, 1]) },
      battleBlendColor: { value: vec3(colors._BlendColor, [1, 1, 1]) },
      battleBlendRange: { value: new THREE.Vector2().fromArray(colors._BlendRangeCtrl ?? [0, 1]) },
      battleBlendStrength: { value: floats._BlendStrength ?? 0 },
      battleMetallic: { value: new THREE.Vector2(floats._Metallic ?? 0, floats._Metallic2 ?? 0) },
      battleSmoothness: { value: metalMap
        ? new THREE.Vector2(floats._GlossMapScale ?? 1, floats._GlossMapScale2 ?? 1)
        : new THREE.Vector2(floats._Glossiness ?? 0, floats._Glossiness2 ?? 0) },
      battleMetallicSplit: { value: isSplit },
      ...(metalMap ? { battleMetallicGloss: { value: metalMap } } : {}),
    });
    const blendDefinition = useBlend ? '#define BATTLE_VERTEX_BLEND\n' : '';
    if (useBlend) {
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nattribute vec4 color;\nvarying float battleVertexWeight;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nbattleVertexWeight = color.r;');
    }
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', [
        '#include <common>', blendDefinition,
        metalMap ? '#define BATTLE_METALLIC_GLOSS' : '',
        lighting.dynamicShadow ? '#define BATTLE_DYNAMIC_SHADOW' : '',
        uniformsGLSL,
      ].join('\n'))
      .replace('#include <shadowmap_pars_fragment>',
        '#include <shadowmap_pars_fragment>\n#include <shadowmask_pars_fragment>')
      .replace('#include <normal_fragment_maps>', `
#include <normal_fragment_maps>
float battleWeight = 0.0;
#ifdef BATTLE_VERTEX_BLEND
  if (battleBlendStrength > 0.01) {
    battleWeight = smoothstep(battleBlendRange.x, battleBlendRange.y, battleVertexWeight) * battleBlendStrength;
    normal = mix(normal, nonPerturbedNormal, battleWeight);
  }
#endif
`)
      .replace('vec3 outgoingLight = totalDiffuse + totalSpecular + totalEmissiveRadiance;', lightingGLSL);
  };
  material.needsUpdate = true;
  return material;
}

export async function loadBattleLighting(layout) {
  const config = layout.battleLighting ?? {};
  const loader = new THREE.TextureLoader();
  const shadowMaskUrl = config.shadowMask ?? layout.lightMap.replace('_light.png', '_shadowmask.png');
  const mapEntries = Object.entries(config.metallicGlossMaps ?? {});
  const [lightmap, shadowMask, ...metallicGlossMaps] = await Promise.all([
    loadRawTexture(loader, layout.lightMap, 1),
    loadRawTexture(loader, shadowMaskUrl, 1),
    ...mapEntries.map(([, url]) => loadRawTexture(loader, url)),
  ]);
  return {
    lightmap, shadowMask,
    metallicGlossMaps: Object.fromEntries(mapEntries.map(([name], index) => [name, metallicGlossMaps[index]])),
    lightmapMultiplier: config.lightmapMultiplier ?? DEFAULT_LIGHTMAP_MULTIPLIER,
    occlusion: new THREE.Vector4().fromArray(config.occlusion ?? [1, 0, 0, 0]),
    rayDirection: new THREE.Vector3().fromArray(layout.sun.rayDirection),
    mainLight: new THREE.Vector3().fromArray(layout.sun.color).multiplyScalar(layout.sun.intensity),
    dynamicShadow: config.dynamicShadow ?? false,
  };
}

export function applyBattleLighting(scene, lighting) {
  const cache = new Map();
  const stats = { nativeMeshes: 0, metallicMaps: 0, vertexBlendMeshes: 0 };
  scene.traverse(node => {
    if (!node.isMesh) return;
    const original = node.material;
    if (Array.isArray(original)) return;
    const data = original.userData;
    if (data.unityShader !== STANDARD || !node.geometry.attributes.uv1) return;
    const useBlend = Boolean(node.geometry.attributes.color && data.unityKeywords?.includes(VERTEX_BLEND));
    const key = `${original.uuid}:${useBlend}`;
    if (!cache.has(key)) cache.set(key, applyStandard(original.clone(), lighting, useBlend));
    node.material = cache.get(key);
    node.receiveShadow = lighting.dynamicShadow && !node.material.transparent;
    stats.nativeMeshes += 1;
    if (useBlend) stats.vertexBlendMeshes += 1;
    if (lighting.metallicGlossMaps[data.unityTextures?._MetallicGlossMap?.name]) stats.metallicMaps += 1;
  });
  return stats;
}
