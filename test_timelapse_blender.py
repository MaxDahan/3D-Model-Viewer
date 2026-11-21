import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


def load_addon():
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(
        Operator=type("Operator", (), {}),
        PropertyGroup=type("PropertyGroup", (), {}),
        Panel=type("Panel", (), {}),
    )
    bpy.props = types.SimpleNamespace(
        StringProperty=MagicMock(), IntProperty=MagicMock(), FloatProperty=MagicMock(),
        BoolProperty=MagicMock(),
    )
    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = MagicMock()
    spec = importlib.util.spec_from_file_location(
        "timelapse_blender_test", Path(__file__).with_name("timelapse_blender.py")
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"bpy": bpy, "mathutils": mathutils}):
        spec.loader.exec_module(module)
    return module


class StageFilesTests(unittest.TestCase):
    def setUp(self):
        self.addon = load_addon()

    def test_orders_lava_mon_versions_starting_at_one(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("chLavaMon_V0003.glb", "chLavaMon_V0001.glb", "chLavaMon_V0002.glb"):
                (folder / name).touch()
            self.assertEqual(
                [path.name for path in self.addon.stage_files(folder)],
                ["chLavaMon_V0001.glb", "chLavaMon_V0002.glb", "chLavaMon_V0003.glb"],
            )

    def test_rejects_missing_versions_and_other_models(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "chLavaMon_V0001.glb").touch()
            (folder / "chLavaMon_V0003.glb").touch()
            with self.assertRaisesRegex(ValueError, "consecutively"):
                self.addon.stage_files(folder)
            (folder / "other_V0002.glb").touch()
            with self.assertRaisesRegex(ValueError, "chLavaMon_V0001"):
                self.addon.stage_files(folder)

    def test_selects_another_model_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "dragon_V0001.glb").touch()
            (folder / "dragon_V0002.glb").touch()
            self.assertEqual(len(self.addon.stage_files(folder, "dragon")), 2)
            for prefix in ("", "../dragon", "dragon name"):
                with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "Model prefix"):
                    self.addon.stage_files(folder, prefix)


class ElevationTests(unittest.TestCase):
    def setUp(self):
        self.addon = load_addon()

    def test_evenly_spaced_and_single_elevation(self):
        self.assertEqual(self.addon.elevation_angles(4, 0, 60), [0, 20, 40, 60])
        self.assertEqual(self.addon.elevation_angles(3, -30, 30), [-30, 0, 30])
        self.assertEqual(self.addon.elevation_angles(1, -20, 60), [-20])

    def test_rejects_invalid_ranges(self):
        for count, minimum, maximum in [(0, 0, 60), (2, 20, 20), (2, 60, 0), (1, -90, 60)]:
            with self.subTest(count=count, minimum=minimum, maximum=maximum):
                with self.assertRaises(ValueError):
                    self.addon.elevation_angles(count, minimum, maximum)


class RenderOperatorTests(unittest.TestCase):
    def test_transparency_checkbox_is_passed_to_background_render(self):
        addon = load_addon()
        addon.bpy.path = types.SimpleNamespace(abspath=lambda path: path)
        addon.bpy.app = types.SimpleNamespace(binary_path="blender")
        for transparent in (False, True):
            with self.subTest(transparent=transparent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                input_dir = root / "input"
                input_dir.mkdir()
                (input_dir / "chLavaMon_V0001.glb").touch()
                settings = types.SimpleNamespace(
                    input_dir=str(input_dir), output_dir=str(root / "output"),
                    pitch_count=1, yaw_count=1, min_elevation=0, max_elevation=60,
                    resolution=128, quality=90, framing=1.15, transparent=transparent,
                    model_prefix="chLavaMon",
                )
                context = types.SimpleNamespace(scene=types.SimpleNamespace(timelapse_settings=settings))
                operator = addon.TIMELAPSE_OT_render()
                operator.report = MagicMock()
                with patch.object(addon.subprocess, "Popen") as popen:
                    self.assertEqual(operator.execute(context), {"FINISHED"})
                command = popen.call_args.args[0]
                self.assertEqual("--transparent" in command, transparent)
                self.assertEqual(command[command.index("--model-prefix") + 1], "chLavaMon")


if __name__ == "__main__":
    unittest.main()
