"""
Job Scraper — точка входа.

Запуск:
    python main.py                                   # полный пайплайн
    python main.py scrape                            # только скрейпинг
    python main.py filter                            # только фильтрация
    python main.py rank                              # только ранжирование
    python main.py -q "3D artist"                    # короткий запрос
    python main.py -w 5                              # 5 потоков

    # Естественный язык (укр/рус/англ):
    python main.py "знайди мені 100 компаній які шукають 3D artist, remote, ЄС"
"""

from job_scraper.cli import main

if __name__ == "__main__":
    main()
