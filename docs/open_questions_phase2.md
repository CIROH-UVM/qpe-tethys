# NGPE Platform — Open Questions (Phase 2)

Hey Pat, here's a summary of where things stand after the Phase 2 workflow refactors and a few open items I'd like your input on before moving forward.

## What's Done in Phase 2

Quick recap of what landed in this push:

- **Always-recording workflow**: No start/stop — every tool action is automatically a workflow step.
- **Tools added via workflow panel only**: Removed standalone tool buttons from the map. You add a step, configure it in the right panel, and run.
- **WorkflowStep wraps the actual Tool object** (not copies of properties).
- **Step output references**: Steps can reference previous step outputs using `step:0`, `step:1`, etc. This lets you build a full pipeline (Load Radar → Scale/Bias on step 1's output) before running anything.
- **Run individual steps**: The play button next to each step lets you run just that one (e.g., load data first, then draw your polygon, then run scale/bias).
- **Pre-run validation**: All tools check their inputs before the engine runs. Clear error messages if something's missing.
- **Re-run cleanup**: Re-running a step or workflow removes previous output layers first, so you don't get duplicates on the map.
- **Save/Load/Clear workflows**: JSON persistence to disk. Survives server restarts.
- **Polygon drawing tied to selected step**: Draw Extent button only appears when the selected step has a polygon property.

---

## Open Questions

### 1. Colormap doesn't match the data

Right now MRMS returns **composite reflectivity (CREF) in dBZ**, with values ranging 0–75. But our colormap is built for QPE precipitation in inches (0–5 range). Everything above 5 just shows as solid purple.

**Options:**
- (a) Build a separate dBZ colormap for CREF (quick fix, we'd swap it in based on dataset type)
- (b) Wait until we have a true QPE product and keep the current colormap

Which do you prefer? If we're getting a real QPE product soon, (b) makes sense. Otherwise (a) is maybe an hour of work.

### 2. Gauge points all look the same

The code generates per-station QC colors (green for good, blue for suspect, orange for bad, etc.) in the GeoJSON properties, but OL's Vector layer renders everything with the default blue style. The custom styling info is there in the data — it's just not being picked up on the JS side.

I'm not sure if Tethys's OL wrappers support per-feature styling from GeoJSON properties. **Do you know if there's a way to pass a style function through the component API?** If not, one workaround is splitting gauges into separate layers by QC flag, each with its own color. It's a bit ugly but it would work.

### 3. Layer visibility toggle doesn't actually hide the layer

Clicking the eye icon updates the state correctly, but OpenLayers ignores property patches on layers that already exist in the map. The only way to truly hide a layer is to remove it from the map children and change the map key (which triggers a full map remount and resets the view position/zoom).

This is a known limitation of the OL + VDOM approach. **Is this something we should invest time fixing (maybe through JS interop), or is it acceptable for the demo?**

### 4. No disk caching for downloaded data

We have an in-memory cache that prevents re-downloading the same MRMS/MADIS data during a session. But it's lost on every server restart. For the current dev workflow this is fine, but if we're doing demos or Pat-style exploratory sessions, re-downloading every restart gets slow.

**Should I add a simple disk cache (pickle/netCDF files in the workspace), or is in-memory enough for now?**

### 5. Temp files from downloads pile up

Noah's `mrms.py` and `madis.py` both create temporary directories for downloads (`mkdtemp()`) but never clean them up. Over time these accumulate. Not urgent, but worth knowing about.

**Should I add cleanup logic now, or is this a "fix it later" item?**

### 6. Where should workflows be saved?

Currently workflows persist as JSON files in `tethysapp/ngpe/workspaces/app_workspace/workflows/`. This works, but it's inside the app source tree (though gitignored via the `workspaces/` directory).

**Does Tethys 4.4.3 have a proper app workspace API we should use instead?** I want to make sure we're putting user data in the right place before it matters.

### 7. What's next? (Phase 3 priorities)

A few things we could work on next — would be helpful to know your priority order:

- **Merge tool** — combine radar + gauge into a single adjusted product
- **Export** — save the adjusted raster as GeoTIFF or NetCDF for external use
- **Undo/redo** — step-level undo within a workflow
- **Better map interactivity** — zoom-to-layer, click-to-inspect values
- **Multi-user** — shared workflow library across users

My guess is Merge and Export are the most useful next, but let me know what you think.

---

Let me know which of these you want to tackle first or if any of these questions change direction on something. Happy to jump on a call if easier.

— Venkat
