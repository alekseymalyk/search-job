"""
Job Scraper — точка входу.

Графічний інтерфейс (рекомендовано):
    python main.py ui

Командний рядок:
    python main.py                                   # повний пайплайн
    python main.py scrape                            # тільки скрейпінг
    python main.py filter                            # тільки фільтрація
    python main.py rank                              # тільки ранжування
    python main.py -q "3D artist"                    # короткий запит
    python main.py -w 5                              # 5 потоків

    # Природня мова (укр/рус/англ):
    python main.py "знайди мені 100 компаній які шукають 3D artist, remote, ЄС"
"""

from job_scraper.cli import main

if __name__ == "__main__":
    main()
