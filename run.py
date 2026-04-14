#!/usr/bin/env python3
"""JobFit AI — CLI entry point."""

import json
import subprocess
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

BANNER = """
╔══════════════════════════════════════════════════╗
║          === JobFit AI ===                       ║
║   Smart Job Application Assistant                ║
╚══════════════════════════════════════════════════╝
"""

MENU = """
1. Start Streamlit app
2. Test scraper          (enter a URL, see scraped text)
3. Test context builder  (scan docs/ folder, print parsed context)
4. Test analyzer         (enter a URL, see analysis JSON)
5. Exit
"""


def start_app():
    print("Starting Streamlit app…")
    subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])


def test_scraper():
    from src.scraper import scrape_job
    url = input("Enter job posting URL: ").strip()
    if not url:
        print("No URL entered.")
        return
    print("Scraping…")
    result = scrape_job(url)
    if result.get("error"):
        print(f"Error: {result.get('message')}")
    else:
        print(f"\nJob Title : {result.get('job_title')}")
        print(f"Company   : {result.get('company')}")
        print(f"Location  : {result.get('location')}")
        print(f"\n--- JD Text (first 2000 chars) ---")
        print((result.get("jd_text") or "")[:2000])


def test_context_builder():
    from src.context_builder import build_context
    print("Scanning docs/ folder…")
    context = build_context()
    if context.get("empty"):
        print("docs/ folder is empty. Add documents and try again.")
        return
    if context.get("parse_error"):
        print("Context parsed with errors. Raw text length:", len(context.get("raw_text", "")))
        return
    print(json.dumps(context, indent=2, ensure_ascii=False)[:3000])
    print(f"\n(Files found: {context.get('files_found')})")


def test_analyzer():
    from src.analyzer import analyze_jd
    from src.context_builder import build_context
    from src.scraper import scrape_job

    url = input("Enter job posting URL: ").strip()
    if not url:
        print("No URL entered.")
        return

    print("Loading context from docs/…")
    context = build_context()
    if context.get("empty"):
        print("docs/ folder empty — analyzer needs a candidate profile.")
        return

    print("Scraping…")
    jd = scrape_job(url)
    if jd.get("error"):
        print(f"Scrape error: {jd.get('message')}")
        return

    print("Analyzing…")
    analysis = analyze_jd(jd, context)
    print(json.dumps(analysis, indent=2, ensure_ascii=False))


def main():
    print(BANNER)
    while True:
        print(MENU)
        choice = input("Select option: ").strip()
        if choice == "1":
            start_app()
        elif choice == "2":
            test_scraper()
        elif choice == "3":
            test_context_builder()
        elif choice == "4":
            test_analyzer()
        elif choice == "5":
            print("Goodbye.")
            sys.exit(0)
        else:
            print("Invalid option. Please enter 1-5.")


if __name__ == "__main__":
    main()
