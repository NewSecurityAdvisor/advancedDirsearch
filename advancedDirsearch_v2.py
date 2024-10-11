import os
import re
import subprocess
import requests
from rich.console import Console
from PIL import Image
from playwright.sync_api import sync_playwright

console = Console()

# Definiere die Wichtigkeit von Statuscodes
STATUS_CODE_PRIORITY = {
    200: 1,   # Wichtigste Seiten
    301: 2,   # Permanente Redirects
    302: 2,   # Temporäre Redirects
    403: 3,   # Verbotene Seiten
    404: 4,   # Nicht gefundene Seiten
    'default': 5  # Andere Codes
}

def run_dirsearch(url, extra_params):
    """Führt dirsearch aus und speichert die Ausgabe in eine Datei."""
    output_file = './dirsearch_output.txt'
    cmd = ['dirsearch', '-u', url, '-o', output_file] + extra_params.split()
    
    console.print(f"[green]Starte Dirsearch für URL: {url}[/green]")
    
    try:
        subprocess.run(cmd, check=True)
        console.print(f"[green]Dirsearch abgeschlossen! Ergebnisse in {output_file} gespeichert.[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Fehler bei der Ausführung von dirsearch: {e}[/red]")
        return None
    
    return output_file

def parse_dirsearch_output(output_file):
    """Parst die Dirsearch-Ausgabe und extrahiert die Statuscodes und URLs."""
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
    """Sortiert die Ergebnisse nach Statuscode-Wichtigkeit."""
    return sorted(results, key=lambda x: STATUS_CODE_PRIORITY.get(x[0], STATUS_CODE_PRIORITY['default']))

def capture_screenshot(url, idx):
    """Erzeugt einen Screenshot der URL mit Playwright."""
    output_image = f'screenshots/screenshot_{idx}.png'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Nutzt Chromium im Headless-Modus
        page = browser.new_page()
        try:
            page.goto(url, timeout=60000)  # 60 Sekunden Timeout
            page.screenshot(path=output_image)
            console.print(f"[green]Screenshot für {url} gespeichert: {output_image}[/green]")
        except Exception as e:
            console.print(f"[red]Fehler beim Laden von {url}: {e}[/red]")
        finally:
            browser.close()
    return output_image

def show_image(image_path):
    """Zeigt ein Bild im Standard-Bildbetrachter des Systems."""
    img = Image.open(image_path)
    img.show()

def navigate_results(sorted_results):
    """Erlaubt es dem Benutzer, durch die URLs zu navigieren."""
    idx = 0
    while True:
        status_code, url = sorted_results[idx]
        console.print(f"\n[cyan]Seite {idx+1} von {len(sorted_results)}: {url} (Status: {status_code})[/cyan]")
        
        # Screenshot der Seite erstellen und anzeigen
        screenshot_path = capture_screenshot(url, idx)
        show_image(screenshot_path)
        
        # Benutzerinteraktion: Weiterblättern oder Beenden
        user_input = input("\nDrücke Enter für die nächste Seite oder 'q' zum Beenden: ")
        if user_input.lower() == 'q':
            break
        idx = (idx + 1) % len(sorted_results)  # Zyklisch durch die URLs navigieren

if __name__ == "__main__":
    # Schritt 1: Eingabe der URL und optionaler Dirsearch-Parameter
    url = input("Gib die URL ein: ")
    extra_params = input("Gib optionale Dirsearch-Parameter ein (oder leer lassen): ")
    
    # Schritt 2: Dirsearch ausführen
    output_file = run_dirsearch(url, extra_params)
    if output_file is None:
        console.print("[red]Dirsearch wurde nicht erfolgreich ausgeführt.[/red]")
        exit(1)
    
    # Schritt 3: Ergebnisse parsen
    results = parse_dirsearch_output(output_file)
    
    # Schritt 4: Ergebnisse sortieren
    sorted_results = sort_results(results)
    
    # Schritt 5: Gefilterte und sortierte URLs anzeigen
    if sorted_results:
        console.print(f"\n[green]{len(sorted_results)} Ergebnisse sortiert nach Wichtigkeit.[/green]")
        navigate_results(sorted_results)
    else:
        console.print("[yellow]Keine Ergebnisse gefunden.[/yellow]")

