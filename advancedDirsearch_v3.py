import os
import re
import sys
import asyncio
import subprocess
from urllib.parse import urlparse
from datetime import datetime
from rich.console import Console
from playwright.async_api import async_playwright

console = Console()

STATUS_CODE_PRIORITY = {
    200: 1,
    301: 2,
    302: 2,
    403: 3,
    404: 4,
    'default': 5
}

SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs("output", exist_ok=True)

def run_dirsearch(url, extra_params):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed = urlparse(url)
    identifier = parsed.netloc.replace('.', '_')
    output_file = f"dirsearch_{identifier}_{timestamp}.txt"
    cmd = ['dirsearch', '-u', url, '-o', output_file] + extra_params.split()

    console.print(f"[green]Starte Dirsearch für URL: {url}[/green]")
    try:
        subprocess.run(cmd, check=True)
        console.print(f"[green]Dirsearch abgeschlossen! Ergebnisse in {output_file} gespeichert.[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Fehler bei der Ausführung von dirsearch: {e}[/red]")
        sys.exit(1)

    return output_file

def parse_dirsearch_output(output_file):
    results = []
    with open(output_file, 'r') as file:
        lines = file.readlines()
        for line in lines:
            match = re.match(r"(\d{3})\s+\S+\s+(\S+)", line)
            if match:
                status_code = int(match.group(1))
                url = match.group(2)
                results.append((status_code, url))
    return results

def sort_results(results):
    return sorted(results, key=lambda x: STATUS_CODE_PRIORITY.get(x[0], STATUS_CODE_PRIORITY['default']))

def get_base_url(url):
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}/"

def generate_output_filename_from_url(url):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed = urlparse(url)
    identifier = parsed.netloc.replace('.', '_')
    return os.path.join("output", f"gallery_{identifier}_{timestamp}.html")

async def capture_screenshot(playwright, url, path):
    browser = await playwright.chromium.launch()
    context = await browser.new_context(ignore_https_errors=True)
    page = await context.new_page()
    try:
        await page.goto(url, timeout=20000)
        await page.screenshot(path=path, full_page=True)
        console.print(f"[green]Screenshot gespeichert: {path}[/green]")
    except Exception as e:
        console.print(f"[red]Fehler bei {url}: {e}[/red]")
    finally:
        await browser.close()

async def process_all_screenshots(sorted_results, html_output_file):
    async with async_playwright() as p:
        tasks = []
        seen = set()
        for idx, (_, url) in enumerate(sorted_results):
            if url not in seen:
                path = os.path.join(SCREENSHOT_DIR, f"screenshot_{idx}.png")
                tasks.append(capture_screenshot(p, url, path))
                seen.add(url)
        # Basis-URL Screenshot
        base_url = get_base_url(sorted_results[0][1])
        base_path = os.path.join(SCREENSHOT_DIR, "screenshot_base.png")
        tasks.append(capture_screenshot(p, base_url, base_path))
        await asyncio.gather(*tasks)

        generate_gallery(html_output_file)

def generate_gallery(output_path):
    images = sorted([img for img in os.listdir(SCREENSHOT_DIR) if img.endswith(".png")])
    with open(output_path, 'w') as f:
        f.write("<html><head><title>Screenshot Galerie</title>")
        f.write("<style>body{font-family:sans-serif;}img{max-width:100%;margin-bottom:20px;}div{margin-bottom:40px;}</style>")
        f.write("</head><body><h1>Screenshots</h1>")
        for img in images:
            f.write(f"<div><h2>{img}</h2><img src='../{SCREENSHOT_DIR}/{img}'></div>")
        f.write("</body></html>")
    console.print(f"[blue]HTML-Galerie erstellt: {output_path}[/blue]")

def main():
    url = input("Gib die URL ein: ")
    extra_params = input("Gib optionale Dirsearch-Parameter ein (oder leer lassen): ")

    output_file = run_dirsearch(url, extra_params)
    results = parse_dirsearch_output(output_file)
    sorted_results = sort_results(results)

    if not sorted_results:
        console.print("[yellow]Keine Ergebnisse gefunden.[/yellow]")
        return

    count_200 = sum(1 for code, _ in sorted_results if code == 200)
    if count_200 > 10:
        confirm = input(f"[Warnung] {count_200} Seiten mit Status 200. Fortfahren mit Screenshots? (y/n): ")
        if confirm.lower() != 'y':
            console.print("[yellow]Screenshot-Erstellung abgebrochen.[/yellow]")
            return

    html_output_file = generate_output_filename_from_url(sorted_results[0][1])
    asyncio.run(process_all_screenshots(sorted_results, html_output_file))

if __name__ == "__main__":
    main()
