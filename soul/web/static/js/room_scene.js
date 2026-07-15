// room_scene.js — the cozy room Phaser scene.
//
// Everything is procedurally generated at boot with Phaser Graphics ->
// generateTexture. No downloaded assets (see ../assets/README.md for how
// CC0 packs could replace this later).
//
// Public surface consumed by main.js:
//   scene.applyState(state)         — push a fresh /api/state or SSE payload
//   scene.setStale(isStale)         — dim/stop the character with "…"
//
// Station layout, action->station/animation, interest->expression, and
// decision->effect are all defined in mapping.js (single source of truth).
// This file only knows how to *render* what mapping.js decides.

import {
  STATIONS,
  ROOM_WIDTH,
  ROOM_HEIGHT,
  mapAction,
  mapStatusOverride,
  mapInterestTier,
  INTEREST_TIER_STYLE,
  mapDecisionEffect,
  bubbleTextFor,
  SPEECH_BUBBLE_MS,
  hadWikiWrite,
} from "./mapping.js";

// Icon drawn above the character's head per animation name.
const ANIMATION_ICON = {
  writing: "icon-pencil",
  reading: "icon-book",
  tidying: "icon-book",
  "thought-cloud": "icon-cloud",
  typing: "icon-monitor",
  scrolling: "icon-laptop",
  opening: "icon-envelope",
  zzz: "icon-zzz",
  talk: "icon-chat",
  wander: null,
  tinkering: "icon-wrench",
  stopped: "icon-ellipsis",
};

const FLOOR_COLOR = 0xdcc9a3;
const FLOOR_LINE = 0xcbb488;
const WALL_COLOR = 0xf1e6d2;
const RUG_COLOR = 0xc97b63;
const WOOD_DARK = 0x8a5a3b;
const WOOD_LIGHT = 0xb98352;

export class RoomScene extends Phaser.Scene {
  constructor() {
    super("room");
    this._bubbleTimer = null;
    this._targetStationKey = "center";
    this._walkTween = null;
    this._bobTween = null;
    this._lastStepId = null;
    this._sparkleEmitter = null;
    this._stale = false;
  }

  preload() {
    // Nothing to preload — every texture is generated in create().
  }

  create() {
    this.cameras.main.setBackgroundColor(WALL_COLOR);
    this._generateTextures();
    this._drawRoom();
    this._createCharacter();

    this.overlay = this.add
      .rectangle(0, 0, ROOM_WIDTH, ROOM_HEIGHT, 0x000000, 0.35)
      .setOrigin(0, 0)
      .setDepth(500)
      .setVisible(false);

    this.staleLabel = this.add
      .text(ROOM_WIDTH / 2, 40, "연결이 지연되고 있습니다 (stale)", {
        fontFamily: "sans-serif",
        fontSize: "16px",
        color: "#ffffff",
        backgroundColor: "#00000088",
        padding: { x: 8, y: 4 },
      })
      .setOrigin(0.5, 0)
      .setDepth(501)
      .setVisible(false);
  }

  // -------------------------------------------------------------------
  // Texture generation (procedural pixel art)
  // -------------------------------------------------------------------

  _tex(key, w, h, drawFn) {
    const g = this.add.graphics();
    drawFn(g);
    g.generateTexture(key, w, h);
    g.destroy();
  }

  _generateTextures() {
    // --- floor tile 32x32 ---
    this._tex("tile-floor", 32, 32, (g) => {
      g.fillStyle(FLOOR_COLOR, 1);
      g.fillRect(0, 0, 32, 32);
      g.lineStyle(1, FLOOR_LINE, 1);
      g.strokeRect(0, 0, 32, 32);
      g.lineBetween(0, 16, 32, 16);
    });

    // --- rug (under window) ---
    this._tex("rug", 160, 100, (g) => {
      g.fillStyle(RUG_COLOR, 1);
      g.fillRoundedRect(0, 0, 160, 100, 10);
      g.lineStyle(4, 0xa85f49, 1);
      g.strokeRoundedRect(4, 4, 152, 92, 8);
    });

    // --- bed ---
    this._tex("bed", 120, 90, (g) => {
      g.fillStyle(WOOD_DARK, 1);
      g.fillRect(0, 60, 120, 20);
      g.fillStyle(0xe8e4f0, 1);
      g.fillRoundedRect(4, 20, 112, 46, 6);
      g.fillStyle(0xffffff, 1);
      g.fillRoundedRect(8, 24, 34, 22, 5);
      g.fillStyle(0x7c6fb0, 1);
      g.fillRect(4, 0, 112, 22);
    });

    // --- desk (writing) ---
    this._tex("desk", 110, 70, (g) => {
      g.fillStyle(WOOD_LIGHT, 1);
      g.fillRect(0, 20, 110, 10);
      g.fillStyle(WOOD_DARK, 1);
      g.fillRect(6, 30, 8, 40);
      g.fillRect(96, 30, 8, 40);
      g.fillStyle(0xffffff, 1);
      g.fillRect(20, 10, 26, 18);
      g.fillStyle(0x333333, 1);
      g.fillRect(22, 12, 22, 12);
    });

    // --- computer desk ---
    this._tex("computer", 110, 80, (g) => {
      g.fillStyle(WOOD_LIGHT, 1);
      g.fillRect(0, 40, 110, 10);
      g.fillStyle(WOOD_DARK, 1);
      g.fillRect(6, 50, 8, 30);
      g.fillRect(96, 50, 8, 30);
      g.fillStyle(0x2c2c34, 1);
      g.fillRoundedRect(28, 4, 54, 38, 4);
      g.fillStyle(0x6cd4ff, 1);
      g.fillRect(32, 8, 46, 26);
      g.fillStyle(0x2c2c34, 1);
      g.fillRect(48, 42, 14, 6);
    });

    // --- bookshelf ---
    this._tex("bookshelf", 100, 130, (g) => {
      g.fillStyle(WOOD_DARK, 1);
      g.fillRect(0, 0, 100, 130);
      g.fillStyle(0x6b4426, 1);
      for (let i = 1; i < 4; i++) g.fillRect(4, i * 32, 92, 4);
      const bookColors = [0xd1495b, 0xedae49, 0x00798c, 0x30638e, 0x003d5b];
      for (let row = 0; row < 3; row++) {
        let x = 8;
        for (let i = 0; i < 8; i++) {
          const w = 6 + (i % 3) * 2;
          const h = 24;
          g.fillStyle(bookColors[(row + i) % bookColors.length], 1);
          g.fillRect(x, row * 32 + 4, w, h);
          x += w + 2;
        }
      }
    });

    // --- window (with laptop nook) ---
    this._tex("window", 100, 80, (g) => {
      g.fillStyle(WOOD_LIGHT, 1);
      g.fillRect(0, 0, 100, 80);
      g.fillStyle(0x9fd8ff, 1);
      g.fillRect(8, 8, 84, 56);
      g.lineStyle(4, WOOD_DARK, 1);
      g.strokeRect(8, 8, 84, 56);
      g.lineBetween(50, 8, 50, 64);
      g.lineBetween(8, 36, 92, 36);
      g.fillStyle(0xffffff, 1);
      g.fillCircle(30, 24, 8);
      g.fillCircle(65, 48, 6);
    });

    // --- laptop prop (small, placed on rug near window) ---
    this._tex("laptop", 40, 26, (g) => {
      g.fillStyle(0xcfcfcf, 1);
      g.fillRect(2, 14, 36, 4);
      g.fillStyle(0xe8e8e8, 1);
      g.fillRect(6, 0, 28, 14);
      g.fillStyle(0x3ba0d1, 1);
      g.fillRect(8, 2, 24, 10);
    });

    // --- workbench ---
    this._tex("workbench", 110, 70, (g) => {
      g.fillStyle(0x5c5c5c, 1);
      g.fillRect(0, 20, 110, 10);
      g.fillStyle(0x333333, 1);
      g.fillRect(6, 30, 8, 40);
      g.fillRect(96, 30, 8, 40);
      g.fillStyle(0xd8a24a, 1);
      g.fillRect(14, 6, 20, 14);
      g.fillStyle(0x777777, 1);
      g.fillCircle(60, 12, 8);
      g.fillStyle(0x444444, 1);
      g.fillCircle(60, 12, 3);
    });

    // --- mailbox ---
    this._tex("mailbox", 40, 60, (g) => {
      g.fillStyle(WOOD_DARK, 1);
      g.fillRect(16, 30, 8, 30);
      g.fillStyle(0xb23b3b, 1);
      g.fillRoundedRect(0, 0, 40, 30, 8);
      g.fillStyle(0xffffff, 1);
      g.fillRect(4, 12, 32, 4);
    });

    // --- door ---
    this._tex("door", 70, 130, (g) => {
      g.fillStyle(0x7a5230, 1);
      g.fillRoundedRect(0, 0, 70, 130, { tl: 30, tr: 30, bl: 0, br: 0 });
      g.fillStyle(0x593c22, 1);
      g.fillRoundedRect(8, 8, 54, 114, { tl: 24, tr: 24, bl: 0, br: 0 });
      g.fillStyle(0xd8b871, 1);
      g.fillCircle(52, 68, 3);
    });

    // --- character body (idle / walk share the same body texture) ---
    this._tex("char-body", 34, 44, (g) => {
      g.fillStyle(0xffd9a0, 1);
      g.fillCircle(17, 12, 10); // head
      g.fillStyle(0x6c8ebf, 1);
      g.fillRoundedRect(4, 20, 26, 22, 6); // torso
      g.fillStyle(0xffd9a0, 1);
      g.fillCircle(6, 30, 5); // left arm
      g.fillCircle(28, 30, 5); // right arm
      g.fillStyle(0x40506b, 1);
      g.fillRoundedRect(6, 40, 9, 4, 2); // left foot
      g.fillRoundedRect(19, 40, 9, 4, 2); // right foot
    });

    // desaturated / low-interest variant
    this._tex("char-body-droop", 34, 44, (g) => {
      g.fillStyle(0xd8cdb9, 1);
      g.fillCircle(17, 14, 10);
      g.fillStyle(0x8b8f97, 1);
      g.fillRoundedRect(4, 22, 26, 20, 6);
      g.fillStyle(0xd8cdb9, 1);
      g.fillCircle(6, 32, 5);
      g.fillCircle(28, 32, 5);
      g.fillStyle(0x5c5f66, 1);
      g.fillRoundedRect(6, 40, 9, 4, 2);
      g.fillRoundedRect(19, 40, 9, 4, 2);
    });

    // --- small icon textures (20x20-ish, drawn above the character) ---
    this._tex("icon-pencil", 20, 20, (g) => {
      g.fillStyle(0xf2c14e, 1);
      g.fillRect(4, 10, 12, 4);
      g.fillStyle(0xdd5c5c, 1);
      g.fillTriangle(16, 10, 20, 12, 16, 14);
      g.fillStyle(0x555555, 1);
      g.fillTriangle(2, 10, 4, 10, 3, 14);
    });
    this._tex("icon-book", 20, 20, (g) => {
      g.fillStyle(0x30638e, 1);
      g.fillRect(2, 4, 16, 12);
      g.fillStyle(0xffffff, 1);
      g.fillRect(4, 6, 12, 8);
      g.lineStyle(1, 0x30638e, 1);
      g.lineBetween(10, 6, 10, 14);
    });
    this._tex("icon-cloud", 24, 18, (g) => {
      g.fillStyle(0xffffff, 1);
      g.fillCircle(8, 10, 7);
      g.fillCircle(15, 8, 6);
      g.fillCircle(20, 11, 5);
      g.fillStyle(0xf2c14e, 1);
      g.fillCircle(20, 3, 3);
    });
    this._tex("icon-monitor", 20, 18, (g) => {
      g.fillStyle(0x2c2c34, 1);
      g.fillRoundedRect(0, 0, 20, 14, 2);
      g.fillStyle(0x6cd4ff, 1);
      g.fillRect(2, 2, 16, 10);
      g.fillStyle(0x2c2c34, 1);
      g.fillRect(7, 14, 6, 3);
    });
    this._tex("icon-laptop", 22, 16, (g) => {
      g.fillStyle(0xcfcfcf, 1);
      g.fillRect(1, 12, 20, 3);
      g.fillStyle(0xe8e8e8, 1);
      g.fillRect(3, 0, 16, 12);
      g.fillStyle(0x3ba0d1, 1);
      g.fillRect(5, 2, 12, 8);
    });
    this._tex("icon-envelope", 20, 16, (g) => {
      g.fillStyle(0xf4f1e8, 1);
      g.fillRect(0, 0, 20, 16);
      g.lineStyle(2, 0xb23b3b, 1);
      g.strokeRect(0, 0, 20, 16);
      g.lineBetween(0, 0, 10, 9);
      g.lineBetween(20, 0, 10, 9);
    });
    this._tex("icon-zzz", 22, 18, (g) => {
      g.fillStyle(0x6c8ebf, 1);
      g.fillRect(0, 0, 10, 3);
      g.fillTriangle(0, 3, 10, 3, 0, 9);
      g.fillRect(0, 6, 10, 3);
      g.fillStyle(0x8fa8cf, 1);
      g.fillRect(12, 9, 8, 2);
      g.fillTriangle(12, 11, 20, 11, 12, 15);
      g.fillRect(12, 13, 8, 2);
    });
    this._tex("icon-chat", 22, 18, (g) => {
      g.fillStyle(0xffffff, 1);
      g.fillRoundedRect(0, 0, 22, 14, 4);
      g.fillTriangle(4, 14, 10, 14, 4, 18);
      g.fillStyle(0x555555, 1);
      g.fillCircle(6, 7, 1.6);
      g.fillCircle(11, 7, 1.6);
      g.fillCircle(16, 7, 1.6);
    });
    this._tex("icon-wrench", 20, 20, (g) => {
      g.fillStyle(0x9a9a9a, 1);
      g.fillCircle(4, 4, 4);
      g.fillRect(4, 4, 12, 4);
      g.fillCircle(17, 16, 4);
    });
    this._tex("icon-ellipsis", 24, 8, (g) => {
      g.fillStyle(0x555555, 1);
      g.fillCircle(2, 4, 2.5);
      g.fillCircle(12, 4, 2.5);
      g.fillCircle(22, 4, 2.5);
    });
    this._tex("icon-bulb", 18, 24, (g) => {
      g.fillStyle(0xf2e14e, 1);
      g.fillCircle(9, 9, 8);
      g.fillStyle(0xb0a03a, 1);
      g.fillRect(5, 16, 8, 5);
    });
    this._tex("icon-note", 18, 20, (g) => {
      g.fillStyle(0xf4e9c1, 1);
      g.fillRect(0, 0, 18, 20);
      g.lineStyle(1, 0xc9b978, 1);
      for (let y = 5; y < 20; y += 5) g.lineBetween(2, y, 16, y);
    });
    this._tex("icon-crumple", 20, 20, (g) => {
      g.fillStyle(0xe8e2d0, 1);
      g.fillCircle(10, 10, 9);
      g.lineStyle(1, 0xbdb59c, 1);
      g.lineBetween(3, 6, 17, 12);
      g.lineBetween(4, 14, 16, 6);
      g.lineBetween(10, 2, 10, 18);
    });
    this._tex("spark", 8, 8, (g) => {
      g.fillStyle(0xfff2a8, 1);
      g.fillCircle(4, 4, 4);
    });
  }

  // -------------------------------------------------------------------
  // Room layout
  // -------------------------------------------------------------------

  _drawRoom() {
    for (let x = 0; x < ROOM_WIDTH; x += 32) {
      for (let y = 0; y < ROOM_HEIGHT; y += 32) {
        this.add.image(x, y, "tile-floor").setOrigin(0, 0).setDepth(0);
      }
    }

    const place = (key, station, depth, offsetY = 0) => {
      const pos = STATIONS[station];
      this.add.image(pos.x, pos.y + offsetY, key).setDepth(depth || Math.round(pos.y));
    };

    this.add.image(STATIONS.window_rug.x, STATIONS.window_rug.y + 30, "rug").setDepth(1);
    place("bed", "bed", 30);
    place("desk", "desk", 30);
    place("bookshelf", "bookshelf", 20, -30);
    place("window", "window_rug", 5, -110);
    place("computer", "computer", 30);
    place("window", "window_laptop", 5, -70);
    this.add.image(STATIONS.window_laptop.x - 10, STATIONS.window_laptop.y + 55, "laptop").setDepth(60);
    place("workbench", "workbench", 30);
    place("mailbox", "mailbox", 30);
    place("door", "door", 5, -30);

    // desk "wiki note" prop, hidden by default, shimmered on wiki_ops.
    this.wikiNoteProp = this.add
      .image(STATIONS.desk.x + 40, STATIONS.desk.y - 30, "icon-note")
      .setDepth(1000)
      .setVisible(false);
  }

  // -------------------------------------------------------------------
  // Character
  // -------------------------------------------------------------------

  _createCharacter() {
    const start = STATIONS.center;
    this.character = this.add.container(start.x, start.y);
    this.charBody = this.add.image(0, 0, "char-body").setOrigin(0.5, 1);
    this.charIcon = this.add.image(14, -46, "icon-pencil").setOrigin(0.5, 1).setVisible(false);
    this.faceGfx = this.add.graphics();
    this.character.add([this.charBody, this.faceGfx, this.charIcon]);
    this.character.setDepth(9999);

    this.bubbleContainer = this.add.container(0, -70);
    this.bubbleBg = this.add.graphics();
    this.bubbleTextObj = this.add
      .text(0, 0, "", {
        fontFamily: "sans-serif",
        fontSize: "13px",
        color: "#222222",
        wordWrap: { width: 180 },
        align: "center",
      })
      .setOrigin(0.5, 0.5);
    this.bubbleContainer.add([this.bubbleBg, this.bubbleTextObj]);
    this.bubbleContainer.setVisible(false);
    this.character.add(this.bubbleContainer);

    // Click the speech bubble -> emit an event main.js wires to the step
    // detail panel. Hit area is (re)sized in _showBubble() to match text.
    this.bubbleContainer.on("pointerdown", () => {
      this.events.emit("bubbleClick", this._lastStepId);
    });

    this._drawFace("neutral");
    this._startBob();
  }

  _startBob() {
    if (this._bobTween) this._bobTween.stop();
    this._bobTween = this.tweens.add({
      targets: this.charBody,
      y: -3,
      duration: 650,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
  }

  _drawFace(tier) {
    const style = INTEREST_TIER_STYLE[tier] || INTEREST_TIER_STYLE.neutral;
    const g = this.faceGfx;
    g.clear();
    g.fillStyle(0x2b2b2b, 1);
    // eyes
    if (tier === "droop") {
      g.fillCircle(12, -32, 1.6);
      g.fillCircle(22, -32, 1.6);
    } else {
      g.fillCircle(12, -33, 2);
      g.fillCircle(22, -33, 2);
    }
    // mouth
    g.lineStyle(2, 0x2b2b2b, 1);
    if (style.mouth === "frown") {
      g.beginPath();
      g.arc(17, -25, 5, Phaser.Math.DegToRad(200), Phaser.Math.DegToRad(340), true);
      g.strokePath();
    } else if (style.mouth === "flat") {
      g.lineBetween(12, -24, 22, -24);
    } else if (style.mouth === "smile") {
      g.beginPath();
      g.arc(17, -28, 5, Phaser.Math.DegToRad(20), Phaser.Math.DegToRad(160));
      g.strokePath();
    } else if (style.mouth === "bigsmile") {
      g.beginPath();
      g.arc(17, -29, 6, Phaser.Math.DegToRad(10), Phaser.Math.DegToRad(170));
      g.strokePath();
    }

    this.charBody.setTexture(style.desaturate ? "char-body-droop" : "char-body");
    this._setSparkle(!!style.sparkle, !!style.particles);
  }

  _setSparkle(sparkle, big) {
    if (this._sparkleEmitter) {
      this._sparkleEmitter.stop();
      this._sparkleEmitter.destroy();
      this._sparkleEmitter = null;
    }
    if (!sparkle) return;
    this._sparkleEmitter = this.add.particles(0, -40, "spark", {
      speed: { min: 10, max: big ? 40 : 20 },
      lifespan: 500,
      scale: { start: big ? 1.2 : 0.7, end: 0 },
      quantity: big ? 2 : 1,
      frequency: big ? 120 : 400,
      emitZone: { type: "random", source: new Phaser.Geom.Circle(0, 0, 16) },
    });
    this._sparkleEmitter.setDepth(10000);
    this.character.add(this._sparkleEmitter);
  }

  // -------------------------------------------------------------------
  // Movement + action rendering
  // -------------------------------------------------------------------

  _walkToStation(stationKey) {
    if (stationKey === this._targetStationKey && this._walkTween && this._walkTween.isPlaying()) return;
    this._targetStationKey = stationKey;
    const pos = STATIONS[stationKey] || STATIONS.center;
    if (this._walkTween) this._walkTween.stop();
    const dist = Phaser.Math.Distance.Between(this.character.x, this.character.y, pos.x, pos.y);
    const duration = Phaser.Math.Clamp(dist * 4, 200, 1800);
    this._walkTween = this.tweens.add({
      targets: this.character,
      x: pos.x,
      y: pos.y,
      duration,
      ease: "Sine.easeInOut",
      onUpdate: () => this.character.setDepth(Math.round(this.character.y)),
    });
  }

  _setActionIcon(animation) {
    const key = ANIMATION_ICON[animation];
    if (!key) {
      this.charIcon.setVisible(false);
      return;
    }
    this.charIcon.setTexture(key).setVisible(true);
    this.tweens.killTweensOf(this.charIcon);
    this.tweens.add({
      targets: this.charIcon,
      y: -50,
      duration: 500,
      yoyo: true,
      repeat: -1,
      ease: "Sine.easeInOut",
    });
  }

  _showBubble(text) {
    if (this._bubbleTimer) {
      clearTimeout(this._bubbleTimer);
      this._bubbleTimer = null;
    }
    if (!text) {
      this.bubbleContainer.setVisible(false);
      if (this.bubbleContainer.input) this.bubbleContainer.disableInteractive();
      return;
    }
    this.bubbleTextObj.setText(text.length > 120 ? text.slice(0, 117) + "…" : text);
    const b = this.bubbleTextObj.getBounds();
    const w = Math.max(60, b.width + 20);
    const h = Math.max(28, b.height + 16);
    this.bubbleBg.clear();
    this.bubbleBg.fillStyle(0xffffff, 0.95);
    this.bubbleBg.lineStyle(1.5, 0x333333, 1);
    this.bubbleBg.fillRoundedRect(-w / 2, -h / 2, w, h, 8);
    this.bubbleBg.strokeRoundedRect(-w / 2, -h / 2, w, h, 8);
    this.bubbleContainer.setInteractive(new Phaser.Geom.Rectangle(-w / 2, -h / 2, w, h), Phaser.Geom.Rectangle.Contains);
    this.bubbleContainer.input.cursor = "pointer";
    this.bubbleContainer.setVisible(true);
    this._bubbleTimer = setTimeout(() => {
      this.bubbleContainer.setVisible(false);
    }, SPEECH_BUBBLE_MS);
  }

  _playOneShotEffect(effect) {
    if (!effect) return;
    switch (effect.kind) {
      case "bulb-spark": {
        const icon = this.add.image(this.character.x, this.character.y - 80, "icon-bulb").setDepth(10001);
        this.tweens.add({
          targets: icon,
          y: icon.y - 20,
          alpha: 0,
          duration: 1200,
          onComplete: () => icon.destroy(),
        });
        break;
      }
      case "bang-relocate": {
        const bang = this.add
          .text(this.character.x, this.character.y - 90, "!", {
            fontFamily: "sans-serif",
            fontSize: "28px",
            color: "#e0463c",
            fontStyle: "bold",
          })
          .setOrigin(0.5)
          .setDepth(10001);
        this.tweens.add({
          targets: bang,
          scale: { from: 0.4, to: 1.3 },
          alpha: { from: 1, to: 0 },
          duration: 900,
          onComplete: () => bang.destroy(),
        });
        break;
      }
      case "note-slot": {
        const note = this.add.image(this.character.x + 20, this.character.y - 60, "icon-note").setDepth(10001);
        this.tweens.add({
          targets: note,
          x: STATIONS.bookshelf.x,
          y: STATIONS.bookshelf.y,
          scale: 0.4,
          alpha: 0,
          duration: 800,
          onComplete: () => note.destroy(),
        });
        break;
      }
      case "crumple-paper": {
        const paper = this.add.image(this.character.x, this.character.y - 60, "icon-crumple").setDepth(10001);
        this.tweens.add({
          targets: paper,
          x: paper.x + 60,
          y: paper.y + 40,
          angle: 180,
          alpha: 0,
          duration: 700,
          onComplete: () => paper.destroy(),
        });
        break;
      }
      default:
        break;
    }
  }

  _updateWikiProp(step) {
    if (!this.wikiNoteProp) return;
    if (hadWikiWrite(step)) {
      this.wikiNoteProp.setVisible(true);
      this.tweens.killTweensOf(this.wikiNoteProp);
      this.tweens.add({
        targets: this.wikiNoteProp,
        alpha: { from: 0.4, to: 1 },
        duration: 400,
        yoyo: true,
        repeat: 3,
      });
    }
  }

  // -------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------

  /**
   * Apply a full state.json-shaped payload. Defensive against missing
   * fields — a fresh install / partially-populated state should render an
   * idle room, not throw.
   */
  applyState(state) {
    if (!state || typeof state !== "object") {
      this.setStale(true);
      return;
    }
    const stale = !!state.stale;
    this.setStale(stale);
    if (stale) return;

    const lastStep = state.last_step || null;
    const override = mapStatusOverride(state.status, stale);
    const mapping = override || mapAction(lastStep && lastStep.action);

    this._walkToStation(mapping.station);
    this._setActionIcon(mapping.animation);

    const tier = mapInterestTier(lastStep && lastStep.interest);
    this._drawFace(tier);

    const isNewStep = lastStep && lastStep.id && lastStep.id !== this._lastStepId;
    if (isNewStep) {
      this._lastStepId = lastStep.id;
      this._showBubble(bubbleTextFor(lastStep));
      this._playOneShotEffect(mapDecisionEffect(lastStep.decision));
      this._updateWikiProp(lastStep);
    } else if (!lastStep) {
      this._showBubble(null);
    }
  }

  setStale(isStale) {
    this._stale = !!isStale;
    this.overlay.setVisible(this._stale);
    this.staleLabel.setVisible(this._stale);
    if (this._stale) {
      this._walkToStation("center");
      this._setActionIcon("stopped");
      this._showBubble("…");
      if (this._bobTween) this._bobTween.pause();
    } else if (this._bobTween) {
      this._bobTween.resume();
    }
  }
}
