"""
RegistrationBot — greendotball.com async Playwright automation.

Verified selectors (inspected 2026-04-15):
  Phone  : #phoneInput   (type="tel", maxlength=10, digits only)
  Image  : #imageInput   (type="file", hidden, multiple, accepts image/*)
  Terms  : #termsCheckbox
  Submit : drag #knob inside #slider from left edge to right edge
  API    : POST https://greendotball.com/api/submit.php
           FormData keys: phone, image, utm_source, …

Dry-run mode:
    python register.py --dry-run --phone 9876543210 --image path/to/img.jpg
    Prints every action without touching the network form endpoint.

Live mode:
    python register.py --phone 9876543210 --image path/to/img.jpg
"""

import asyncio
import os
from typing import Dict, Optional

from playwright.async_api import (
    Page,
    BrowserContext,
    TimeoutError as PWTimeout,
    async_playwright,
)

# ── Configuration ──────────────────────────────────────────────────────────────

REGISTRATION_URL = "https://greendotball.com/?utm_source=ViralFission&utm_medium=VF95"

# Confirmed selectors — do NOT change without re-running inspection
PHONE_SELECTOR   = "#phoneInput"
IMAGE_SELECTOR   = "#imageInput"
TERMS_SELECTOR   = "#termsCheckbox"
SLIDER_SELECTOR  = "#slider"
KNOB_SELECTOR    = "#knob"

# Modal selectors used to detect outcome
MODAL_SELECTOR   = "#successModal"
MODAL_TITLE_SEL  = "#successModal .modal-title"

# Realistic Chrome UA — required to avoid 403 from the CDN WAF
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DELAY_BETWEEN_ATTEMPTS: float = 2.0    # seconds
DEFAULT_TIMEOUT: int           = 20_000  # ms


# ── Bot ────────────────────────────────────────────────────────────────────────

class RegistrationBot:
    """
    Async Playwright bot that fills and submits the greendotball.com entry form.

    Usage::

        bot = RegistrationBot(dry_run=True)          # inspection / verification
        result = await bot.register("9876543210", "photo.jpg")
        # → {"status": "success" | "failed", "message": "..."}

        bot = RegistrationBot(dry_run=False)          # live run
        results = await bot.register_batch([
            ("9876543210", "img1.jpg"),
            ("9123456780", "img2.jpg"),
        ])
    """

    def __init__(self, headless: bool = True, dry_run: bool = False):
        self.headless = headless
        self.dry_run  = dry_run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register(self, phone: str, image_path: str) -> Dict[str, str]:
        """
        Perform one registration attempt.

        Args:
            phone:      10-digit Indian mobile number (digits only, no +91).
            image_path: Absolute or relative path to the image file.

        Returns:
            {"status": "success" | "failed", "message": "<detail>"}
        """
        await asyncio.sleep(DELAY_BETWEEN_ATTEMPTS)

        if self.dry_run:
            return self._dry_run_result(phone, image_path)

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                ctx = await self._create_context(browser)
                page = await ctx.new_page()
                result = await self._run_registration(page, phone, image_path)
                await browser.close()
            return result
        except Exception as exc:
            return {"status": "failed", "message": f"Unexpected error: {exc}"}

    async def register_batch(self, entries: list) -> list:
        """
        Run register() for each (phone, image_path) tuple sequentially.

        Returns a list of result dicts, each augmented with 'phone' and
        'image_path' keys for easy logging.
        """
        results = []
        for phone, image_path in entries:
            result = await self.register(phone, image_path)
            result["phone"]      = phone
            result["image_path"] = image_path
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Browser context — UA spoofing to avoid CDN 403
    # ------------------------------------------------------------------

    async def _create_context(self, browser) -> BrowserContext:
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Remove the navigator.webdriver fingerprint
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return ctx

    # ------------------------------------------------------------------
    # Core automation
    # ------------------------------------------------------------------

    async def _run_registration(
        self, page: Page, phone: str, image_path: str
    ) -> Dict[str, str]:

        # ── 1. Navigate ────────────────────────────────────────────────
        try:
            resp = await page.goto(
                REGISTRATION_URL,
                wait_until="domcontentloaded",
                timeout=DEFAULT_TIMEOUT,
            )
            if resp and resp.status >= 400:
                return {
                    "status":  "failed",
                    "message": f"Page returned HTTP {resp.status}",
                }
            # Let JS finish rendering
            await page.wait_for_timeout(2000)
        except PWTimeout:
            return {"status": "failed", "message": "Page load timed out"}
        except Exception as exc:
            return {"status": "failed", "message": f"Navigation error: {exc}"}

        # ── 2. Fill phone number ───────────────────────────────────────
        try:
            await page.wait_for_selector(PHONE_SELECTOR, timeout=DEFAULT_TIMEOUT)
            # The site strips non-digits via JS; send digits only
            digits = "".join(c for c in phone if c.isdigit())[-10:]
            await page.fill(PHONE_SELECTOR, digits)
        except PWTimeout:
            return {
                "status":  "failed",
                "message": f"Phone field not found: {PHONE_SELECTOR!r}",
            }

        # ── 3. Upload image (hidden input — set files directly) ────────
        # #imageInput has display:none — wait for it to be attached to the DOM
        # (not visible), then set files directly via Playwright's file-input API.
        try:
            await page.wait_for_selector(IMAGE_SELECTOR, state="attached", timeout=DEFAULT_TIMEOUT)
            await page.set_input_files(IMAGE_SELECTOR, image_path)
            # Allow the change-event listener to mark fileUploaded = true
            await page.wait_for_timeout(500)
        except PWTimeout:
            return {
                "status":  "failed",
                "message": f"Image upload field not found: {IMAGE_SELECTOR!r}",
            }
        except Exception as exc:
            return {"status": "failed", "message": f"Image upload error: {exc}"}

        # ── 4. Accept terms & conditions ───────────────────────────────
        try:
            await page.wait_for_selector(TERMS_SELECTOR, timeout=DEFAULT_TIMEOUT)
            await page.check(TERMS_SELECTOR)
        except PWTimeout:
            return {
                "status":  "failed",
                "message": f"Terms checkbox not found: {TERMS_SELECTOR!r}",
            }

        # ── 5. Drag slider knob to submit ──────────────────────────────
        try:
            result = await self._drag_slider(page)
            if result:
                return result          # drag itself failed
        except Exception as exc:
            return {"status": "failed", "message": f"Slider drag error: {exc}"}

        # ── 6. Wait for modal / network response ───────────────────────
        try:
            # Wait for the success modal to become active
            await page.wait_for_selector(
                f"{MODAL_SELECTOR}.active", timeout=DEFAULT_TIMEOUT
            )
        except PWTimeout:
            # Modal never appeared — inspect raw content as fallback
            return self._detect_outcome_from_html(await page.content(), page.url)

        # ── 7. Read modal title to determine success vs error ──────────
        return await self._detect_outcome_from_modal(page)

    async def _drag_slider(self, page: Page) -> Optional[Dict[str, str]]:
        """
        Simulate a pointer-drag from the left side of #knob to the right
        end of #slider.  Uses the Pointer Events API (same as the real JS).

        Returns None on success, or a failure dict if the elements are missing.
        """
        slider_box = await page.locator(SLIDER_SELECTOR).bounding_box()
        knob_box   = await page.locator(KNOB_SELECTOR).bounding_box()

        if not slider_box or not knob_box:
            return {
                "status":  "failed",
                "message": "Slider or knob element not found / not visible",
            }

        # Start: centre of the knob
        start_x = knob_box["x"] + knob_box["width"] / 2
        start_y = knob_box["y"] + knob_box["height"] / 2

        # End: right side of slider minus a small margin (mirrors the JS maxX logic)
        end_x = slider_box["x"] + slider_box["width"] - knob_box["width"] / 2 - 8
        end_y = start_y

        await page.mouse.move(start_x, start_y)
        await page.mouse.down()

        # Smooth drag in small increments so event listeners fire correctly
        steps = 30
        for i in range(1, steps + 1):
            x = start_x + (end_x - start_x) * i / steps
            await page.mouse.move(x, end_y)
            await page.wait_for_timeout(10)   # ~300 ms total drag duration

        await page.mouse.up()
        return None

    # ------------------------------------------------------------------
    # Outcome detection
    # ------------------------------------------------------------------

    async def _detect_outcome_from_modal(self, page: Page) -> Dict[str, str]:
        """Read the modal title to distinguish success from error."""
        try:
            title_el = await page.query_selector(MODAL_TITLE_SEL)
            title    = (await title_el.inner_text()).strip() if title_el else ""
        except Exception:
            title = ""

        try:
            msg_el  = await page.query_selector(f"{MODAL_SELECTOR} .modal-message")
            message = (await msg_el.inner_text()).strip() if msg_el else ""
        except Exception:
            message = ""

        if title.lower() == "success!":
            return {"status": "success", "message": message or "Registered successfully"}
        if title.lower() == "oops!":
            return {"status": "failed", "message": message or "Server returned an error"}

        # Unknown modal state — fall back to text scan
        return self._detect_outcome_from_html(await page.content(), page.url)

    def _detect_outcome_from_html(
        self, html: str, final_url: str
    ) -> Dict[str, str]:
        """Keyword scan fallback when modal state is ambiguous."""
        lower = html.lower()
        success_kw = ["success", "registered", "thank you", "confirmed", "entry received"]
        error_kw   = ["oops", "error", "invalid", "failed", "already registered"]

        for kw in success_kw:
            if kw in lower:
                return {"status": "success", "message": f"Keyword {kw!r} found in page"}

        for kw in error_kw:
            if kw in lower:
                return {"status": "failed", "message": f"Keyword {kw!r} found in page"}

        return {
            "status":  "failed",
            "message": "No recognisable outcome indicator found in page",
        }

    # ------------------------------------------------------------------
    # Dry-run — prints what the bot WOULD do, nothing is submitted
    # ------------------------------------------------------------------

    def _dry_run_result(self, phone: str, image_path: str) -> Dict[str, str]:
        digits = "".join(c for c in phone if c.isdigit())[-10:]

        print()
        print("╔══════════════════════════════════════════════════════╗")
        print("║              DRY-RUN  —  no submission               ║")
        print("╠══════════════════════════════════════════════════════╣")
        print(f"║  URL          : {REGISTRATION_URL}")
        print(f"║  Phone field  : {PHONE_SELECTOR}")
        print(f"║               → value: {digits!r}  (stripped to 10 digits)")
        print(f"║  Image field  : {IMAGE_SELECTOR}  (hidden, set via set_input_files)")
        print(f"║               → file : {image_path!r}")
        print(f"║  File exists  : {os.path.isfile(image_path)}")
        print(f"║  Terms check  : {TERMS_SELECTOR}  → will be checked")
        print(f"║  Submit       : drag {KNOB_SELECTOR} inside {SLIDER_SELECTOR} to right end")
        print(f"║  Success cue  : {MODAL_SELECTOR}.active  + .modal-title == 'Success!'")
        print(f"║  Error cue    : {MODAL_SELECTOR}.active  + .modal-title == 'Oops!'")
        print(f"║  Delay        : {DELAY_BETWEEN_ATTEMPTS}s between attempts")
        print(f"║  User-Agent   : {_USER_AGENT[:55]}…")
        print("╚══════════════════════════════════════════════════════╝")
        print()
        return {"status": "success", "message": "Dry-run — form was NOT submitted"}


# ── CLI entry-point ────────────────────────────────────────────────────────────

async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="greendotball.com RegistrationBot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Dry-run (verify selectors):\n"
            "    python register.py --dry-run --phone 9876543210 --image img.jpg\n\n"
            "  Live single registration:\n"
            "    python register.py --phone 9876543210 --image img.jpg\n\n"
            "  Live, visible browser window:\n"
            "    python register.py --no-headless --phone 9876543210 --image img.jpg\n"
        ),
    )
    parser.add_argument("--phone",       default="9876543210",
                        help="10-digit phone number (default: 9876543210)")
    parser.add_argument("--image",       default="images/image_1.png",
                        help="Path to image file (default: images/image_1.png)")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print actions without submitting")
    parser.add_argument("--no-headless", action="store_true",
                        help="Show the browser window (useful for debugging)")
    args = parser.parse_args()

    bot    = RegistrationBot(headless=not args.no_headless, dry_run=args.dry_run)
    result = await bot.register(args.phone, args.image)
    print("Result:", result)


if __name__ == "__main__":
    asyncio.run(_main())
