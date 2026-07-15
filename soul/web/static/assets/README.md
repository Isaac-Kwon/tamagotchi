# assets/

Intentionally empty. All room/character art in this M7 web UI is generated
procedurally at boot time in `js/room_scene.js` via Phaser's
`Graphics.generateTexture()` — no downloaded image files are used.

If you want richer art later, a CC0 pixel asset pack (e.g. from Kenney.nl)
can be dropped into this directory and swapped in by replacing the texture
keys generated in `room_scene.js._generateTextures()` with
`this.load.image(key, "assets/...")` calls in `preload()` instead.
