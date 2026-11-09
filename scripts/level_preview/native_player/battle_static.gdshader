shader_type spatial;

#ifdef BATTLE_ALPHA_BLEND
render_mode unshaded, fog_disabled, cull_disabled;
#else
render_mode unshaded, fog_disabled;
#endif

uniform sampler2D albedo_tex : source_color, hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D lightmap_tex : hint_default_white, filter_linear, repeat_disable;
uniform sampler2D shadowmask_tex : hint_default_white, filter_linear, repeat_disable;
uniform sampler2D metallic_gloss_tex : hint_default_white, filter_linear, repeat_disable;
uniform sampler2D emission_tex : source_color, hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap, repeat_enable;

uniform bool has_shadowmask = false;
uniform bool has_metallic_gloss = false;
uniform bool has_emission_map = false;
uniform bool has_normal_map = false;
uniform bool metallic_split = false;
uniform float alpha_cutoff = 0.0;
uniform float normal_scale = 1.0;
uniform float lightmap_multiplier = 5.0;
uniform vec4 occlusion_weights = vec4(1.0, 0.0, 0.0, 0.0);
uniform vec3 light_dir_world = vec3(0.0, 0.0, 1.0);
uniform vec3 main_light = vec3(1.0);
uniform vec3 material_color = vec3(1.0);
uniform vec3 emission_color = vec3(0.0);
uniform float metallic = 0.0;
uniform float metallic_secondary = 0.0;
uniform float smoothness = 0.0;
uniform float smoothness_secondary = 0.0;
uniform vec3 blend_color = vec3(1.0);
uniform vec2 blend_range = vec2(0.0, 1.0);
uniform float blend_strength = 0.0;

vec3 to_gamma(vec3 color) {
	vec3 value = max(color, vec3(0.0));
	return mix(value * 12.92, 1.055 * pow(value, vec3(1.0 / 2.4)) - 0.055,
		step(vec3(0.0031308), value));
}

vec3 to_linear(vec3 color) {
	vec3 value = max(color, vec3(0.0));
	return mix(value / 12.92, pow((value + 0.055) / 1.055, vec3(2.4)),
		step(vec3(0.04045), value));
}

void fragment() {
	vec4 base = texture(albedo_tex, UV);
	if (base.a < alpha_cutoff) {
		discard;
	}
	vec3 albedo_gamma = OUTPUT_IS_SRGB ? base.rgb : to_gamma(base.rgb);
	float weight = blend_strength > 0.01 ? smoothstep(blend_range.x, blend_range.y, COLOR.r) * blend_strength : 0.0;
	albedo_gamma = mix(albedo_gamma, blend_color, weight) * material_color;

	float diffuse_metal = metallic;
	float specular_metal = mix(metallic, metallic_secondary, weight);
	float gloss = mix(smoothness, smoothness_secondary, weight);
	if (has_metallic_gloss) {
		vec4 packed_gloss = texture(metallic_gloss_tex, UV);
		diffuse_metal = packed_gloss.r;
		specular_metal = metallic_split ? mix(packed_gloss.r, packed_gloss.g, weight) : packed_gloss.r;
		gloss *= metallic_split ? mix(packed_gloss.a, packed_gloss.b, weight) : packed_gloss.a;
	}

	vec3 surface_normal = normalize(NORMAL);
	if (has_normal_map) {
		vec2 xy = texture(normal_tex, UV).rg * 2.0 - 1.0;
		vec3 mapped = vec3(xy * normal_scale, sqrt(max(1.0 - dot(xy, xy), 0.0)));
		mat3 tangent_basis = mat3(normalize(TANGENT), normalize(BINORMAL), surface_normal);
		surface_normal = normalize(mix(normalize(tangent_basis * mapped), surface_normal, weight));
	}

	// The game adds lighting in gamma space. Keep atlas channels raw and convert
	// only the final result to the color space expected by the Godot renderer.
	vec3 diffuse = 0.779084 * (1.0 - diffuse_metal) * albedo_gamma;
	vec3 specular = mix(vec3(0.220916), albedo_gamma, specular_metal);
	vec4 packed_light = texture(lightmap_tex, UV2);
	vec3 baked = packed_light.rgb * (packed_light.a * lightmap_multiplier);
	float occlusion = has_shadowmask ? clamp(dot(texture(shadowmask_tex, UV2), occlusion_weights), 0.0, 1.0) : 1.0;
	vec3 to_light = normalize((VIEW_MATRIX * vec4(light_dir_world, 0.0)).xyz);
	vec3 half_dir = normalize(normalize(VIEW) + to_light);
	float no_l = max(dot(surface_normal, to_light), 0.0);
	float no_h = clamp(dot(surface_normal, half_dir), 0.0, 1.0);
	float lo_h = clamp(dot(to_light, half_dir), 0.0, 1.0);
	float roughness = 1.0 - gloss;
	float r2 = roughness * roughness;
	float distribution = r2 / (max(lo_h, 0.32) * (1.5 + r2) * ((r2 * r2 - 1.0) * no_h * no_h + 1.00001));
	vec3 direct = (diffuse + distribution * specular) * no_l * main_light * occlusion;

	vec3 emitted = emission_color;
	if (has_emission_map) {
		vec3 sample_color = texture(emission_tex, UV).rgb;
		emitted *= OUTPUT_IS_SRGB ? sample_color : to_gamma(sample_color);
	}
	vec3 outgoing = max(diffuse * baked + direct + emitted, vec3(0.0));
	ALBEDO = OUTPUT_IS_SRGB ? outgoing : to_linear(outgoing);
#ifdef BATTLE_ALPHA_BLEND
	ALPHA = base.a;
#endif
}
