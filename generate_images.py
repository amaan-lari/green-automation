import math
import os
import random
import shutil
from typing import List

from PIL import Image, ImageDraw, ImageFilter

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_circle_mask(size: int, cx: int, cy: int, radius: int) -> Image.Image:
    """White inside the circle, black outside — used for clipping."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius], fill=255
    )
    return mask


def _add_sphere_overlay(
    img: Image.Image, cx: int, cy: int, radius: int, rng: random.Random
) -> Image.Image:
    """
    Composite a 3-D-looking overlay on top of any flat pattern:
      • limb darkening  — dark ring at the circle edge
      • specular highlight — small bright spot near the top
    """
    SIZE = img.width
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # Limb darkening: rings from edge inward, fading to transparent
    for step in range(22):
        t = step / 22                           # 0 = outermost, 1 = inner
        r = int(radius * (1.0 - t * 0.20))
        alpha = int(80 * (1.0 - t) ** 2)       # strong at edge, fades fast
        d.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(0, 15, 0, alpha),
            width=max(2, radius // 12),
        )

    # Specular highlight: soft white blob near the top
    hx = cx + rng.randint(-radius // 3, radius // 4)
    hy = cy - rng.randint(radius // 6, radius // 2)
    hr = int(radius * rng.uniform(0.13, 0.30))
    for i in range(hr, 0, -1):
        a = int(110 * (1.0 - i / hr) ** 0.55)
        d.ellipse([hx - i, hy - i, hx + i, hy + i], fill=(255, 255, 255, a))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ── Style draw functions ───────────────────────────────────────────────────────
# Each function draws directly onto `draw` (the ImageDraw for `img`).
# They may reach radius pixels outside cx/cy — that's fine because we clip
# the whole canvas to a circle mask afterwards.

def _draw_smooth_sphere(draw, cx, cy, radius, rng, R, G, B):
    """Radial gradient: dark at the edge, bright near the offset highlight."""
    hl_x = rng.randint(-radius // 3, radius // 3)
    hl_y = rng.randint(-radius // 2, -radius // 8)
    for i in range(100, 0, -1):
        t = i / 100
        r = max(1, int(radius * t))
        brightness = 0.38 + 0.72 * (1.0 - t)
        rc = min(255, int(R * brightness))
        gc = min(255, int(G * brightness))
        bc = min(255, int(B * brightness))
        ox = int(hl_x * (1 - t) * 0.45)
        oy = int(hl_y * (1 - t) * 0.45)
        draw.ellipse([cx - r + ox, cy - r + oy, cx + r + ox, cy + r + oy], fill=(rc, gc, bc))


def _draw_concentric_rings(draw, cx, cy, radius, rng, R, G, B):
    """Alternating light / dark concentric rings — bullseye / onion look."""
    n = rng.randint(5, 11)
    for i in range(n, 0, -1):
        t = i / n
        r = max(1, int(radius * t))
        # odd rings brighter, even rings darker
        f = 1.25 if i % 2 == 0 else 0.60
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
        )
    # Thin dividing lines between rings
    for i in range(1, n):
        r = max(1, int(radius * i / n))
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(max(0, R - 30), max(0, G - 60), max(0, B - 30)),
            width=2,
        )


def _draw_spots(draw, cx, cy, radius, rng, R, G, B):
    """Solid base colour with large irregular spots — mossy / spotted ball."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(R, G, B))
    n = rng.randint(7, 16)
    for _ in range(n):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius * 0.78)
        sx = int(cx + dist * math.cos(angle))
        sy = int(cy + dist * math.sin(angle))
        sr = rng.randint(max(4, radius // 10), max(6, radius // 5))
        f = rng.uniform(0.45, 1.55)
        draw.ellipse(
            [sx - sr, sy - sr, sx + sr, sy + sr],
            fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
        )


def _draw_radial_stripes(draw, cx, cy, radius, rng, R, G, B):
    """Pie-wedge segments with alternating shades — beach-ball / citrus look."""
    n = rng.randint(3, 7) * 2      # even so stripes alternate cleanly
    step = 360.0 / n
    offset = rng.uniform(0, 360)
    for i in range(n):
        a0 = offset + i * step
        a1 = offset + (i + 1) * step
        f = 1.25 if i % 2 == 0 else 0.60
        draw.pieslice(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            start=a0,
            end=a1,
            fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
        )


def _draw_mossy_patches(draw, cx, cy, radius, rng, R, G, B):
    """Many overlapping irregular blobs — moss / lichen / camouflage texture."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(R, G, B))
    n = rng.randint(22, 48)
    for _ in range(n):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius * 0.85)
        px = int(cx + dist * math.cos(angle))
        py = int(cy + dist * math.sin(angle))
        pw = rng.randint(radius // 10, radius // 4)
        ph = rng.randint(radius // 10, radius // 4)
        f = rng.uniform(0.50, 1.50)
        draw.ellipse(
            [px - pw, py - ph, px + pw, py + ph],
            fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
        )


def _draw_speckled(draw, cx, cy, radius, rng, R, G, B):
    """Gradient base covered in tiny dots — speckled / grainy texture."""
    # Start with the smooth gradient so the sphere depth is there
    _draw_smooth_sphere(draw, cx, cy, radius, rng, R, G, B)
    # Overlay many small circles of varying shade
    n = rng.randint(180, 450)
    for _ in range(n):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius * 0.90)
        px = int(cx + dist * math.cos(angle))
        py = int(cy + dist * math.sin(angle))
        sr = rng.randint(2, max(3, radius // 16))
        f = rng.uniform(0.45, 1.55)
        draw.ellipse(
            [px - sr, py - sr, px + sr, py + sr],
            fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
        )


def _draw_honeycomb(draw, cx, cy, radius, rng, R, G, B):
    """Hexagonal honeycomb grid — each cell a slightly different shade."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(R, G, B))
    hex_r = rng.randint(radius // 8, radius // 5)
    col_step = max(1, int(hex_r * 1.732))   # sqrt(3) × hex_r
    row_step = max(1, int(hex_r * 1.5))

    for row in range(-radius // row_step - 1, radius // row_step + 2):
        for col in range(-radius // col_step - 1, radius // col_step + 2):
            hx = cx + col * col_step + (row % 2) * col_step // 2
            hy = cy + row * row_step
            points = [
                (hx + hex_r * math.cos(math.radians(60 * i - 30)),
                 hy + hex_r * math.sin(math.radians(60 * i - 30)))
                for i in range(6)
            ]
            f = rng.uniform(0.60, 1.40)
            draw.polygon(
                points,
                fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
            )
            draw.polygon(
                points,
                outline=(max(0, R - 40), max(0, G - 60), max(0, B - 40)),
            )


def _draw_spiral(draw, cx, cy, radius, rng, R, G, B):
    """Spiral arms that wind outward from the centre."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(R, G, B))
    arms = rng.randint(3, 7)
    turns = rng.uniform(1.5, 3.0)
    steps = 300
    arm_width = max(2, radius // 10)

    for arm in range(arms):
        arm_offset = (2 * math.pi * arm) / arms
        points = []
        for step in range(steps):
            t = step / steps
            r = t * radius * 0.92
            angle = arm_offset + t * turns * 2 * math.pi
            points.append((int(cx + r * math.cos(angle)), int(cy + r * math.sin(angle))))
        f = rng.uniform(0.50, 0.80) if arm % 2 == 0 else rng.uniform(1.20, 1.50)
        color = (min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f)))
        if len(points) > 1:
            draw.line(points, fill=color, width=arm_width)


def _draw_grid_squares(draw, cx, cy, radius, rng, R, G, B):
    """Checkerboard-style grid with alternating light / dark cells."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(R, G, B))
    cell = rng.randint(radius // 7, radius // 4)

    for row in range(-radius // cell - 1, radius // cell + 2):
        for col in range(-radius // cell - 1, radius // cell + 2):
            x0 = cx + col * cell
            y0 = cy + row * cell
            f = 1.30 if (row + col) % 2 == 0 else 0.65
            draw.rectangle(
                [x0, y0, x0 + cell - 1, y0 + cell - 1],
                fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
            )


def _draw_marble_swirl(draw, cx, cy, radius, rng, R, G, B):
    """Marble-like swirling bands — sine-wave colour modulation across the disc."""
    freq = rng.uniform(6.0, 14.0)
    phase = rng.uniform(0.0, 2 * math.pi)
    twist = rng.uniform(1.5, 4.0)

    for py in range(cy - radius, cy + radius + 1):
        for px in range(cx - radius, cx + radius + 1):
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy > radius * radius:
                continue
            val = math.sin(freq * (dx / radius) + twist * (dy / radius) + phase)
            f = 0.50 + val * 0.50          # maps [-1, 1] → [0.0, 1.0]
            draw.point(
                (px, py),
                fill=(min(255, int(R * f)), min(255, int(G * f)), min(255, int(B * f))),
            )


_STYLES = [
    _draw_smooth_sphere,
    _draw_concentric_rings,
    _draw_spots,
    _draw_radial_stripes,
    _draw_mossy_patches,
    _draw_speckled,
    _draw_honeycomb,
    _draw_spiral,
    _draw_grid_squares,
    _draw_marble_swirl,
]


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_green_circle_image(filename: str) -> str:
    """
    Create a unique 200×200 green circle image.

    Each call:
      • uses OS-entropy for a fresh random seed (guaranteed uniqueness across runs)
      • picks one of 10 visual styles at random
      • varies the green hue within each style
      • adds sphere shading (limb-darkening + specular highlight) on top
      • adds texture noise and a soft Gaussian blur for an organic look
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # Fresh OS-entropy seed — no two calls produce the same image
    seed = int.from_bytes(os.urandom(8), "big")
    rng = random.Random(seed)

    SIZE = 400          # render at 2× then downsample for anti-aliased edges
    cx = cy = SIZE // 2
    radius = int(SIZE * 0.42)

    # Unique green shade per image (G dominant; R and B vary for warmth/coolness)
    R = rng.randint(10, 70)
    G = rng.randint(130, 220)
    B = rng.randint(10, 70)

    # Pick a random visual style
    style_fn = rng.choice(_STYLES)

    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    style_fn(draw, cx, cy, radius, rng, R, G, B)

    # Clip everything outside the circle to white
    mask = _make_circle_mask(SIZE, cx, cy, radius)
    white = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    img = Image.composite(img, white, mask)

    # Sphere shading overlay (3-D pop regardless of style)
    img = _add_sphere_overlay(img, cx, cy, radius, rng)

    # Fine texture noise inside the circle
    pixels = img.load()
    for _ in range(rng.randint(500, 1500)):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius * 0.92)
        px = int(cx + dist * math.cos(angle))
        py = int(cy + dist * math.sin(angle))
        if 0 <= px < SIZE and 0 <= py < SIZE:
            pr, pg, pb = pixels[px, py]
            n = rng.randint(-10, 10)
            pixels[px, py] = (
                max(0, min(255, pr + n)),
                max(0, min(255, pg + n)),
                max(0, min(255, pb + n)),
            )

    # Gaussian blur — softens edges and looks organic, not computer-sharp
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 2.0)))

    # Downsample 400→200 (also anti-aliases the circle boundary)
    img = img.resize((200, 200), Image.LANCZOS)

    filepath = os.path.join(IMAGES_DIR, filename)
    img.save(filepath)
    return filepath


def generate_images_batch(count: int) -> List[str]:
    """Generate `count` unique green-circle images named image_1.png … image_N.png."""
    return [generate_green_circle_image(f"image_{i + 1}.png") for i in range(count)]


def cleanup_images() -> None:
    """Delete the images folder and all its contents."""
    if os.path.exists(IMAGES_DIR):
        shutil.rmtree(IMAGES_DIR)
