import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import upload_timelapse as uploader


class UploadTimelapseTests(unittest.TestCase):
    def make_frames(self, folder, stages=1, pitches=4, yaws=12):
        for stage in range(stages):
            for pitch in range(pitches):
                for yaw in range(yaws):
                    (folder / f"step_{stage:03d}_yaw_{yaw:02d}_pitch_{pitch:02d}.webp").write_bytes(
                        f"{stage}-{pitch}-{yaw}".encode()
                    )

    def test_variable_view_grid_and_missing_final_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_frames(folder, stages=2, pitches=3, yaws=6)
            metadata = {"version": 1, "stages": 2, "yaw_count": 6, "pitch_count": 3}
            (folder / uploader.RENDER_INFO).write_text(json.dumps(metadata))
            frames, stages, yaws, pitches = uploader.collect_frames(folder)
            self.assertEqual((len(frames), stages, yaws, pitches), (36, 2, 6, 3))
            args = ["upload_timelapse.py", str(folder), "--site", "https://example.com", "--username", "test"]
            def fake_upload(path, endpoint, authorization):
                return {"id": 1, "url": "https://example.com/" + path.name}
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch.object(uploader, "upload", side_effect=fake_upload), patch("builtins.print"):
                uploader.main()
            output = (folder / "wordpress-custom-html.txt").read_text()
            data = json.loads(output.split("const frames = ", 1)[1].split(";", 1)[0])
            self.assertEqual((len(data), len(data[0]), len(data[0][0])), (2, 3, 6))
            self.assertEqual(data[1][2][5], "https://example.com/step_001_yaw_05_pitch_02.webp")
            (folder / "step_001_yaw_05_pitch_02.webp").unlink()
            with self.assertRaisesRegex(ValueError, "step_001_yaw_05_pitch_02"):
                uploader.collect_frames(folder)
            metadata["stages"] = 3
            (folder / uploader.RENDER_INFO).write_text(json.dumps(metadata))
            self.make_frames(folder, stages=2, pitches=3, yaws=6)
            with self.assertRaisesRegex(ValueError, "step_002_yaw_00_pitch_00"):
                uploader.collect_frames(folder)

    def test_rejects_frames_outside_configured_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_frames(folder, pitches=1, yaws=2)
            (folder / uploader.RENDER_INFO).write_text(json.dumps(
                {"version": 1, "stages": 1, "yaw_count": 1, "pitch_count": 1}
            ))
            with self.assertRaisesRegex(ValueError, "outside the configured grid"):
                uploader.collect_frames(folder)

    def test_prefixed_frames_are_loaded_using_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / uploader.RENDER_INFO).write_text(json.dumps(
                {"version": 1, "stages": 1, "yaw_count": 2, "pitch_count": 1,
                 "model_prefix": "dragon"}
            ))
            for yaw in range(2):
                (folder / f"dragon_step_000_yaw_{yaw:02d}_pitch_00.webp").write_bytes(b"frame")
            frames, stages, yaws, pitches = uploader.collect_frames(folder)
            self.assertEqual((len(frames), stages, yaws, pitches), (2, 1, 2, 1))
            self.assertEqual(frames[0, 0, 1].name, "dragon_step_000_yaw_01_pitch_00.webp")
            args = ["upload_timelapse.py", str(folder), "--site", "https://example.com", "--username", "test"]
            def fake_upload(path, endpoint, authorization):
                return {"id": 1, "url": "https://example.com/" + path.name}
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch.object(uploader, "upload", side_effect=fake_upload), patch("builtins.print"):
                uploader.main()
            output = (folder / "wordpress-custom-html.txt").read_text()
            data = json.loads(output.split("const frames = ", 1)[1].split(";", 1)[0])
            self.assertEqual(data[0][0][1], "https://example.com/dragon_step_000_yaw_01_pitch_00.webp")
            (folder / "dragon_step_000_yaw_01_pitch_00.webp").unlink()
            with self.assertRaisesRegex(ValueError, "Missing dragon_step_000_yaw_01_pitch_00"):
                uploader.collect_frames(folder)

    def test_requires_complete_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_frames(folder)
            (folder / "step_000_yaw_03_pitch_02.webp").unlink()
            with self.assertRaisesRegex(ValueError, "step_000_yaw_03_pitch_02"):
                uploader.collect_frames(folder)

    def test_upload_sends_webp_content_type_and_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "step_000_yaw_00_pitch_00.webp"
            path.write_bytes(b"webp image bytes")
            response = BytesIO(b'{"id": 12, "source_url": "https://example.com/image.webp"}')
            with patch.object(uploader.OPENER, "open", return_value=response) as opened:
                result = uploader.upload(path, "https://example.com/wp-json/wp/v2/media", "Basic test")
            request = opened.call_args.args[0]
            self.assertEqual(request.get_header("Content-type"), "image/webp")
            self.assertEqual(request.get_header("Content-disposition"),
                             'attachment; filename="step_000_yaw_00_pitch_00.webp"')
            self.assertEqual(request.data, b"webp image bytes")
            self.assertEqual(result["url"], "https://example.com/image.webp")

    def test_uploads_actual_urls_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_frames(folder)
            calls = []

            def fake_upload(path, endpoint, authorization):
                calls.append(path.name)
                return {"id": len(calls), "url": "https://example.com/renamed/" + path.name}

            args = ["upload_timelapse.py", str(folder), "--site", "https://example.com", "--username", "test"]
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch.object(uploader, "upload", side_effect=fake_upload), \
                    patch("builtins.print"):
                uploader.main()
                uploader.main()
            self.assertEqual(len(calls), 48)
            output = (folder / "wordpress-custom-html.txt").read_text()
            self.assertNotIn(uploader.PLACEHOLDER, output)
            data = json.loads(output.split("const frames = ", 1)[1].split(";", 1)[0])
            self.assertEqual(len(data[0]), 4)
            self.assertEqual(len(data[0][0]), 12)
            self.assertEqual(data[0][2][3], "https://example.com/renamed/step_000_yaw_03_pitch_02.webp")
            state = json.loads((folder / "timelapse-uploads.json").read_text())
            self.assertEqual(len(state["uploads"]), 48)

            (folder / "step_000_yaw_00_pitch_00.webp").write_bytes(b"changed")
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch("builtins.print"), self.assertRaisesRegex(ValueError, "changed since upload"):
                uploader.main()

    def test_interrupted_upload_resumes_recorded_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.make_frames(folder)
            calls = []

            def fake_upload(path, endpoint, authorization):
                if len(calls) == 3:
                    raise OSError("connection interrupted")
                calls.append(path.name)
                return {"id": len(calls), "url": "https://example.com/" + path.name}

            args = ["upload_timelapse.py", str(folder), "--site", "https://example.com", "--username", "test"]
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch.object(uploader, "upload", side_effect=fake_upload), patch("builtins.print"):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    uploader.main()
            state = json.loads((folder / "timelapse-uploads.json").read_text())
            self.assertEqual(len(state["uploads"]), 3)
            with patch("sys.argv", args), patch.object(uploader.getpass, "getpass", return_value="secret"), \
                    patch.object(uploader, "upload", return_value={"id": 9, "url": "https://example.com/new.webp"}) as upload, \
                    patch("builtins.print"):
                uploader.main()
            self.assertEqual(upload.call_count, 45)


if __name__ == "__main__":
    unittest.main()
