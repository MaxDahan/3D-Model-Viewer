# Model timelapse prototype

This prototype renders one GLB per model stage and displays the resulting WebP
images from the WordPress Media Library in a Custom HTML block. Test with two or
three stages before a full run.
This is a draft: check the real models, rendering, hosting limits, and the
published WordPress page before committing to a large upload.

## 1. Prepare the stages

Put the stages in one folder, using this model's consecutive version names,
starting at `V0001`:

```text
chLavaMon_V0001.glb
chLavaMon_V0002.glb
chLavaMon_V0003.glb
```

The renderer currently expects the `chLavaMon` name and consecutive version
numbers. The first input, `chLavaMon_V0001.glb`, becomes output stage `step_000`.
We can add other model names later.

Each GLB must show the model at that stage. A final GLB cannot recreate the
earlier modeling history. Keep all stages in the same position, orientation and
scale. The renderer measures the combined bounds of all stages and uses the
same orthographic framing and Workbench studio shading for every image.
Imported cameras and lights are removed from the render scene. Workbench uses
simplified shading and may not reproduce the model's full materials. Check the
first test renders for textures, missing objects and framing before rendering
the rest.

## 2. Render in Blender

1. In Blender 5.3, open **Edit > Preferences > Add-ons**. Use the top-right menu
   and select **Install from Disk**, choose `timelapse_blender.py`, and enable
   **Model Timelapse Frame Renderer**. This single `.py` file is all your friend
   needs to render. If an earlier draft is installed, replace it with this
   updated version.
2. In the 3D View, open the sidebar with **N**, then open **Timelapse**.
3. Select the GLB folder and an output folder. Use a new, empty output folder.
   The defaults are 1024 × 1024 WebP, quality 90, 12 horizontal views and
   4 vertical views.
   - Horizontal views are evenly spaced around 360°.
   - Vertical views are evenly spaced between the minimum and maximum
     elevations, in degrees. The defaults are 0° to 60°; negative values look
     upward from below. With one vertical view, the minimum is used. Allowed
     elevations are -89° to 89°; for multiple views the minimum must be lower.
   - **Orthographic framing scale** controls the framing around the combined
     model bounds. The default is 1.15; larger values zoom out.
4. Click **Start Rendering**. A separate Blender process renders in the
   background; check `timelapse-render.log` in the output folder. Completion is
   indicated by `Rendering completed successfully.` An error will be in the
   same log.

The filename records the zero-based stage, yaw index and pitch index, for
example `step_001_yaw_03_pitch_02.webp`. Total images = stages × horizontal
views × vertical views. For 150 stages, 12 × 4 produces 7,200 images, while
6 × 3 produces 2,700. The current renderer uses an opaque background even
though WebP supports transparency. Dimensions and quality do not guarantee a
maximum file size. Older JPEG renders are not converted; render into a new folder.

The output includes `timelapse-render.json`, which records the stage and view
counts. Keep it alongside the images so the uploader can check the entire grid.
The background Workbench process needs functioning graphics support; if it
fails, check `timelapse-render.log` for the error.

Do not start a second render in the same folder. If Blender or the computer
crashes, a `.timelapse-render.lock` file may remain. Only after confirming the
render process has stopped, remove that lock and choose a new empty output
folder to rerun: this draft does not resume incomplete renders or overwrite
existing frames.

## 3. Upload manually and add the block

For the current chLavaMon test, upload all 120 WebP images to **Media > Library**.
The existing `wordpress-lavamon.html` block is configured for four stages, six
horizontal views, five vertical views and the November 2026 upload folder on
midomaru.com. Copy its entire contents into a WordPress **Custom HTML** block,
then save and test the actual page. No JSON or log file needs to be uploaded.
If WordPress renames a file or stores it in a different folder, its expected URL
will not work and the block must be updated.

The site must retain `<style>` and `<script>` tags; if it removes them, use a
plugin/theme integration instead. See [WordPress.com custom-code restrictions](https://wordpress.com/support/code/).

### Optional: automated upload

The following alternative uploads images and generates a block with the actual
URLs returned by WordPress. It is not needed for the manual workflow above.

The site must support WebP uploads, the standard WordPress REST API and application
passwords, and the account must have permission to upload media. Use an
application password created in the WordPress user profile, not the normal
login password. See [WordPress authentication documentation](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/).
Do not share the password; enter it only at the local command's hidden prompt.

On the computer that contains the rendered images, open a terminal in the folder
containing `upload_timelapse.py` and `wordpress-timelapse.html` and run:

```bash
python3 upload_timelapse.py "/path/to/rendered-images" --site "https://your-site.com" --username "your-wordpress-username"
```

The uploader checks that the complete configured grid exists for every stage.
For older renders without metadata, it checks the original 12 × 4 grid instead.
It uploads each image individually and writes `timelapse-uploads.json` in the
render folder after each successful upload. Keep that file: rerunning the same
command resumes using its saved attachment URLs, and stops if a saved image has
changed. WordPress may generate extra image sizes and may rename files; the
viewer uses the exact returned URLs. An upload interrupted after WordPress
accepts it but before the record is saved may need manual cleanup in Media
Library to avoid a duplicate. The script does not delete media.

The command refuses HTTP and redirects to avoid sending credentials to an
unexpected location. Use the site's final HTTPS URL. The account needs access
to the site's `/wp-json/wp/v2/media` endpoint; some hosting, security plugins,
or WordPress configurations may block it.

After all uploads finish, open `wordpress-custom-html.txt` in the render folder,
copy its entire contents, and paste it into a **Custom HTML** block on the
WordPress page. Do not paste `wordpress-timelapse.html` directly: it is a
template and does not contain your uploaded URLs. Save and test the actual page,
not just the editor preview. The code needs the site to retain `<style>` and
`<script>` tags; if it removes them, use a plugin/theme integration instead.
See [WordPress.com custom-code restrictions](https://wordpress.com/support/code/).

## 4. Viewer behavior

- Playback begins automatically at two stages per second and stops at the last
  stage. Visitors who request reduced motion start paused.
- Drag horizontally or vertically, or focus the image and use arrow keys.
  Angles are discrete; dragging does not change the stage.
- The slider pauses and selects a stage. Reset view changes the angle only.
- The viewer loads the current frame and prefetches the next stage at the
  current angle, rather than downloading every image at startup.
- Replay starts again at the first stage while retaining the current angle.

The full block contains one URL per image, so a 7,200-image project will produce
a large block and a crowded Media Library. Validate the hosting plan's storage,
upload limits, performance, and backup policy before uploading the complete
set. Upload and render duration depend on your hardware, model, and connection.
