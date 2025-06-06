import os
import re
import sys
import asyncio
import subprocess
import argparse
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.rule import Rule
from playwright.async_api import async_playwright, Browser

MAX_CONCURRENT_SCREENSHOTS = 10
SCREENSHOT_TIMEOUT = 20000

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
    if not path_str or path_str == "/":
        return "index"
    clean_path = path_str.split('?')[0].strip('/')
    sanitized = clean_path.replace('/', '_')
    sanitized = re.sub(r'\.(php|html|htm|asp|aspx|jsp|txt)$', '', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', sanitized)
    return sanitized if sanitized else "page"


def run_dirsearch(url: str, extra_params: List[str], scan_dir: Path) -> Optional[Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = scan_dir / f"dirsearch_report_{timestamp}.txt"
    cmd = ['dirsearch', '-u', url, '--output', str(output_file), '--full-url'] + extra_params

    console.print(f"[green]Starting Dirsearch for URL: {url}[/green]")
    console.print(f"[grey50]Command: {' '.join(cmd)}[/grey50]\n")
    try:
        subprocess.run(cmd, check=True)
        console.print(f"\n[bold green]Dirsearch completed! Report saved to {output_file}[/bold green]")
    except FileNotFoundError:
        console.print("[bold red]Error: 'dirsearch' command not found.[/bold red]")
        console.print("Please ensure dirsearch is installed and in your system's PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"\n[red]Dirsearch exited with an error (Code: {e.returncode}).[/red]")
        return None
    return output_file


def parse_dirsearch_output(output_file: Path) -> List[Tuple[int, str]]:
    results = []
    console.print(f"Parsing results from [cyan]{output_file}[/cyan]...")
    try:
        with open(output_file, 'r', encoding='utf-8') as file:
            for line in file:
                match = re.match(r"(\d{3})\s+.*\s+(https?://.+)", line)
                if match:
                    results.append((int(match.group(1)), match.group(2).strip()))
    except FileNotFoundError:
        console.print(f"[red]Error: Dirsearch output file not found at {output_file}[/red]")
    return results


def get_base_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


async def capture_screenshot_task(semaphore: asyncio.Semaphore, browser: Browser, url: str, path: Path):
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
            console.print(f"[red]Failed to capture {path.name} from {url}: {type(e).__name__}[/red]")
            path.touch()
        finally:
            if context: await context.close()


async def process_all_screenshots(results_200: List[Tuple[int, str]], base_target_url: str,
                                  scan_screenshot_dir: Path) -> Path:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCREENSHOTS)
    base_path = scan_screenshot_dir / "base.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Immer ein Screenshot der Basis-URL machen
        tasks = [capture_screenshot_task(semaphore, browser, get_base_url(base_target_url), base_path)]
        # Screenshots für alle 200er Ergebnisse
        for _, url in results_200:
            base_name = sanitize_path_for_filename(urlparse(url).path)
            path_to_save = scan_screenshot_dir / f"{base_name}.png"
            counter = 0
            while path_to_save.exists():
                counter += 1
                path_to_save = scan_screenshot_dir / f"{base_name}_{counter}.png"
            tasks.append(capture_screenshot_task(semaphore, browser, url, path_to_save))

        if tasks:
            await asyncio.gather(*tasks)
        await browser.close()
    return base_path


def generate_gallery(html_output_path: Path, scan_screenshot_dir: Path):
    images = sorted([p.name for p in scan_screenshot_dir.glob("*.png") if p.stat().st_size > 0])
    if not images:
        console.print(f"[yellow]No successful screenshots were taken for the gallery.[/yellow]")
        return

    with open(html_output_path, 'w', encoding='utf-8') as f:
        f.write("<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>Screenshot Gallery</title><style>")
        f.write(
            "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background-color:#f0f2f5;margin:0;padding:20px;}")
        f.write(
            "h1{text-align:center;color:#1c1e21;} .gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:20px;}")
        f.write(
            ".card{background-color:white;border:1px solid #ddd;border-radius:8px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.1);}")
        f.write(
            ".card h2{font-size:1em;padding:12px 15px;margin:0;background-color:#f5f6f7;border-bottom:1px solid #ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}")
        f.write(
            ".card a{display:block;text-decoration:none;color:inherit;} .card .img-container{height:220px;overflow:hidden;}")
        f.write(
            ".card img{width:100%;height:100%;object-fit:cover;transition:transform .2s ease-in-out;} .card:hover img{transform:scale(1.05);}")
        f.write("</style></head><body><h1>Screenshot Gallery</h1><div class='gallery'>")
        for img in images:
            f.write(
                f"<div class='card'><a href='screenshots/{img}' target='_blank'><h2>{img}</h2><div class='img-container'><img src='screenshots/{img}' alt='{img}'></div></a></div>")
        f.write("</div></body></html>")
    console.print(
        f"[blue]HTML gallery created: [link=file://{html_output_path.resolve()}]file://{html_output_path.resolve()}[/link][/blue]")


def generate_master_index(scan_results: List[Dict]):
    index_path = TOP_LEVEL_OUTPUT_DIR / "index.html"
    console.print(Rule("[bold blue]Generating Master Index Page", style="blue"))
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(
            "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>Scan Results Dashboard</title><style>")
        f.write(
            "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background-color:#f0f2f5;margin:0;padding:20px;}")
        f.write(
            "h1{text-align:center;color:#1c1e21;} .gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:20px;}")
        f.write(
            ".card{background-color:white;border:1px solid #ddd;border-radius:8px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.1);}")
        f.write(
            ".card h2{font-size:1em;padding:12px 15px;margin:0;background-color:#f5f6f7;border-bottom:1px solid #ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}")
        f.write(
            ".card a{display:block;text-decoration:none;color:inherit;} .card .img-container{height:220px;overflow:hidden;background-color:#e9ebee;display:flex;align-items:center;justify-content:center;}")
        f.write(
            ".card img{width:100%;height:100%;object-fit:cover;transition:transform .2s ease-in-out;} .card:hover img{transform:scale(1.05);}")
        f.write("</style></head><body><h1>Scan Results Dashboard</h1><div class='gallery'>")
        for result in scan_results:
            f.write(
                f"<div class='card'><a href='{result['gallery_path']}' target='_blank'><h2>{result['url']}</h2><div class='img-container'><img src='{result['preview_path']}' alt='{result['url']}'></div></a></div>")
        f.write("</div></body></html>")
    console.print(
        f"[bold blue]Master index created: [link=file://{index_path.resolve()}]file://{index_path.resolve()}[/link][/bold blue]")

async def run_scan_for_target(target_url: str, extra_params: List[str]) -> Optional[Dict]:
    console.print(Rule(f"[bold yellow]Processing Target: {target_url}", style="yellow"))
    sanitized_name = sanitize_url_for_foldername(target_url)
    scan_dir = TOP_LEVEL_OUTPUT_DIR / sanitized_name
    scan_screenshot_dir = scan_dir / "screenshots"
    os.makedirs(scan_screenshot_dir, exist_ok=True)
    console.print(f"Saving all output for this scan in: [bold cyan]{scan_dir}[/bold cyan]")

    dirsearch_output_file = run_dirsearch(target_url, extra_params, scan_dir)
    if not dirsearch_output_file:
        console.print(f"[bold red]Skipping screenshot phase for {target_url} due to dirsearch error.[/bold red]")
        return None

    results = parse_dirsearch_output(dirsearch_output_file)
    if not results:
        console.print("[yellow]Dirsearch found no accessible URLs. Moving on.[/yellow]")
        return None

    results_200 = [res for res in results if res[0] == 200]
    console.print(
        f"Found [bold]{len(results)}[/bold] total URLs, [bold green]{len(results_200)}[/bold green] with status 200.")

    # KEINE ABFRAGE MEHR - ES GEHT IMMER DIREKT WEITER
    console.print(
        f"Starting screenshot capture for {len(results_200) + 1} URLs with concurrency limit of [bold magenta]{MAX_CONCURRENT_SCREENSHOTS}[/bold magenta]...")
    base_screenshot_path = await process_all_screenshots(results_200, target_url, scan_screenshot_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_output_file = scan_dir / f"gallery_{timestamp}.html"
    generate_gallery(html_output_file, scan_screenshot_dir)

    return {
        "url": target_url,
        "gallery_path": html_output_file.relative_to(TOP_LEVEL_OUTPUT_DIR).as_posix(),
        "preview_path": base_screenshot_path.relative_to(TOP_LEVEL_OUTPUT_DIR).as_posix()
    }


def get_user_input() -> Tuple[List[str], List[str]]:
    targets, extra_params = [], []
    console.print(Rule("[bold magenta]Advanced Dirsearch & Screenshot Tool", style="magenta"))
    console.print("Select input method:\n[1] Single URL\n[2] URL List File")
    try:
        choice = Prompt.ask(">", choices=["1", "2"], show_choices=False)
        if choice == '1':
            url = Prompt.ask("Enter the target URL").strip()
            if url: targets.append(url)
        elif choice == '2':
            file_path_str = Prompt.ask("Enter the path to the URL list file").strip()
            file_path = Path(file_path_str)
            if file_path.is_file():
                with open(file_path, 'r') as f:
                    targets = [line.strip() for line in f if line.strip()]
            else:
                console.print(f"[red]Error: File not found at '{file_path_str}'[/red]")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Input cancelled.[/yellow]")

    if targets:
        console.print("\nEnter any additional parameters for dirsearch (e.g., -w wordlist.txt --crawl).")
        extra_params_str = Prompt.ask("Optional Dirsearch parameters", default="").strip()
        extra_params = extra_params_str.split()
    return targets, extra_params
--
async def main():
    parser = argparse.ArgumentParser(description="A wrapper for dirsearch to take screenshots of results.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-u', '--url', help="Single target URL.")
    group.add_argument('-l', '--urls-file', help="Path to a file containing a list of target URLs.")
    args, unknown_args = parser.parse_known_args()

    targets, extra_params = [], []
    is_list_scan = False

    if args.url or args.urls_file:
        if args.url:
            targets.append(args.url)
        else:
            is_list_scan = True
            try:
                with open(args.urls_file, 'r') as f:
                    targets = [line.strip() for line in f if line.strip()]
            except FileNotFoundError:
                console.print(f"[red]Error: File not found at '{args.urls_file}'[/red]")
                return
        extra_params = unknown_args
    else:
        interactive_targets, interactive_params = get_user_input()
        targets, extra_params = interactive_targets, interactive_params
        if len(targets) > 1: is_list_scan = True

    if not targets:
        console.print("[red]No target URLs to scan. Exiting.[/red]")
        return

    normalized_targets = [f"https://{t}" if not t.startswith(('http://', 'https://')) else t for t in targets]

    scan_results = []
    for i, target in enumerate(normalized_targets):
        result = await run_scan_for_target(target, extra_params)
        if result:
            scan_results.append(result)

        if i < len(normalized_targets) - 1:
            console.print("\n")

    if is_list_scan and scan_results:
        generate_master_index(scan_results)

    console.print(Rule("[bold green]All scans completed.", style="green"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Process interrupted by user. Exiting.[/bold yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        console.print_exception(show_locals=False)
        sys.exit(1)