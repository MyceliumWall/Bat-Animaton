#!/usr/bin/env python3
"""
Ink-blot pixel bat, seen from the side, hunting a moth.  Pure Python +
tkinter (tkinter ships with Python, nothing to install).

    python ink_bat.py

The bat flies in profile, body pitched forward toward the prey, jaws snapping,
fangs bared, wings pumping with real joints (shoulder -> elbow -> wrist ->
fingers) that lag behind each other.  The wings foreshorten as they swing
through the middle of the stroke, the body bobs against them, and the whole
bat shakes a little at the bottom of every downstroke.  Edges "boil" like wet
ink, soot blobs orbit, and sparks and plus signs drift around it.

Settings are in the block below.  Close the window to quit.
"""

import math
import random
import time
import tkinter as tk

# ------------------------------------------------------------------ SETTINGS
CELL = 3                    # screen pixels per sprite pixel
GRID_W, GRID_H = 200, 148   # sprite pixels  (window = 600 x 444)
FPS = 30

FACING = 1                  # 1 = bat faces right, -1 = faces left
SHOW_PREY = True            # the moth being chased
FLAP_PERIOD = 0.55          # seconds per full wing beat (smaller = faster)
WING_SWING = 1.0            # 1.0 = default, 1.3 = wilder wings
BODY_BOB = 2.6              # how far the body rocks against the wings
SHOW_TRAILS = False         # faint afterimage copies that follow the wings
SHOW_SHOCKWAVE = False      # the dotted ring that expands each downstroke
TRAIL_LAG = (0.035, 0.07)   # seconds behind the wings for the afterimages
EDGE_BOIL_HZ = 14           # how fast the ragged ink edges re-roll
BURST_SPARKS = 6            # sparks thrown off the wings per downstroke
IDLE_SPECKS_PER_SEC = 7
CROSSES_PER_SEC = 0.9

# colors: 0 background, 1 ink, 2 eyes/fangs, 3/4 light trail, 5/6 fading ink
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


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


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


def rotate_about(p, pivot, ang):
    c, s = math.cos(ang), math.sin(ang)
    dx, dy = p[0] - pivot[0], p[1] - pivot[1]
    return (pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c)


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
# Body frame: +x is forward (toward the nose), +y is down, origin = body center.
def make_transform(pitch):
    """Body frame -> screen offsets: tilt nose-down by `pitch`, then face left/right."""
    c, s = math.cos(pitch), math.sin(pitch)

    def tf(p):
        return (FACING * (p[0] * c - p[1] * s), p[0] * s + p[1] * c)
    return tf


def paint(grid, poly, val, x0, y0, tf):
    fill_poly(grid, [tf(p) for p in poly], val, x0, y0)


def prey_pos(t, x0, y0):
    """The moth zigzags ahead of the bat."""
    px = x0 + FACING * (46 + 9 * math.sin(1.1 * t) + 3 * math.sin(2.9 * t))
    py = y0 + (-5 * math.sin(0.8 * t) + 4 * math.sin(2.3 * t + 1.0) + 2.5 * math.sin(5.1 * t))
    return px, py


def pose(t):
    """Everything that follows from the wing beat at time t."""
    phi = 2 * math.pi * t / FLAP_PERIOD
    x0 = CX - FACING * 14 + FACING * 5 * math.sin(0.6 * t)          # surges toward the prey
    y0 = CY + BODY_BOB * math.cos(phi) + 2.2 * math.sin(1.7 * t)
    py = prey_pos(t, x0, y0)[1] if SHOW_PREY else y0
    pitch = 0.20 + 0.012 * clamp(py - y0, -12, 12) + 0.05 * math.cos(phi)
    return phi, x0, y0, pitch


def wing_shape(phi, far=False):
    """One wing in the body frame: filled pieces, bones and fingertip positions."""
    s = WING_SWING
    if far:
        shoulder, k, phi = (2.0, -4.4), 0.92, phi - 0.4
    else:
        shoulder, k = (4.0, -3.6), 1.0
    a1 = math.radians(27 + 72 * s * math.cos(phi))             # upper arm: up ~100, down ~-45
    a2 = math.radians(27 + 78 * s * math.cos(phi - 0.7))       # forearm lags a little
    rear = math.tanh(2.5 * math.sin(a2))                       # fingers fan toward the tail
    lag = 22 * s * math.sin(phi - 0.7)                         # fingertips trail the stroke
    hip = (-7.0, 3.0)

    # seen from the side, a wing swinging through the middle of the stroke
    # points at the camera and looks shorter
    ws = (0.42 + 0.58 * abs(math.sin(a1))) * k

    def fit(p):
        x = shoulder[0] + (p[0] - shoulder[0]) * ws
        y = shoulder[1] + (p[1] - shoulder[1]) * ws
        if x > 13.0:                          # never let a wing poke out past the nose
            x = 13.0 + (x - 13.0) * 0.2
        return (x, y)

    elbow = add(shoulder, polar(a1, 11))
    wrist = add(elbow, polar(a2, 13))
    tips = []
    for i, (off, length) in enumerate(((28, 17), (58, 19), (88, 16))):
        ang = a2 + rear * math.radians(off) + math.radians(lag * (0.5 + 0.25 * i))
        tips.append(add(wrist, polar(ang, length)))
    elbow, wrist = fit(elbow), fit(wrist)
    tips = [fit(tp) for tp in tips]

    def notch(a, b):
        return lerp(lerp(a, b, 0.5), wrist, 0.36)

    # several simple pieces (one big outline folds over itself when the wing is raised)
    pieces = [
        [shoulder, elbow, hip],
        [elbow, wrist, hip],
        [wrist, tips[2], notch(tips[2], hip), hip],
        [wrist, tips[0], notch(tips[0], tips[1]), tips[1],
         notch(tips[1], tips[2]), tips[2]],
    ]
    bones = [(shoulder, elbow, 3.0), (elbow, wrist, 2.4)] + [(wrist, tp, 1.5) for tp in tips]
    return pieces, bones, tips


def draw_wing(grid, phi, x0, y0, tf, val, far=False, bones=True):
    pieces, bone_list, tips = wing_shape(phi, far)
    for piece in pieces:
        paint(grid, piece, val, x0, y0, tf)
    if bones:
        for p, q, w in bone_list:
            paint(grid, thick_line(p, q, w), val, x0, y0, tf)
    return [(x0 + tf(tp)[0], y0 + tf(tp)[1]) for tp in tips]


def jaw_angle(t, mouth_to_prey):
    """Jaws gape wider the closer the prey is, and snap at about 3 bites a second."""
    near = clamp((48 - mouth_to_prey) / 30, 0.0, 1.0)
    return 0.30 + 0.50 * near + 0.20 * math.sin(2 * math.pi * 3.2 * t)


JAW_PIVOT = (13.5, 1.4)


def draw_body(grid, phi, x0, y0, tf, jaw):
    paint(grid, ellipse(-1.0, 0.5, 11.0, 5.6), 1, x0, y0, tf)           # torso
    paint(grid, ellipse(5.0, -0.5, 6.0, 5.8), 1, x0, y0, tf)            # shoulders
    paint(grid, ellipse(12.5, -1.8, 5.6, 5.2), 1, x0, y0, tf)           # head
    paint(grid, [(14.0, -5.2), (23.0, -1.6), (23.6, 0.6), (13.5, 1.2)], 1, x0, y0, tf)   # snout
    lower = [(13.5, 1.4), (22.4, 1.7), (21.6, 3.8), (14.0, 4.8)]                          # lower jaw
    paint(grid, [rotate_about(p, JAW_PIVOT, jaw) for p in lower], 1, x0, y0, tf)
    paint(grid, [(9.5, -6.0), (5.5, -16.0), (13.5, -7.4)], 1, x0, y0, tf)               # ears
    paint(grid, [(12.0, -6.2), (9.0, -15.5), (15.2, -7.6)], 1, x0, y0, tf)
    paint(grid, [(-9.5, 2.0), (-19.0, 7.0), (-17.0, 9.5), (-8.5, 5.5)], 1, x0, y0, tf)  # tail membrane
    paint(grid, thick_line((-6.5, 4.5), (-12.5, 10.5), 2.0), 1, x0, y0, tf)             # hind legs
    paint(grid, thick_line((-8.5, 4.0), (-15.0, 9.0), 1.8), 1, x0, y0, tf)


def draw_fangs(grid, x0, y0, tf, jaw):
    paint(grid, [(20.0, 0.5), (21.6, 0.6), (20.8, 3.6)], 2, x0, y0, tf)
    lower = [rotate_about(p, JAW_PIVOT, jaw) for p in ((20.4, 1.9), (21.8, 1.9), (21.0, -1.0))]
    paint(grid, lower, 2, x0, y0, tf)


def draw_blobs(grid, t, phi, x0, y0):
    swell = 1.0 + 0.28 * max(0.0, math.sin(phi))
    for k, (ox, oy, w, ph, size) in enumerate(BLOBS):
        a = w * t + ph
        bx = x0 - FACING * 20 + 0.68 * ox * math.cos(a)
        by = y0 + 0.88 * oy * math.sin(a) - 2
        r = size * swell * (1 + 0.12 * math.sin(3 * t + k))
        fill_poly(grid, ellipse(0, 0, r, r * 0.92, 14), 1, bx, by)


def draw_moth(grid, t, px, py):
    """A tiny moth with fast fluttering wings."""
    fill_poly(grid, ellipse(0, 0, 2.4, 1.1, 10), 1, px, py)
    for phase, val in ((0.0, 1), (1.1, 5)):
        c = math.sin(2 * math.pi * 9 * t + phase)
        wing = [(0.8, -0.5), (-3.2, -0.5 - 4.8 * c), (-3.8, -0.5 - 1.2 * c)]
        fill_poly(grid, wing, val, px, py)
    put(grid, px + FACING * 3, py - 1.5, 5)                    # antennae
    put(grid, px + FACING * 4, py - 2.5, 5)


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

    def update(self, t, phi, wing_tips, x0, y0):
        dt = 0.0 if self.last_t is None else min(0.1, t - self.last_t)
        self.last_t = t
        rng = self.rng

        # mid-downstroke: sparks fly off the wingtips and the bat shakes
        cyc = math.floor((phi + 1.5 * math.pi) / (2 * math.pi))
        if cyc != self.cycle:
            if self.cycle != -1:
                for tx, ty in wing_tips:
                    for _ in range(BURST_SPARKS):
                        self.spawn(rng.choice(("dot", "dash", "dot")), tx, ty,
                                   -FACING * rng.uniform(8, 26), rng.uniform(-6, 20),
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
    phi, x0, y0, pitch = pose(t)
    if t < world.shake_until:
        r = world.rng
        x0 += r.choice((-1, 0, 1))
        y0 += r.choice((-1, 0, 1))
    tf = make_transform(pitch)
    prey = prey_pos(t, x0, y0)

    mx, my = tf((21.0, 1.0))
    dist = math.hypot(x0 + mx - prey[0], y0 + my - prey[1]) if SHOW_PREY else 99.0
    jaw = jaw_angle(t, dist)

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
        p2 = pose(t - lag)
        draw_wing(grid, p2[0], x0, y0, tf, code, bones=False)

    # the ink itself (far wing first so the near wing overlaps it)
    mass = [bytearray(GRID_W) for _ in range(GRID_H)]
    far_tips = draw_wing(mass, phi, x0, y0, tf, 1, far=True)
    near_tips = draw_wing(mass, phi, x0, y0, tf, 1)
    draw_body(mass, phi, x0, y0, tf, jaw)
    draw_blobs(mass, t, phi, x0, y0)
    mass = roughen(mass, int(t * EDGE_BOIL_HZ))
    for r in range(GRID_H):
        row, mrow = grid[r], mass[r]
        if any(mrow):
            for c in range(GRID_W):
                if mrow[c]:
                    row[c] = 1

    # particles, sparks, plus signs
    world.update(t, phi, [near_tips[1], far_tips[1]], x0, y0)
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

    # the prey
    if SHOW_PREY:
        draw_moth(grid, t, prey[0], prey[1])

    # face: fangs and one eye (blinks now and then)
    draw_fangs(grid, x0, y0, tf, jaw)
    ex, ey = tf((15.8, -3.6))
    ex, ey = int(math.floor(x0 + ex)), int(math.floor(y0 + ey))
    for dy in ((0,) if world.blinking(t) else (-1, 0)):
        for dx in (-1, 0):
            put(grid, ex + dx, ey + dy, 2)
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
