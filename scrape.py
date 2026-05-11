import pandas as pd
from bs4 import BeautifulSoup
from supabase import create_client
import smtplib
from email.message import EmailMessage
import os
import requests
import time
from datetime import datetime

headers = {"User-Agent": "Mozilla/5.0"}

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

existing = supabase.table("albums").select("title").execute()
existing_titles = set(row["title"] for row in existing.data)
print(f"{len(existing_titles)} albums already in Supabase")

rows = []
pages_count = 50
scrape_time = datetime.now().isoformat()
stop_scraping = False

for page in range(1, pages_count + 1):
    if stop_scraping:
        break

    url = f"https://pitchfork.com/reviews/albums/?page={page}"
    response = requests.get(url, headers=headers, timeout=20)

    if response.status_code != 200:
        print(f"failed on page {page}: {response.status_code}")
        break

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.summary-item")

    for card in cards:
        album_node = card.select_one("h3")
        album = album_node.get_text(strip=True) if album_node else None

        if album and album in existing_titles:
            print(f"hit existing album '{album}' — stopping")
            stop_scraping = True
            break

        artist_node = card.select_one("div.summary-item__sub-hed")
        artist = artist_node.get_text(strip=True) if artist_node else None

        genre_node = card.select_one("span.rubric__name")
        genre = genre_node.get_text(strip=True) if genre_node else None

        date_node = card.select_one("time")
        review_date = date_node.get_text(strip=True).replace("Reviewed", "").strip() if date_node else None

        image_node = card.select_one("img.responsive-image__image")
        image = image_node.get("src") if image_node else None

        rows.append({
            "album": album,
            "artist": artist,
            "genre": genre,
            "review_date": review_date,
            "image": image,
            "scraped_at": scrape_time
        })

    time.sleep(1)


if not rows:
    print("nothing new, already up to date")
else:
    print(f"{len(rows)} new albums found, pushing to Supabase")

    df = pd.DataFrame(rows)
    df["album"]       = df["album"].fillna("unknown")
    df["artist"]      = df["artist"].fillna("unknown")
    df["genre"]       = df["genre"].fillna("unknown")
    df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce").dt.date.astype(str)
    df["genre"]       = df["genre"].str.strip().str.lower()
    df["artist"]      = df["artist"].str.strip()
    df = df.drop_duplicates()

    upload_rows = []
    for _, row in df.iterrows():
        upload_rows.append({
            "title":       str(row["album"]),
            "artist":      str(row["artist"]),
            "genre":       str(row["genre"]),
            "review_date": str(row["review_date"]),
            "scraped_at":  scrape_time,
            "image":       str(row["image"])
        })

    df_upload = pd.DataFrame(upload_rows).drop_duplicates(subset=["title", "scraped_at"])
    upload_rows = df_upload.to_dict(orient="records")

    supabase.table("albums").upsert(upload_rows, on_conflict="title,scraped_at").execute()
    print(f"done — {len(upload_rows)} rows inserted")

    def send_alert(new_count, new_albums):
        msg = EmailMessage()
        msg["Subject"] = f"{new_count} new reviews on Pitchfork"
        msg["From"]    = os.environ["ALERT_EMAIL"]
        msg["To"]      = os.environ["ALERT_EMAIL"]

        album_list = "\n".join(
            f"- {r['title']} — {r['artist']} ({r['genre']})"
            for r in new_albums[:20]
        )

        msg.set_content(f"""hey,

{new_count} new {"review" if new_count == 1 else "reviews"} just went up on Pitchfork:

{album_list}
{"..." if new_count > 20 else ""}

check the dashboard.
        """)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(os.environ["ALERT_EMAIL"], os.environ["ALERT_PASSWORD"])
            server.send_message(msg)

        print("email sent")

    send_alert(len(upload_rows), upload_rows)
