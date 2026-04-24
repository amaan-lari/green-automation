import asyncio
from playwright.async_api import async_playwright


async def inspect_form():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        url = "https://greendotball.com/?utm_source=ViralFission&utm_medium=VF95"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")

        print("Waiting 10 seconds so you can see the page...\n")
        await asyncio.sleep(10)

        # Collect all input fields
        inputs = await page.query_selector_all("input, textarea, select")
        print("=" * 50)
        print(f"INPUT FIELDS FOUND: {len(inputs)}")
        print("=" * 50)
        for i, el in enumerate(inputs):
            name = await el.get_attribute("name") or ""
            id_ = await el.get_attribute("id") or ""
            type_ = await el.get_attribute("type") or ""
            placeholder = await el.get_attribute("placeholder") or ""
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            print(f"[{i+1}] tag={tag!r:10} name={name!r:20} id={id_!r:20} type={type_!r:15} placeholder={placeholder!r}")

        # Collect all form action URLs
        forms = await page.query_selector_all("form")
        print()
        print("=" * 50)
        print(f"FORMS FOUND: {len(forms)}")
        print("=" * 50)
        for i, form in enumerate(forms):
            action = await form.get_attribute("action") or "(no action)"
            method = await form.get_attribute("method") or "GET"
            id_ = await form.get_attribute("id") or ""
            cls = await form.get_attribute("class") or ""
            print(f"[{i+1}] action={action!r}  method={method!r}  id={id_!r}  class={cls!r}")

        # Screenshot
        screenshot_path = "form_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"\nScreenshot saved to: {screenshot_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(inspect_form())
