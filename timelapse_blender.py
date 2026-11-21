bl_info = {
    "name": "Model Timelapse Frame Renderer",
    "author": "Timelapse viewer",
    "version": (0, 4, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Timelapse",
    "description": "Render numbered GLB stages from adjustable camera angles",
    "category": "Render",
}

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import bpy
from mathutils import Vector


MODEL_PREFIX_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
RENDER_INFO = "timelapse-render.json"


def stage_files(directory, model_prefix="chLavaMon"):
    if not MODEL_PREFIX_PATTERN.fullmatch(model_prefix):
        raise ValueError("Model prefix must contain 1-64 letters, numbers, underscores, or hyphens.")
    pattern = re.compile(rf"{re.escape(model_prefix)}_V(\d{{4,}})\.glb", re.IGNORECASE)
    files = []
    for path in Path(directory).iterdir():
        if path.suffix.lower() != ".glb":
            continue
        match = pattern.fullmatch(path.name)
        if not match:
            raise ValueError(f"GLB must be named {model_prefix}_V0001.glb, {model_prefix}_V0002.glb, etc.: {path.name}")
        files.append((int(match.group(1)), path))
    files.sort()
    if not files or [number for number, _ in files] != list(range(1, len(files) + 1)):
        raise ValueError(f"GLB stages must be numbered consecutively from {model_prefix}_V0001.glb.")
    return [path for _, path in files]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_stage(path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    bpy.context.view_layer.update()


def model_bounds():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        points.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    if not points:
        raise ValueError("A stage has no visible mesh objects.")
    return points


def elevation_angles(count, minimum, maximum):
    if not 1 <= count <= 99:
        raise ValueError("Vertical views must be between 1 and 99.")
    if not all(math.isfinite(value) and -89 <= value <= 89 for value in (minimum, maximum)):
        raise ValueError("Elevations must be between -89 and 89 degrees.")
    if minimum > maximum or (count > 1 and minimum == maximum):
        raise ValueError("Minimum elevation must be lower than maximum for multiple views.")
    if count == 1:
        return [minimum]
    return [minimum + (maximum - minimum) * i / (count - 1) for i in range(count)]


def camera_direction(yaw_index, yaw_count, pitch_degrees):
    pitch = math.radians(pitch_degrees)
    yaw = math.radians(yaw_index * 360 / yaw_count)
    return Vector((math.sin(yaw) * math.cos(pitch),
                   -math.cos(yaw) * math.cos(pitch),
                   math.sin(pitch)))


def fitted_ortho_scale(minimum, maximum, center, yaw_count, pitches):
    corners = [
        Vector((x, y, z)) - center
        for x in (minimum.x, maximum.x)
        for y in (minimum.y, maximum.y)
        for z in (minimum.z, maximum.z)
    ]
    extent = 0.0
    for pitch in pitches:
        for yaw in range(yaw_count):
            rotation = (-camera_direction(yaw, yaw_count, pitch)).to_track_quat("-Z", "Y").inverted()
            for corner in corners:
                point = rotation @ corner
                extent = max(extent, abs(point.x), abs(point.y))
    return extent * 2


def has_render_output(folder):
    return (folder / RENDER_INFO).exists() or any(
        any(folder.glob(f"*step_*_yaw_*_pitch_*.{extension}"))
        for extension in ("jpg", "webp")
    )


def render_stages(input_dir, output_dir, resolution, quality, yaw_count,
                  pitch_count, min_elevation, max_elevation, framing, transparent=False,
                  model_prefix="chLavaMon"):
    if not 1 <= yaw_count <= 99:
        raise ValueError("Horizontal views must be between 1 and 99.")
    pitches = elevation_angles(pitch_count, min_elevation, max_elevation)
    if not math.isfinite(framing) or not 0.1 <= framing <= 5:
        raise ValueError("Framing scale must be between 0.1 and 5.")
    files = stage_files(input_dir, model_prefix)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if has_render_output(output):
        raise ValueError("Output folder already contains a render or its metadata; choose an empty folder.")

    minimum = Vector((float("inf"),) * 3)
    maximum = Vector((float("-inf"),) * 3)
    for path in files:
        reset_scene()
        import_stage(path)
        for point in model_bounds():
            for axis in range(3):
                minimum[axis] = min(minimum[axis], point[axis])
                maximum[axis] = max(maximum[axis], point[axis])
        print(f"Measured {path.name}", flush=True)

    center = (minimum + maximum) / 2
    diameter = (maximum - minimum).length
    if diameter <= 0:
        raise ValueError("The model bounds have zero size.")
    radius = diameter / 2
    ortho_scale = fitted_ortho_scale(minimum, maximum, center, yaw_count, pitches) * framing

    metadata = {
        "version": 1,
        "stages": len(files),
        "yaw_count": yaw_count,
        "pitch_count": pitch_count,
        "elevations_degrees": pitches,
        "transparent": transparent,
        "model_prefix": model_prefix,
        "framing": framing,
    }
    (output / RENDER_INFO).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    for stage, path in enumerate(files):
        reset_scene()
        import_stage(path)
        scene = bpy.context.scene
        # Workbench uses its own studio lighting, not imported scene lights.
        for obj in list(scene.objects):
            if obj.type in {"LIGHT", "CAMERA"}:
                bpy.data.objects.remove(obj, do_unlink=True)

        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.image_settings.file_format = "WEBP"
        scene.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
        scene.render.image_settings.quality = quality
        scene.render.film_transparent = transparent
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "TEXTURE"
        shading.background_type = "VIEWPORT"
        shading.background_color = (0.03, 0.03, 0.03)

        camera_data = bpy.data.cameras.new("Timelapse camera")
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = ortho_scale
        camera_data.clip_start = max(radius * 0.001, 0.0001)
        camera_data.clip_end = radius * 20
        camera = bpy.data.objects.new("Timelapse camera", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        for pitch_index, pitch_degrees in enumerate(pitches):
            for yaw_index in range(yaw_count):
                direction = camera_direction(yaw_index, yaw_count, pitch_degrees)
                camera.location = center + direction * radius * 4
                camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
                name = f"{model_prefix}_step_{stage:03d}_yaw_{yaw_index:02d}_pitch_{pitch_index:02d}.webp"
                scene.render.filepath = str(output / name)
                bpy.ops.render.render(write_still=True)
                print(f"Rendered {name}", flush=True)


class TIMELAPSE_OT_render(bpy.types.Operator):
    bl_idname = "timelapse.render_frames"
    bl_label = "Start Rendering"
    bl_description = "Render in a separate Blender process; see the log in the output folder"

    def execute(self, context):
        settings = context.scene.timelapse_settings
        input_dir = Path(bpy.path.abspath(settings.input_dir))
        output_dir = Path(bpy.path.abspath(settings.output_dir))
        if not settings.input_dir or not input_dir.is_dir() or not settings.output_dir:
            self.report({"ERROR"}, "Choose an existing input folder and an output folder.")
            return {"CANCELLED"}
        try:
            files = stage_files(input_dir, settings.model_prefix)
            elevation_angles(settings.pitch_count, settings.min_elevation, settings.max_elevation)
            output_dir.mkdir(parents=True, exist_ok=True)
            if has_render_output(output_dir):
                raise ValueError("Output folder already contains a render or its metadata.")
            lock_path = output_dir / ".timelapse-render.lock"
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(lock_fd)
            log_path = output_dir / "timelapse-render.log"
            command = [
                bpy.app.binary_path, "--background", "--python-exit-code", "1",
                "--python", os.path.abspath(__file__), "--",
                str(input_dir), str(output_dir), str(settings.resolution), str(settings.quality),
                str(settings.yaw_count), str(settings.pitch_count),
                str(settings.min_elevation), str(settings.max_elevation), str(settings.framing),
                "--model-prefix", settings.model_prefix,
            ]
            if settings.transparent:
                command.append("--transparent")
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            except OSError:
                lock_path.unlink()
                raise
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Started {len(files) * settings.yaw_count * settings.pitch_count} renders. See {log_path}")
        return {"FINISHED"}


class TIMELAPSE_Settings(bpy.types.PropertyGroup):
    model_prefix: bpy.props.StringProperty(name="Model prefix", default="chLavaMon")
    input_dir: bpy.props.StringProperty(name="GLB folder", subtype="DIR_PATH")
    output_dir: bpy.props.StringProperty(name="Output folder", subtype="DIR_PATH")
    resolution: bpy.props.IntProperty(name="Image width and height", default=1024, min=64, max=8192)
    quality: bpy.props.IntProperty(name="WebP quality", default=90, min=1, max=100)
    yaw_count: bpy.props.IntProperty(name="Horizontal views", default=12, min=1, max=99)
    pitch_count: bpy.props.IntProperty(name="Vertical views", default=4, min=1, max=99)
    min_elevation: bpy.props.FloatProperty(name="Minimum elevation (degrees)", default=0, min=-89, max=89)
    max_elevation: bpy.props.FloatProperty(name="Maximum elevation (degrees)", default=60, min=-89, max=89)
    framing: bpy.props.FloatProperty(name="Orthographic framing scale", default=1.15, min=0.1, max=5)
    transparent: bpy.props.BoolProperty(name="Transparent background", default=False)


class TIMELAPSE_PT_panel(bpy.types.Panel):
    bl_label = "Model Timelapse"
    bl_idname = "TIMELAPSE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Timelapse"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.timelapse_settings
        layout.prop(settings, "model_prefix")
        layout.prop(settings, "input_dir")
        layout.prop(settings, "output_dir")
        layout.prop(settings, "resolution")
        layout.prop(settings, "quality")
        layout.prop(settings, "yaw_count")
        layout.prop(settings, "pitch_count")
        layout.prop(settings, "min_elevation")
        layout.prop(settings, "max_elevation")
        layout.prop(settings, "framing")
        layout.prop(settings, "transparent")
        layout.operator("timelapse.render_frames")


classes = (TIMELAPSE_Settings, TIMELAPSE_OT_render, TIMELAPSE_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.timelapse_settings = bpy.props.PointerProperty(type=TIMELAPSE_Settings)


def unregister():
    del bpy.types.Scene.timelapse_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("resolution", type=int)
    parser.add_argument("quality", type=int)
    parser.add_argument("yaw_count", type=int)
    parser.add_argument("pitch_count", type=int)
    parser.add_argument("min_elevation", type=float)
    parser.add_argument("max_elevation", type=float)
    parser.add_argument("framing", type=float)
    parser.add_argument("--transparent", action="store_true")
    parser.add_argument("--model-prefix", default="chLavaMon")
    arguments = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    try:
        render_stages(
            arguments.input_dir, arguments.output_dir, arguments.resolution, arguments.quality,
            arguments.yaw_count, arguments.pitch_count, arguments.min_elevation,
            arguments.max_elevation, arguments.framing, arguments.transparent, arguments.model_prefix,
        )
        print("Rendering completed successfully.", flush=True)
    finally:
        lock_path = Path(arguments.output_dir) / ".timelapse-render.lock"
        lock_path.unlink(missing_ok=True)
