#!/usr/bin/env python3
"""Upload rendered frames and produce a WordPress Custom HTML block."""

import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


MODEL_PREFIX_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
RENDER_INFO = "timelapse-render.json"
PLACEHOLDER = "__TIMELAPSE_DATA__"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


OPENER = build_opener(NoRedirect)


def collect_frames(folder):
    metadata_path = folder / RENDER_INFO
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("version") != 1:
            raise ValueError("Invalid or unsupported render metadata.")
        model_prefix = metadata.get("model_prefix", "")
        if not isinstance(model_prefix, str) or (model_prefix and not MODEL_PREFIX_PATTERN.fullmatch(model_prefix)):
            raise ValueError("Invalid model prefix in render metadata.")
        stages, yaw_count, pitch_count = (
            metadata.get("stages"), metadata.get("yaw_count"), metadata.get("pitch_count")
        )
        if (type(stages) is not int or stages < 1
                or type(yaw_count) is not int or not 1 <= yaw_count <= 99
                or type(pitch_count) is not int or not 1 <= pitch_count <= 99):
            raise ValueError("Invalid stage or view counts in render metadata.")
    else:
        model_prefix = ""
        yaw_count, pitch_count = 12, 4
        print("No render metadata found; checking for the original 12 × 4 view grid.")
    prefix = f"{model_prefix}_" if model_prefix else ""
    frame_pattern = re.compile(rf"{re.escape(prefix)}step_(\d{{3,}})_yaw_(\d{{2}})_pitch_(\d{{2}})\.webp")
    frames = {}
    for path in folder.glob("*.webp"):
        match = frame_pattern.fullmatch(path.name)
        if not match:
            continue
        stage, yaw, pitch = map(int, match.groups())
        key = (stage, pitch, yaw)
        if key in frames:
            raise ValueError(f"Invalid or duplicate frame: {path.name}")
        frames[key] = path
    if not frames:
        raise ValueError(f"No matching rendered WebP frames found for prefix {model_prefix!r}.")
    if not metadata_path.exists():
        stages = max(key[0] for key in frames) + 1
    for (stage, pitch, yaw), path in frames.items():
        if stage >= stages or yaw >= yaw_count or pitch >= pitch_count:
            raise ValueError(f"Frame is outside the configured grid: {path.name}")
    for stage in range(stages):
        for pitch in range(pitch_count):
            for yaw in range(yaw_count):
                if (stage, pitch, yaw) not in frames:
                    raise ValueError(f"Missing {prefix}step_{stage:03d}_yaw_{yaw:02d}_pitch_{pitch:02d}.webp")
    return frames, stages, yaw_count, pitch_count


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def upload(path, endpoint, authorization):
    request = Request(endpoint, data=path.read_bytes(), method="POST", headers={
        "Authorization": authorization,
        "Content-Type": "image/webp",
        "Content-Disposition": f'attachment; filename="{path.name}"',
    })
    with OPENER.open(request, timeout=120) as response:
        result = json.load(response)
    if not isinstance(result.get("id"), int) or not isinstance(result.get("source_url"), str):
        raise ValueError(f"WordPress did not return an attachment ID and URL for {path.name}.")
    url = result["source_url"]
    if urlparse(url).scheme != "https":
        raise ValueError(f"WordPress returned a non-HTTPS URL for {path.name}: {url}")
    return {"id": result["id"], "url": url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path, help="Folder containing rendered WebP images")
    parser.add_argument("--site", required=True, help="WordPress site URL, including https://")
    parser.add_argument("--username", required=True, help="WordPress username")
    args = parser.parse_args()
    site = args.site.rstrip("/")
    parsed = urlparse(site)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Use the site's HTTPS URL, without a query string or fragment.")
    frames, stages, yaw_count, pitch_count = collect_frames(args.frames)
    state_path = args.frames / "timelapse-uploads.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("site") != site or not isinstance(state.get("uploads"), dict):
            raise ValueError("Existing upload record belongs to a different site or is invalid.")
    else:
        state = {"site": site, "uploads": {}}
    password = getpass.getpass("WordPress application password (not your normal password): ")
    if not password:
        raise ValueError("An application password is required.")
    credentials = f"{args.username}:{password}".encode("utf-8")
    authorization = "Basic " + base64.b64encode(credentials).decode("ascii")
    endpoint = site + "/wp-json/wp/v2/media"
    data = [[[None for _ in range(yaw_count)] for _ in range(pitch_count)] for _ in range(stages)]
    for index, (key, path) in enumerate(sorted(frames.items()), 1):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = state["uploads"].get(path.name)
        if existing:
            if existing.get("sha256") != digest:
                raise ValueError(f"{path.name} changed since upload. Use a new output folder.")
            result = existing
        else:
            result = upload(path, endpoint, authorization)
            result["sha256"] = digest
            state["uploads"][path.name] = result
            save_state(state_path, state)
        stage, pitch, yaw = key
        data[stage][pitch][yaw] = result["url"]
        print(f"{index}/{len(frames)}: {path.name}", flush=True)

    template = Path(__file__).with_name("wordpress-timelapse.html").read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError("Viewer template is missing its unique configuration placeholder.")
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    output = args.frames / "wordpress-custom-html.txt"
    output.write_text(template.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"\nFinished. Paste the contents of {output} into a WordPress Custom HTML block.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"WordPress returned HTTP {error.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except (OSError, URLError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
