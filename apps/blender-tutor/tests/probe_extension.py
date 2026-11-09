"""Check the INSTALLED extension end to end: connect to a running Core and answer one observe request.

    blender -b --python probe_extension.py        (the Core must be running: scripts/dev_up.ps1 -NoBlender)

In a window, bpy.app.timers calls the same _pump() function; here we call it by hand.
"""

import importlib
import time
import urllib.request

import bpy

EXT = "bl_ext.user_default.wysp_tutor"
bpy.ops.wm.open_mainfile(filepath=r"{scene}")
mod = importlib.import_module(EXT)
prefs = bpy.context.preferences.addons[EXT].preferences
print("PROBE-EXT prefs:", prefs.core_url)
print("PROBE-EXT connect ->", mod.connect())
deadline = time.monotonic() + 15
connected = False
while time.monotonic() < deadline:
    mod._pump()
    adapter = mod._adapter
    if adapter and adapter.client and adapter.client.connected:
        connected = True
        break
    time.sleep(0.02)
print("PROBE-EXT connected:", connected, "| last_error:", mod._adapter.client.last_error if mod._adapter else None)
if connected:
    health = urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3).read().decode()
    print("PROBE-EXT core sees adapter:", "blender-tutor" in health)
    # let the Core ask for an observation through the pump
    end = time.monotonic() + 4
    while time.monotonic() < end:
        mod._pump()
        time.sleep(0.02)
mod.disconnect()
print("PROBE-EXT-DONE")
