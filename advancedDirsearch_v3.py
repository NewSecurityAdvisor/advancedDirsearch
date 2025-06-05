import os
import re
import sys
import asyncio
import subprocess
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.prompt import Confirm
from playwright.async_api import async_playwright, Browser

MAX_CONCURRENT_SCREENSHOTS = 10
SCREENSHOT_TIMEOUT = 20000  # Milliseconds

console = Console()
CWD = Path.cwd()
TOP_LEVEL_OUTPUT_DIR = CWD / "output"
os.makedirs(TOP_LEVEL_OUTPUT_DIR, exist_ok=True)

STATUS_CODE_PRIORITY = {
    200: 1, 301: 2, 302: 2, 403: 3, 404: 4, 'default': 5
}


def sanitize_url_for_foldername(url: str) -> str:
    parsed = urlparse(url)
    return re.sub(r'[:.]', '_', parsed.netloc)

def sanitize_path_for_filename(path_str: str) -> str:
    # If path is empty or just a slash, it's the root/index.
    if not path_str or path_str == "/":
        return "index"

    clean_path = path_str.split('?')[0].strip('/')

    sanitized = clean_path.replace('/', '_')

    sanitized = re.sub(r'\.(php|html|htm|asp|aspx|jsp|txt)$', '', sanitized, flags=re.IGNORECASE)

    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', sanitized)

    return sanitized if sanitized else "page"


def run_dirsearch(url: str, extra_params: str, scan_dir: Path) -> Path:
    """Runs dirsearch and saves the output into the dedicated scan directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = scan_dir / f"dirsearch_report_{timestamp}.txt"
    cmd = ['dirsearch', '-u', url, '--output', str(output_file), '--full-url'] + extra_params.split()

    console.print(f"[green]Starting Dirsearch for URL: {url}[/green]")
    console.print(f"[grey50]Command: {' '.join(cmd)}[/grey50]\n")
    try:
        subprocess.run(cmd, check=True)
        console.print(f"\n[bold green]Dirsearch completed! Report saved to {output_file}[/bold green]")
    except FileNotFoundError:
        console.print("[bold red]Error: 'dirsearch' command not found.[/bold red]")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"\n[red]Dirsearch exited with an error (Code: {e.returncode}).[/red]")
        sys.exit(1)

    return output_file


def parse_dirsearch_output(output_file: Path) -> List[Tuple[int, str]]:
    results = []
    console.print(f"Parsing results from [cyan]{output_file}[/cyan]...")
    try:
        with open(output_file, 'r', encoding='utf-8') as file:
            for line in file:
                match = re.match(r"(\d{3})\s+.*\s+(https?://.+)", line)
                if match:
                    status_code = int(match.group(1))
                    url = match.group(2).strip()
                    results.append((status_code, url))
    except FileNotFoundError:
        console.print(f"[red]Error: Dirsearch output file not found at {output_file}[/red]")
        return []
    return results


def sort_results(results: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    return sorted(results, key=lambda x: STATUS_CODE_PRIORITY.get(x[0], STATUS_CODE_PRIORITY['default']))


def get_base_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


async def capture_screenshot_task(
        semaphore: asyncio.Semaphore, browser: Browser, url: str, path: Path
):
    async with semaphore:
        context = None
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            console.print(f"[cyan]Capturing {path.name} -> {url}[/cyan]")
            await page.goto(url, timeout=SCREENSHOT_TIMEOUT, wait_until="domcontentloaded")
            await page.screenshot(path=path, full_page=True)
            console.print(f"[green]Screenshot saved: {path.name}[/green]")
        except Exception as e:
            error_type = type(e).__name__
            console.print(f"[red]Failed to capture {path.name} from {url}: {error_type}[/red]")
            path.touch()
        finally:
            if context:
                await context.close()


async def process_all_screenshots(
        results_200: List[Tuple[int, str]], base_target_url: str, scan_screenshot_dir: Path
):
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCREENSHOTS)
    async with async_playwright() as p:
        console.print(f"Launching browser...")
        browser = await p.chromium.launch()
        console.print(
            f"Starting screenshot capture with concurrency limit of [bold magenta]{MAX_CONCURRENT_SCREENSHOTS}[/bold magenta]...")

        tasks = []

        base_url = get_base_url(base_target_url)
        base_path = scan_screenshot_dir / "base.png"
        tasks.append(capture_screenshot_task(semaphore, browser, base_url, base_path))

        # Task 2: Capture all 200-status URLs with sanitized path names.
        for _, url in results_200:
            url_path = urlparse(url).path
            base_name = sanitize_path_for_filename(url_path)
            counter = 0
            path_to_save = scan_screenshot_dir / f"{base_name}.png"
            while path_to_save.exists():
                counter += 1
                path_to_save = scan_screenshot_dir / f"{base_name}_{counter}.png"

            tasks.append(capture_screenshot_task(semaphore, browser, url, path_to_save))

        if tasks:
            await asyncio.gather(*tasks)

        await browser.close()

    console.print("\n[bold green]All screenshot tasks finished.[/bold green]")


def generate_gallery(html_output_path: Path, scan_screenshot_dir: Path):
    console.print("Generating HTML gallery...")
    images = sorted([
        img for img in os.listdir(scan_screenshot_dir)
        if img.endswith(".png") and os.path.getsize(scan_screenshot_dir / img) > 0
    ])

    with open(html_output_path, 'w', encoding='utf-8') as f:
        f.write("<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>")
        f.write("<title>Screenshot Gallery</title><style>")
        f.write(
            "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background-color:#f0f2f5;margin:0;padding:20px;}")
        f.write("h1{text-align:center;color:#1c1e21;}")
        f.write(".gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:20px;}")
        f.write(
            ".card{background-color:white;border:1px solid #ddd;border-radius:8px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.1);}")
        f.write(
            ".card h2{font-size:1em;padding:12px 15px;margin:0;background-color:#f5f6f7;border-bottom:1px solid #ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}")
        f.write(".card a{display:block;text-decoration:none;color:inherit;}")
        f.write(".card .img-container{height:220px;overflow:hidden;}")
        f.write(".card img{width:100%;height:100%;object-fit:cover;transition:transform .2s ease-in-out;}")
        f.write(".card:hover img{transform:scale(1.05);}")
        f.write("</style></head><body><h1>Screenshot Gallery</h1><div class='gallery'>")

        for img in images:
            relative_image_path = f"screenshots/{img}"

            f.write(f"<div class='card'><a href='{relative_image_path}' target='_blank'>")
            f.write(f"<h2>{img}</h2><div class='img-container'><img src='{relative_image_path}' alt='{img}'></div>")
            f.write("</a></div>")

        f.write("</div></body></html>")
    console.print(
        f"[blue]HTML gallery created: [link=file://{html_output_path.resolve()}]file://{html_output_path.resolve()}[/link][/blue]")


def main():
    try:
        url = input("Enter the target URL: ").strip()
        if not url:
            console.print("[red]URL cannot be empty.[/red]")
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            console.print(f"[yellow]Scheme not provided. Defaulting to https://[/yellow]")
            url = f"https://{url}"

        sanitized_name = sanitize_url_for_foldername(url)
        scan_dir = TOP_LEVEL_OUTPUT_DIR / sanitized_name
        scan_screenshot_dir = scan_dir / "screenshots"
        os.makedirs(scan_screenshot_dir, exist_ok=True)
        console.print(f"Saving all output for this scan in: [bold cyan]{scan_dir}[/bold cyan]")

        extra_params = input("Enter optional Dirsearch parameters (or leave empty): ")

        dirsearch_output_file = run_dirsearch(url, extra_params, scan_dir)
        results = parse_dirsearch_output(dirsearch_output_file)

        if not results:
            console.print("[yellow]Dirsearch found no accessible URLs. Exiting.[/yellow]")
            return

        sorted_results = sort_results(results)
        results_200 = [res for res in sorted_results if res[0] == 200]

        console.print(f"Found [bold]{len(sorted_results)}[/bold] total URLs.")
        console.print(
            f"Found [bold green]{len(results_200)}[/bold green] URLs with status 200, which will be screenshotted.")

        if not results_200:
            if not Confirm.ask("No 200-status pages found. Proceed with screenshot of the base URL only?"):
                return
        elif len(results_200) > 15:
            if not Confirm.ask(f"This will generate up to {len(results_200) + 1} screenshots. Continue?"):
                return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_output_file = scan_dir / f"gallery_{timestamp}.html"

        awaitable = process_all_screenshots(results_200, url, scan_screenshot_dir)
        asyncio.run(awaitable)

        generate_gallery(html_output_file, scan_screenshot_dir)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Process interrupted by user. Exiting.[/bold yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()