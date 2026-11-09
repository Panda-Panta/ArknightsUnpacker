extends Node

const BUFFER := Vector2i(1920, 1080)
const SPEED := 2.0
const UP := Vector3(0.0, 0.0, 1.0)

var options := {}
var asset_root: String
var actor_root: String
var layout: Dictionary
var fixture: Dictionary
var world := Node3D.new()
var viewport := SubViewport.new()
var textures := {}
var actors := {}
var timeline: Array[Dictionary] = []
var timed_props: Array[Dictionary] = []
var elapsed := 0.0
var battle_time := 0.0
var playing := true
var frame_count := 0
var peak_actors := 0
var active_actors := 0
var last_tick := 0.0
var max_frame_gap := 0.0
var last_draw := 0
var shaded_surfaces := 0
var present: TextureRect


func _ready() -> void:
	set_process(false)
	for argument in OS.get_cmdline_user_args():
		var parts := argument.split("=", true, 1)
		options[parts[0]] = parts[1] if parts.size() == 2 else true
	var assets: Variant = options.get("--assets")
	var atlases: Variant = options.get("--actors")
	if not assets is String or not atlases is String or not assets.is_absolute_path() or not atlases.is_absolute_path():
		fail("Native replay requires absolute --assets and --actors paths")
		return
	asset_root = assets
	actor_root = atlases
	layout = read_object(asset_root.path_join("scene-layout.json"))
	fixture = read_object(asset_root.path_join("fixture.json"))
	if layout.is_empty() or fixture.is_empty():
		fail("Original scene layout or replay fixture unavailable")
		return
	actors = read_object(actor_root.path_join("index.json"))
	if actors.is_empty() and not fixture.events.is_empty():
		fail("Original actor atlas index unavailable")
		return
	Engine.max_fps = 120
	viewport.size = BUFFER
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.msaa_3d = Viewport.MSAA_4X
	add_child(viewport)
	viewport.add_child(world)
	setup_camera()
	var map := load_model(layout.asset, true)
	if map == null:
		return
	world.add_child(map)
	for prop: Dictionary in layout.get("props", []):
		var model := load_model(prop.asset, false)
		if model == null:
			return
		for index in range(prop.positions.size()):
			var instance: Node3D = model if index == 0 else model.duplicate()
			instance.position = v3(prop.positions[index])
			world.add_child(instance)
			var times: Array = prop.get("activationTimes", [])
			if index < times.size() and times[index] != null:
				timed_props.append({"node": instance, "time": float(times[index])})
	build_timeline()
	battle_time = clampf(float(options.get("--start", "0")), 0.0, float(fixture.duration))
	update_scene()
	present = TextureRect.new()
	present.texture = viewport.get_texture()
	present.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	present.stretch_mode = TextureRect.STRETCH_SCALE
	present.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(present)
	present.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	RenderingServer.frame_post_draw.connect(on_frame_drawn)
	set_process(true)
	print("PROBE_READY ", JSON.stringify(status()))


func fail(message: String) -> void:
	push_error(message)
	get_tree().quit(1)


func read_object(path: String) -> Dictionary:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Dictionary else {}


func v3(values: Array) -> Vector3:
	return Vector3(float(values[0]), float(values[1]), float(values[2]))


func texture_at(path: String) -> Texture2D:
	if not textures.has(path):
		var image := Image.load_from_file(path)
		if image == null or image.is_empty():
			fail("Cannot load original texture " + path)
			return null
		textures[path] = ImageTexture.create_from_image(image)
	return textures[path]


func setup_camera() -> void:
	var camera := Camera3D.new()
	camera.fov = float(layout.camera.fov)
	camera.near = 0.3
	camera.far = 1000.0
	world.add_child(camera)
	camera.position = v3(layout.camera.position)
	camera.look_at(v3(layout.camera.target), UP)
	camera.make_current()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(layout.get("background", "#201b18"))
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color.WHITE
	env.ambient_light_energy = float(layout.get("ambient", 0.3))
	var backdrop := WorldEnvironment.new()
	backdrop.environment = env
	world.add_child(backdrop)
	var sunlight := DirectionalLight3D.new()
	sunlight.light_color = Color(float(layout.sun.color[0]), float(layout.sun.color[1]), float(layout.sun.color[2]))
	sunlight.light_energy = float(layout.sun.intensity)
	world.add_child(sunlight)
	sunlight.position = -v3(layout.sun.rayDirection) * 5.0
	sunlight.look_at(Vector3.ZERO, UP)


func load_model(relative: String, battle_map: bool) -> Node3D:
	var source := asset_root.path_join(relative)
	var importer := GLTFDocument.new()
	var state := GLTFState.new()
	var error := importer.append_from_file(source, state)
	if error != OK:
		fail("Cannot import %s, error %s" % [source, error])
		return null
	var result := importer.generate_scene(state) as Node3D
	if result == null:
		fail("No mesh scene generated for " + source)
		return null
	if battle_map and layout.has("lightMap"):
		apply_baked_materials(result, state.json)
	return result


func apply_baked_materials(root: Node3D, raw: Dictionary) -> void:
	var shader := load("res://battle_static.gdshader") as Shader
	if shader == null:
		fail("Original battle lighting shader unavailable")
		return
	var blend_shader := Shader.new()
	blend_shader.code = "#define BATTLE_ALPHA_BLEND\n" + shader.code
	var source_materials := {}
	for material: Dictionary in raw.get("materials", []):
		source_materials[material.get("name", "")] = material
	var lightmap := texture_at(asset_root.path_join(layout.lightMap))
	var lighting: Dictionary = layout.get("battleLighting", {})
	var shadowmask: Texture2D
	if lighting.get("shadowMask"):
		shadowmask = texture_at(asset_root.path_join(lighting.shadowMask))
	var replacements := {}
	for mesh: MeshInstance3D in root.find_children("*", "MeshInstance3D", true, false):
		for surface in range(mesh.mesh.get_surface_count()):
			var original := mesh.get_active_material(surface) as BaseMaterial3D
			if original == null or mesh.mesh.surface_get_arrays(surface)[Mesh.ARRAY_TEX_UV2] == null:
				continue
			var descriptor: Dictionary = source_materials.get(original.resource_name, {})
			var info: Dictionary = descriptor.get("extras", {})
			if info.get("unityShader") != "Torappu/Scene/StandardRealtimeShadow":
				continue
			if not replacements.has(original.resource_name):
				var material := ShaderMaterial.new()
				material.shader = blend_shader if descriptor.get("alphaMode") == "BLEND" else shader
				if descriptor.get("alphaMode") == "MASK":
					material.set_shader_parameter("alpha_cutoff", float(descriptor.get("alphaCutoff", 0.5)))
				material.set_shader_parameter("albedo_tex", original.albedo_texture)
				material.set_shader_parameter("lightmap_tex", lightmap)
				material.set_shader_parameter("lightmap_multiplier", float(lighting.get("lightmapMultiplier", 5.0)))
				material.set_shader_parameter("light_dir_world", -v3(layout.sun.rayDirection))
				material.set_shader_parameter("main_light", v3(layout.sun.color) * float(layout.sun.intensity))
				if shadowmask != null:
					material.set_shader_parameter("shadowmask_tex", shadowmask)
					material.set_shader_parameter("has_shadowmask", true)
				var floats: Dictionary = info.get("unityFloats", {})
				var colors: Dictionary = info.get("unityColors", {})
				var keywords: Array = info.get("unityKeywords", [])
				var unity_textures: Dictionary = info.get("unityTextures", {})
				var gloss_asset: String = unity_textures.get("_MetallicGlossMap", {}).get("lightingAsset", "")
				var has_gloss := "_METALLICGLOSSMAP" in keywords and not gloss_asset.is_empty()
				if has_gloss:
					material.set_shader_parameter("metallic_gloss_tex", texture_at(asset_root.path_join(gloss_asset)))
				material.set_shader_parameter("has_metallic_gloss", has_gloss)
				material.set_shader_parameter("material_color", v3(colors.get("_Color", [1.0, 1.0, 1.0])))
				material.set_shader_parameter("metallic", float(floats.get("_Metallic", 0.0)))
				material.set_shader_parameter("smoothness", float(floats.get("_GlossMapScale" if has_gloss else "_Glossiness", 0.0)))
				if "_EMISSION" in keywords and original.emission_texture != null:
					material.set_shader_parameter("emission_tex", original.emission_texture)
					material.set_shader_parameter("has_emission_map", true)
					material.set_shader_parameter("emission_color", v3(colors.get("_EmissionColor", [0.0, 0.0, 0.0])))
				if original.normal_texture != null:
					material.set_shader_parameter("normal_tex", original.normal_texture)
					material.set_shader_parameter("has_normal_map", true)
				replacements[original.resource_name] = material
			mesh.set_surface_override_material(surface, replacements[original.resource_name])
			shaded_surfaces += 1


func build_timeline() -> void:
	for definition: Dictionary in actors.values():
		for kind in ["move", "idle"]:
			if definition.has(kind):
				texture_at(actor_root.path_join(definition[kind].file))
	for item: Dictionary in fixture.events:
		if not actors.has(item.enemyId):
			continue
		# JSON numbers are floats. Route step lookups use integer indices.
		item.jumps = PackedInt32Array(item.jumps)
		var definition: Dictionary = actors[item.enemyId]
		var sprite := Sprite3D.new()
		sprite.rotation.x = PI / 6.0
		sprite.visible = false
		sprite.shaded = false
		sprite.alpha_cut = SpriteBase3D.ALPHA_CUT_DISCARD
		sprite.alpha_scissor_threshold = 0.02
		world.add_child(sprite)
		var config: Dictionary = fixture.actors[item.enemyId]
		var shadow := build_shadow(config.get("shadow", {}))
		timeline.append({"item": item, "definition": definition, "sprite": sprite, "shadow": shadow, "config": config})


func build_shadow(config: Dictionary) -> Sprite3D:
	if not config.has("vertices"):
		return null
	var sprite := Sprite3D.new()
	sprite.texture = texture_at(asset_root.path_join(config.texture))
	if sprite.texture == null:
		return null
	var a := v3(config.vertices[0])
	var b := v3(config.vertices[3])
	var span := b - a
	sprite.pixel_size = 1.0
	sprite.scale = Vector3(absf(span.x) / sprite.texture.get_width(), absf(span.y) / sprite.texture.get_height(), 1.0)
	sprite.modulate.a = float(config.get("opacity", 1.0))
	sprite.set_meta("base_offset", (a + b) * 0.5 + Vector3(0.0, 0.0, 0.008))
	sprite.visible = false
	world.add_child(sprite)
	return sprite


func route_pose(item: Dictionary, age: float) -> Dictionary:
	var path: Array = item.path
	var direction := -1.0
	var moving := 0.0
	for i in range(path.size()):
		var point := Vector2(float(path[i][0]), float(path[i][1]))
		var wait := float(item.waits.get(str(i), 0.0))
		if age < wait:
			return {"point": point, "direction": direction, "phase": age, "idle": true}
		age -= wait
		var hidden := float(item.hiddenWaits.get(str(i), 0.0))
		if age < hidden:
			return {}
		age -= hidden
		if i + 1 == path.size():
			break
		if i in item.jumps:
			continue
		var next := Vector2(float(path[i + 1][0]), float(path[i + 1][1]))
		var step := point.distance_to(next) / float(item.moveSpeed)
		if next.x != point.x:
			direction = signf(next.x - point.x)
		if age < step:
			return {"point": point.lerp(next, age / step), "direction": direction, "phase": moving + age, "idle": false}
		age -= step
		moving += step
	return {}


func update_scene() -> void:
	for prop in timed_props:
		prop.node.visible = battle_time >= prop.time
	var origin := v3(layout.origin)
	var columns := v3(layout.columns)
	var rows := v3(layout.rows)
	active_actors = 0
	for entry in timeline:
		var item: Dictionary = entry.item
		var sprite: Sprite3D = entry.sprite
		var shadow: Sprite3D = entry.shadow
		var visible_now: bool = battle_time >= float(item.time) and battle_time < float(item.get("exitTime", fixture.duration))
		var pose := route_pose(item, battle_time - float(item.time)) if visible_now else {}
		sprite.visible = not pose.is_empty()
		if shadow != null:
			shadow.visible = sprite.visible
		if not sprite.visible:
			continue
		var definition: Dictionary = entry.definition
		var clip: Dictionary = definition.get("idle", definition.move) if pose.idle else definition.move
		var frame := posmod(int(floor(float(pose.phase) * float(clip.fps))), int(clip.frames))
		var atlas := texture_at(actor_root.path_join(clip.file))
		var width := int(clip.frameWidth)
		var height := int(clip.frameHeight)
		var columns_in_atlas := int(clip.columns)
		if sprite.texture != atlas:
			sprite.texture = atlas
			sprite.hframes = columns_in_atlas
			sprite.vframes = atlas.get_height() / height
		sprite.frame = frame
		var pixel_size := float(definition.size[0]) / width
		sprite.pixel_size = pixel_size
		sprite.flip_h = pose.direction < 0.0
		var anchor: Array = definition.get("anchor", [width / 2.0, height * 0.75])
		var base: Vector3 = origin + columns * pose.point.x + rows * pose.point.y
		sprite.position = base + v3(definition.get("offset", entry.config.get("actorOffset", [0.0, 0.0, 0.0])))
		sprite.position += sprite.basis.y * (float(anchor[1]) - height / 2.0) * pixel_size
		if shadow != null:
			shadow.position = base + shadow.get_meta("base_offset")
		active_actors += 1
	peak_actors = maxi(peak_actors, active_actors)


func _process(delta: float) -> void:
	elapsed += delta
	if playing:
		battle_time = minf(battle_time + delta * SPEED, float(fixture.duration))
		update_scene()
	if elapsed - last_tick >= 1.0:
		last_tick = elapsed
		print("PROBE_TICK ", JSON.stringify(status()))


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_SPACE:
			playing = not playing
		elif event.keycode == KEY_F11 and not options.has("--embedded"):
			get_window().mode = Window.MODE_WINDOWED if get_window().mode == Window.MODE_FULLSCREEN else Window.MODE_FULLSCREEN
		elif event.keycode == KEY_ESCAPE:
			if options.has("--embedded"):
				print("PROBE_ESCAPE")
			elif get_window().mode == Window.MODE_FULLSCREEN:
				get_window().mode = Window.MODE_WINDOWED


func on_frame_drawn() -> void:
	var now := Time.get_ticks_usec()
	if last_draw > 0:
		max_frame_gap = maxf(max_frame_gap, (now - last_draw) / 1000.0)
	last_draw = now
	frame_count += 1


func status() -> Dictionary:
	var size := get_window().size
	return {"pid": OS.get_process_id(), "elapsed": elapsed, "battle": battle_time,
		"drawn": frame_count, "fps": Engine.get_frames_per_second(), "maxGapMs": max_frame_gap,
		"buffer": [BUFFER.x, BUFFER.y], "window": [size.x, size.y],
		"actors": active_actors, "peakActors": peak_actors, "sourceSpawns": fixture.events.size(),
		"sampleSpawns": timeline.size(), "shadedSurfaces": shaded_surfaces,
		"seed": fixture.seed, "stage": fixture.levelId}
