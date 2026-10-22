#!/usr/bin/env python3
"""
Ink-blot pixel bat -- big flapping wings, motion trails, shockwaves and
floating soot.  Pure Python + tkinter (tkinter ships with Python, nothing to
install).

    python ink_bat.py

Look (matched to the reference screenshot): ragged dark ink pixels on light
gray, white square eyes, a hollow mouth, soot blobs / plus signs / specks
drifting around it, and a faint grid between the pixels.

Extras on top of the reference:
  * wings flap with real joints (shoulder -> elbow -> wrist -> fingers) that
    lag behind each other, so the wing whips instead of just swinging
  * the body bobs against the wings, the mouth opens on every downstroke
  * a burst of sparks flies off at the bottom of each stroke and the whole
    bat shakes a little (afterimage trails and the shockwave ring are built in
    but switched off -- see SHOW_TRAILS / SHOW_SHOCKWAVE)
  * soot blobs orbit and swell with the beat; the edges "boil" like wet ink

Tweak the numbers in the SETTINGS block.  Close the window to quit.
"""

import math
import random
import time
import tkinter as tk

# ------------------------------------------------------------------ SETTINGS
CELL = 3                    # screen pixels per sprite pixel
GRID_W, GRID_H = 200, 148   # sprite pixels  (window = 600 x 444)
FPS = 30

FLAP_PERIOD = 0.55          # seconds per full wing beat (smaller = faster)
WING_SWING = 1.0            # 1.0 = default, 1.3 = wilder wings
BODY_BOB = 3.2              # how far the body rocks against the wings
SHOW_TRAILS = False         # faint afterimage copies that follow the wings
SHOW_SHOCKWAVE = False      # the dotted ring that expands each downstroke
TRAIL_LAG = (0.035, 0.07)   # seconds behind the wings for the afterimages
EDGE_BOIL_HZ = 14           # how fast the ragged ink edges re-roll
BURST_SPARKS = 7            # sparks thrown off each wing per downstroke
IDLE_SPECKS_PER_SEC = 7
CROSSES_PER_SEC = 0.9

# colors: 0 background, 1 ink, 2 eyes, 3/4 light trail, 5/6 fading ink
BG = (168, 167, 165)
PALETTE = {0: BG, 1: (46, 43, 42), 2: (240, 240, 236), 3: (136, 135, 133),
           4: (152, 151, 149), 5: (88, 85, 84), 6: (122, 121, 119)}
GAP = {0: BG, 1: (92, 89, 88), 2: (205, 205, 200), 3: (148, 147, 145),
       4: (160, 159, 157), 5: (120, 118, 116), 6: (140, 139, 137)}

# a few soot blobs: (orbit x, orbit y, angular speed, phase, size)
BLOBS = [
    (40, 20, 0.90, 0.2, 3.6), (33, 28, -1.15, 2.1, 2.9), (46, 12, 0.70, 4.0, 3.2),
    (28, 15, 1.35, 5.2, 2.2), (44, 31, -0.80, 1.0, 3.9), (37, 8, -1.45, 3.3, 1.9),
    (24, 26, 1.05, 0.9, 2.6),
]

CX, CY = GRID_W / 2, GRID_H / 2 + 2


# ------------------------------------------------------------ small helpers
def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def polar(angle, length):
    """Vector pointing `angle` radians counter-clockwise from +x (screen y is down)."""
    return (math.cos(angle) * length, -math.sin(angle) * length)


def fill_poly(rows, poly, val, ox=0.0, oy=0.0):
    """Scanline polygon fill into a list of bytearrays."""
    n = len(poly)
    ys = [p[1] + oy for p in poly]
    r0 = max(0, int(math.ceil(min(ys) - 0.5)))
    r1 = min(GRID_H - 1, int(math.floor(max(ys) - 0.5)))
    for r in range(r0, r1 + 1):
        yc = r + 0.5
        xs = []
        for i in range(n):
            xa, ya = poly[i]
            xb, yb = poly[(i + 1) % n]
            ya += oy
            yb += oy
            if (ya <= yc < yb) or (yb <= yc < ya):
                xs.append(xa + ox + (yc - ya) * (xb - xa) / (yb - ya))
        xs.sort()
        row = rows[r]
        for k in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[k] - 0.5)))
            b = min(GRID_W - 1, int(math.floor(xs[k + 1] - 0.5)))
            if b >= a:
                row[a:b + 1] = bytes([val]) * (b - a + 1)


def ellipse(cx, cy, rx, ry, n=20):
    return [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def thick_line(p, q, w):
    dx, dy = q[0] - p[0], q[1] - p[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln * w / 2, dx / ln * w / 2
    return [(p[0] + nx, p[1] + ny), (q[0] + nx, q[1] + ny),
            (q[0] - nx, q[1] - ny), (p[0] - nx, p[1] - ny)]


def put(grid, x, y, val):
    x, y = int(x), int(y)
    if 0 <= x < GRID_W and 0 <= y < GRID_H:
        grid[y][x] = val


def noise(a, b, c, d):
    x = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791) ^ (d * 2654435761)
    x &= 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 0x5BD1E995) & 0xFFFFFFFF
    x ^= x >> 15
    return x & 0xFFFF


# ------------------------------------------------------------------ the bat
def pose(t):
    """Everything that moves with the wing beat at time t."""
    phi = 2 * math.pi * t / FLAP_PERIOD
    bob = BODY_BOB * math.cos(phi)
    x0 = CX + 3.0 * math.sin(0.9 * t)
    y0 = CY + bob + 2.2 * math.sin(1.7 * t)
    return phi, x0, y0


def wing_shape(phi):
    """Right-wing joints relative to the body center, plus its filled pieces."""
    s = WING_SWING
    b1 = math.radians(5 + 42 * s * math.cos(phi))              # upper arm
    b2 = math.radians(10 + 60 * s * math.cos(phi - 0.9))       # forearm lags
    lag = 28 * s * math.sin(phi - 0.9)                         # fingers trail the stroke

    shoulder = (6.0, -3.0)
    elbow = add(shoulder, polar(b1, 10))
    wrist = add(elbow, polar(b2, 12))
    tips = []
    for i, (fan, length) in enumerate(((8, 17), (-22, 19), (-52, 17))):
        ang = b2 + math.radians(fan + lag * (0.6 + 0.25 * i))
        tips.append(add(wrist, polar(ang, length)))
    hip = (4.0, 8.0)

    def notch(a, b):
        return lerp(lerp(a, b, 0.5), wrist, 0.36)

    # The membrane is built from several simple pieces (a single outline folds
    # over itself when the wing is raised, which erased most of the wing).
    pieces = [
        [shoulder, elbow, hip],
        [elbow, wrist, hip],
        [wrist, tips[2], notch(tips[2], hip), hip],
        [wrist, tips[0], notch(tips[0], tips[1]), tips[1],
         notch(tips[1], tips[2]), tips[2]],
    ]
    bones = [(shoulder, elbow, 3.2), (elbow, wrist, 2.6)] + [(wrist, tp, 1.8) for tp in tips]
    return pieces, bones, tips


def mirror(points):
    return [(-x, y) for x, y in points]


def draw_wings(grid, phi, x0, y0, val, with_bones=True):
    pieces, bones, tips = wing_shape(phi)
    for piece in pieces:
        fill_poly(grid, piece, val, x0, y0)
        fill_poly(grid, mirror(piece), val, x0, y0)
    if with_bones:
        for p, q, w in bones:
            fill_poly(grid, thick_line(p, q, w), val, x0, y0)
            fill_poly(grid, thick_line((-p[0], p[1]), (-q[0], q[1]), w), val, x0, y0)
    return tips


def draw_body(grid, phi, x0, y0):
    squash = 0.9 * math.cos(phi)
    fill_poly(grid, ellipse(0, 1.5, 5.2, 8.0 + squash), 1, x0, y0)       # torso
    fill_poly(grid, ellipse(0, -9.0, 5.0, 4.5), 1, x0, y0)               # head
    ear = [(-4.6, -11.5), (-5.9, -19.5), (-1.2, -13.5)]
    fill_poly(grid, ear, 1, x0, y0)
    fill_poly(grid, mirror(ear), 1, x0, y0)
    fill_poly(grid, [(-2.8, 8), (-2.4, 11.5), (-1.2, 9)], 1, x0, y0)     # feet
    fill_poly(grid, [(2.8, 8), (2.4, 11.5), (1.2, 9)], 1, x0, y0)


def draw_blobs(grid, t, phi, x0, y0):
    swell = 1.0 + 0.28 * max(0.0, math.sin(phi))
    for k, (ox, oy, w, ph, size) in enumerate(BLOBS):
        a = w * t + ph
        bx = x0 + 0.88 * ox * math.cos(a)
        by = y0 + 0.88 * oy * math.sin(a) - 2
        r = size * swell * (1 + 0.12 * math.sin(3 * t + k))
        fill_poly(grid, ellipse(0, 0, r, r * 0.92, 14), 1, bx, by)


def roughen(mass, tick):
    """Wet-ink edges: nudge the ends of every horizontal run by a cell."""
    out = [bytearray(GRID_W) for _ in range(GRID_H)]
    for r in range(GRID_H):
        row = mass[r]
        if not any(row):
            continue
        c = 0
        while c < GRID_W:
            if row[c]:
                s = c
                while c < GRID_W and row[c]:
                    c += 1
                e = c
                if e - s >= 3:
                    js = noise(r, s, tick, 1) % 6
                    je = noise(r, e, tick, 2) % 6
                    s += -1 if js == 0 else (1 if js == 1 else 0)
                    e += -1 if je == 0 else (1 if je == 1 else 0)
                    s, e = max(0, s), min(GRID_W, e)
                if e > s:
                    out[r][s:e] = b"\x01" * (e - s)
            else:
                c += 1
    return out


# --------------------------------------------------------- particles & rings
class World:
    def __init__(self):
        self.rng = random.Random(3)
        self.parts = []          # sparks, specks, crosses
        self.rings = []          # shockwaves: start times
        self.cycle = -1
        self.shake_until = 0.0
        self.last_t = None
        self.blink_at = 1.6

    def spawn(self, kind, x, y, vx, vy, life):
        self.parts.append({"k": kind, "x": x, "y": y, "vx": vx, "vy": vy,
                           "life": life, "age": 0.0})

    def update(self, t, phi, tips, x0, y0):
        dt = 0.0 if self.last_t is None else min(0.1, t - self.last_t)
        self.last_t = t
        rng = self.rng

        # bottom of every downstroke: sparks + shockwave + shake
        cyc = math.floor((phi + 1.5 * math.pi) / (2 * math.pi))
        if cyc != self.cycle:
            if self.cycle != -1:
                for side in (1, -1):
                    tx = x0 + side * tips[1][0]
                    ty = y0 + tips[1][1]
                    for _ in range(BURST_SPARKS):
                        self.spawn(rng.choice(("dot", "dash", "dot")), tx, ty,
                                   side * rng.uniform(8, 26), rng.uniform(-6, 20),
                                   rng.uniform(0.5, 1.0))
                self.rings.append(t)
                self.shake_until = t + 0.12
            self.cycle = cyc

        # ambient embers and drifting plus signs
        if rng.random() < IDLE_SPECKS_PER_SEC * dt:
            a = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(18, 38)
            self.spawn(rng.choice(("dot", "dash")), x0 + r * math.cos(a),
                       y0 + r * math.sin(a) * 0.75, rng.uniform(-3, 3),
                       rng.uniform(-4, 1), rng.uniform(0.7, 1.4))
        if rng.random() < CROSSES_PER_SEC * dt:
            a = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(26, 40)
            self.spawn("cross", x0 + r * math.cos(a), y0 + r * math.sin(a) * 0.7,
                       rng.uniform(-2, 2), rng.uniform(-3, 1), rng.uniform(1.0, 1.8))

        for p in self.parts:
            p["age"] += dt
            drag = max(0.0, 1.0 - 1.8 * dt)
            p["vx"] *= drag
            p["vy"] = p["vy"] * drag + 6.0 * dt * (1 if p["k"] != "cross" else 0)
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
        self.parts = [p for p in self.parts if p["age"] < p["life"]]
        self.rings = [r for r in self.rings if t - r < 0.7]

    def blinking(self, t):
        if t > self.blink_at:
            if t > self.blink_at + 0.14:
                self.blink_at = t + self.rng.uniform(1.8, 3.6)
            return True
        return False


def fade_code(p):
    f = p["age"] / p["life"]
    return 1 if f < 0.55 else (5 if f < 0.8 else 6)


# -------------------------------------------------------------- one frame
def render(t, world):
    phi, x0, y0 = pose(t)
    if t < world.shake_until:
        r = world.rng
        x0 += r.choice((-1, 0, 1))
        y0 += r.choice((-1, 0, 1))
    ix, iy = int(round(x0)), int(round(y0))

    grid = [bytearray(GRID_W) for _ in range(GRID_H)]

    # shockwave rings (back layer)
    for start in (world.rings if SHOW_SHOCKWAVE else ()):
        age = t - start
        radius = 8 + 70 * age
        code = 3 if age < 0.4 else 4
        for k in range(0, 360, 3):
            a = math.radians(k)
            put(grid, x0 + radius * math.cos(a), y0 + radius * 0.72 * math.sin(a), code)

    # afterimage trails of the wings
    for lag, code in (((TRAIL_LAG[1], 4), (TRAIL_LAG[0], 3)) if SHOW_TRAILS else ()):
        p2, tx0, ty0 = pose(t - lag)
        draw_wings(grid, p2, x0 + (tx0 - pose(t)[1]), y0 + (ty0 - pose(t)[2]), code, False)

    # the ink itself
    mass = [bytearray(GRID_W) for _ in range(GRID_H)]
    tips = draw_wings(mass, phi, x0, y0, 1)
    draw_body(mass, phi, x0, y0)
    draw_blobs(mass, t, phi, x0, y0)
    mass = roughen(mass, int(t * EDGE_BOIL_HZ))
    for r in range(GRID_H):
        row, mrow = grid[r], mass[r]
        if any(mrow):
            for c in range(GRID_W):
                if mrow[c]:
                    row[c] = 1

    # particles, sparks, plus signs
    world.update(t, phi, tips, x0, y0)
    for p in world.parts:
        code = fade_code(p)
        x, y = p["x"], p["y"]
        if p["k"] == "dot":
            put(grid, x, y, code)
        elif p["k"] == "dash":
            put(grid, x, y, code)
            put(grid, x + 1, y, code)
        else:
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                put(grid, x + dx, y + dy, code)

    # face: mouth opens on the downstroke, eyes blink now and then
    open_mouth = 3 if math.sin(phi) > 0.35 else 2
    for r in range(iy - 6, iy - 6 + open_mouth):
        for c in range(ix - 2, ix + 2):
            put(grid, c, r, 0)
    top_row = iy - 11
    eye_rows = (iy - 10,) if world.blinking(t) else (top_row, iy - 10)
    for r in eye_rows:
        for c in (ix - 4, ix - 3, ix + 2, ix + 3):
            put(grid, c, r, 2)
    return grid


# ------------------------------------------------------- grid -> Tk image
PAT = [None] * 7
GAPPAT = [None] * 7
for _code, _col in PALETTE.items():
    PAT[_code] = bytes(_col) * (CELL - 1) + bytes(GAP[_code])
    GAPPAT[_code] = bytes(GAP[_code]) * CELL
HEADER = b"P6 %d %d 255\n" % (GRID_W * CELL, GRID_H * CELL)


def to_ppm(grid):
    out = [HEADER]
    for row in grid:
        line = b"".join([PAT[c] for c in row])
        gap = b"".join([GAPPAT[c] for c in row])
        out.append(line * (CELL - 1) + gap)
    return b"".join(out)


def main():
    root = tk.Tk()
    root.title("bat")
    root.resizable(False, False)
    bg_hex = "#%02x%02x%02x" % BG
    root.configure(bg=bg_hex)
    label = tk.Label(root, bd=0, highlightthickness=0, bg=bg_hex)
    label.pack()

    world = World()
    start = time.time()
    interval = 1.0 / FPS

    def tick():
        began = time.time()
        grid = render(began - start, world)
        photo = tk.PhotoImage(data=to_ppm(grid), format="PPM")
        label.configure(image=photo)
        label.image = photo                     # keep a reference
        spent = time.time() - began
        root.after(max(1, int((interval - spent) * 1000)), tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
