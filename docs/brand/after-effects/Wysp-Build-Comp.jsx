/*
 * Wysp mascot: builds the composition in After Effects.
 * File > Scripts > Run Script File... and pick this file (keep it next to the "layers-svg" and "layers-png" folders).
 * Not run in After Effects by the person who wrote it: if it stops with an error, use the manual way in README.md.
 */
(function () {
    var USE_SVG = true;          // false: use the PNG layers (2048 px, shown at 50%)
    var COMP_W = 1920, COMP_H = 1080, FPS = 30, DURATION = 6;
    var LAYERS = [
        {
                "name": "01-flame-outer",
                "pivot": [
                        512.5,
                        1015
                ]
        },
        {
                "name": "02-flame-shine",
                "pivot": [
                        242.0,
                        700.5
                ]
        },
        {
                "name": "03-flame-inner",
                "pivot": [
                        513.0,
                        1002
                ]
        },
        {
                "name": "04-face",
                "pivot": [
                        511.0,
                        673.5
                ]
        },
        {
                "name": "05-cheek-left",
                "pivot": [
                        313.5,
                        779.5
                ]
        },
        {
                "name": "06-cheek-right",
                "pivot": [
                        708.0,
                        779.5
                ]
        },
        {
                "name": "07-glasses",
                "pivot": [
                        511.0,
                        696.5
                ]
        },
        {
                "name": "08-eye-left",
                "pivot": [
                        370.5,
                        704.5
                ]
        },
        {
                "name": "09-eye-right",
                "pivot": [
                        651.0,
                        704.5
                ]
        },
        {
                "name": "10-sparkle-left",
                "pivot": [
                        354.0,
                        679.5
                ]
        },
        {
                "name": "11-sparkle-right",
                "pivot": [
                        634.0,
                        679.5
                ]
        },
        {
                "name": "12-mouth",
                "pivot": [
                        510.5,
                        791.0
                ]
        }
];

    var here = File($.fileName).parent;
    var dir = new Folder(here.fsName + (USE_SVG ? "/layers-svg" : "/layers-png"));
    if (!dir.exists) { alert("Cannot find the folder " + dir.fsName); return; }

    app.beginUndoGroup("Wysp mascot");
    var comp = app.project.items.addComp("Wysp mascot", COMP_W, COMP_H, 1, DURATION, FPS);
    comp.bgColor = [0.071, 0.02, 0.196];   // night #120532
    var folder = app.project.items.addFolder("Wysp layers");
    var k = USE_SVG ? 1 : 2;               // layer pixels per canvas unit
    var left = COMP_W / 2 - 512, top = COMP_H / 2 - 512;   // where the 1024 canvas starts in the comp

    for (var i = 0; i < LAYERS.length; i++) {
        var spec = LAYERS[i];
        var file = new File(dir.fsName + "/" + spec.name + (USE_SVG ? ".svg" : ".png"));
        if (!file.exists) { alert("Missing " + file.fsName); continue; }
        var io = new ImportOptions(file);
        io.importAs = ImportAsType.FOOTAGE;
        var item = app.project.importFile(io);
        item.parentFolder = folder;
        var layer = comp.layers.add(item);
        layer.name = spec.name.replace(/^\d+-/, "");
        if (USE_SVG) { layer.collapseTransformation = true; }   // continuously rasterize: stays sharp when scaled
        // Pivot in canvas units -> position in the comp, so every layer still sits exactly where it was drawn.
        layer.anchorPoint.setValue([spec.pivot[0] * k, spec.pivot[1] * k]);
        layer.position.setValue([left + spec.pivot[0], top + spec.pivot[1]]);
        if (!USE_SVG) { layer.scale.setValue([50, 50]); }
    }
    comp.openInViewer();
    app.endUndoGroup();
})();
