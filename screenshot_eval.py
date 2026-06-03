#!/usr/bin/env python3
"""Playwright screenshot evaluation script for SIMA UI."""
import asyncio
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8010"
OUTPUT_DIR = "output/playwright/ui_eval"

PAGES = [
    ("/", "landing"),
    ("/login/", "login"),
    ("/dashboard/", "dashboard"),
]

async def take_screenshots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # Login first
        await page.goto(f"{BASE_URL}/login/")
        await page.fill('input[name="username"]', "testplaywright")
        await page.fill('input[name="password"]', "test12345")
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)

        # Find a lesson job to screenshot
        await page.goto(f"{BASE_URL}/dashboard/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)

        # Try to click on first lesson
        try:
            # First click "Abrir curso" to enter the course
            course_btn = await page.query_selector("a:has-text('Abrir curso')")
            if course_btn:
                await course_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)

            # Then find a lesson link
            lesson_link = await page.query_selector("a[href^='/clase/']")
            if lesson_link:
                await lesson_link.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)

                # Screenshot lesson detail (light)
                await page.screenshot(path=f"{OUTPUT_DIR}/lesson_detail_light.png", full_page=True)
                print(f"Saved: {OUTPUT_DIR}/lesson_detail_light.png")

                # Try pipeline viz
                try:
                    pipeline_link = await page.query_selector("a[href*='/pipeline/']")
                    if pipeline_link:
                        await pipeline_link.click()
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(2)
                        await page.screenshot(path=f"{OUTPUT_DIR}/pipeline_viz_light.png", full_page=True)
                        print(f"Saved: {OUTPUT_DIR}/pipeline_viz_light.png")
                except Exception as e:
                    print(f"Pipeline viz error: {e}")

                # Switch to dark mode
                await page.evaluate("""() => {
                    document.documentElement.setAttribute('data-theme', 'dark');
                    localStorage.setItem('sima-theme', 'dark');
                }""")
                await asyncio.sleep(1)
                await page.screenshot(path=f"{OUTPUT_DIR}/pipeline_viz_dark.png", full_page=True)
                print(f"Saved: {OUTPUT_DIR}/pipeline_viz_dark.png")

                # Go back to lesson detail (dark)
                await page.goto(page.url.replace('/pipeline/', '/'))
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)
                await page.screenshot(path=f"{OUTPUT_DIR}/lesson_detail_dark.png", full_page=True)
                print(f"Saved: {OUTPUT_DIR}/lesson_detail_dark.png")

                # Dashboard dark
                await page.goto(f"{BASE_URL}/dashboard/")
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(1)
                await page.screenshot(path=f"{OUTPUT_DIR}/dashboard_dark.png", full_page=True)
                print(f"Saved: {OUTPUT_DIR}/dashboard_dark.png")

                # Switch back to light for dashboard
                await page.evaluate("""() => {
                    document.documentElement.removeAttribute('data-theme');
                    localStorage.setItem('sima-theme', 'light');
                }""")
                await asyncio.sleep(1)
                await page.screenshot(path=f"{OUTPUT_DIR}/dashboard_light.png", full_page=True)
                print(f"Saved: {OUTPUT_DIR}/dashboard_light.png")
        except Exception as e:
            print(f"Lesson detail error: {e}")
            # Fallback: screenshot dashboard
            await page.screenshot(path=f"{OUTPUT_DIR}/dashboard_light.png", full_page=True)
            print(f"Saved: {OUTPUT_DIR}/dashboard_light.png")

        # Landing page (no login needed)
        await page.goto(f"{BASE_URL}/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        await page.screenshot(path=f"{OUTPUT_DIR}/landing_light.png", full_page=True)
        print(f"Saved: {OUTPUT_DIR}/landing_light.png")

        await page.evaluate("""() => {
            document.documentElement.setAttribute('data-theme', 'dark');
        }""")
        await asyncio.sleep(1)
        await page.screenshot(path=f"{OUTPUT_DIR}/landing_dark.png", full_page=True)
        print(f"Saved: {OUTPUT_DIR}/landing_dark.png")

        await browser.close()
        print("All screenshots captured!")

if __name__ == "__main__":
    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    asyncio.run(take_screenshots())
