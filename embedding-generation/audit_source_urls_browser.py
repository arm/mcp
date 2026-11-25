# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.

"""Verify HTTP-blocked public pages in an isolated, unauthenticated browser."""

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def usable_page(url, final_url, title, body):
    """Reject error/login pages and known Arm application shells."""
    target = urlsplit(final_url)
    if (
        target.scheme not in {"http", "https"}
        or not title.strip()
        or len(body.strip()) < 100
    ):
        return False
    if re.search(r"/(login|signin|sign-in|oauth|authorize)(/|$)", target.path, re.I):
        return False
    if re.search(
        r"^(access denied|forbidden|just a moment|sign in|log in|login|404|403|page not found|verify you are human)\b",
        title.strip(),
        re.I,
    ):
        return False
    if re.search(
        r"access denied|verify you are human|checking your browser|page not found",
        body[:400],
        re.I,
    ):
        return False
    for source in (urlsplit(url), target):
        if source.hostname == "developer.arm.com" and source.path.startswith(
            "/documentation/"
        ):
            if title.strip().lower() in {
                "documentation",
                "documentation – arm developer",
                "documentation — arm developer",
                "documentation - arm developer",
            }:
                return False
        if source.hostname == "developer.arm.com" and source.path.startswith(
            "/ecosystem-dashboard/"
        ):
            if "package" in parse_qs(source.query) and not title.endswith(
                " - Ecosystem Dashboard for Arm"
            ):
                return False
    return True


async def verify_page(context, url, deadline):
    from playwright.async_api import Error

    page = await context.new_page()
    navigation = {}

    def record_response(response):
        if (
            response.request.is_navigation_request()
            and response.frame == page.main_frame
        ):
            navigation.update(http_status=response.status, final_url=response.url)

    page.on("response", record_response)
    expires = min(deadline, time.monotonic() + 25)
    try:
        remaining = max(1, (expires - time.monotonic()) * 1000)
        await page.goto(url, wait_until="domcontentloaded", timeout=remaining)
        while time.monotonic() < expires:
            code = navigation.get("http_status", 0)
            # JavaScript challenges can navigate from 403/503 to a usable page.
            if code >= 400 and code not in {403, 503}:
                return None
            try:
                title = await page.title()
                body = await page.locator("body").inner_text(
                    timeout=max(1, (expires - time.monotonic()) * 1000)
                )
                login = await page.locator('input[type="password"]:visible').count()
                code = navigation.get("http_status", 0)
                if (
                    200 <= code < 300
                    and not login
                    and usable_page(url, page.url, title, body)
                ):
                    return dict(
                        url=url, final_url=page.url, http_status=code, title=title
                    )
            except Error:
                pass  # A client-side redirect may replace the current document.
            await asyncio.sleep(0.25)
    except Error:
        pass  # A failed browser check cannot upgrade an uncertain HTTP result.
    finally:
        await page.close()
    return None


async def run(urls, output, budget_seconds, channel):
    from playwright.async_api import async_playwright

    deadline = time.monotonic() + budget_seconds
    pending = iter(urls)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, channel=channel)
        try:
            context = await browser.new_context()
            with output.open("w", encoding="utf-8") as handle:
                completed = 0

                async def worker():
                    nonlocal completed
                    while time.monotonic() < deadline:
                        url = next(pending, None)
                        if url is None:
                            return
                        await asyncio.sleep(1)
                        if time.monotonic() >= deadline:
                            return
                        result = await verify_page(context, url, deadline)
                        if result:
                            handle.write(json.dumps(result) + "\n")
                            handle.flush()
                        completed += 1
                        if completed % 100 == 0:
                            print(
                                f"Browser checked {completed}/{len(urls)} URLs",
                                flush=True,
                            )

                await asyncio.gather(*(worker() for _ in range(min(4, len(urls)))))
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget-seconds", type=float, required=True)
    parser.add_argument("--channel", default="chromium")
    args = parser.parse_args()
    asyncio.run(
        run(
            json.loads(args.input.read_text()),
            args.output,
            args.budget_seconds,
            args.channel,
        )
    )
