import pandas as pd
from bs4 import BeautifulSoup
from supabase import create_client

import os
import requests
import time
from datetime import datetime


headers = {
    "User-Agent": "Mozilla/5.0"
}

rows = []

pages_count = 50

scrape_time = datetime.now().isoformat()

for page in range(1, pages_count + 1):

    url = f"https://pitchfork.com/reviews/albums/?page={page}"
    response = requests.get(url, headers=headers, timeout=20)

    if response.status_code != 200:
        print(f"Blocked or failed on page {page}: {response.status_code}")
        break


    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.summary-item")

    for card in cards:

        album_node = card.select_one("h3")
        album = album_node.get_text(strip=True) if album_node else None

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
            "image" : image,
            "scraped_at": scrape_time
        })

    time.sleep(1)

df = pd.DataFrame(rows)

filename = "pitchfork_output.csv.csv"

if os.path.exists(filename):
    df.to_csv(filename, mode="a", header=False, index=False)
else:
    df.to_csv(filename, index=False)


df["album"] = df["album"].fillna("unknown")
df["artist"] = df["artist"].fillna("unknown")
df["genre"] = df["genre"].fillna("unknown")
df["review_date"] = df["review_date"].fillna("unknown")
df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce").dt.date
df["genre"] = df["genre"].str.strip().str.lower()
df["artist"] = df["artist"].str.strip()
df["review_date"] = (
    df["review_date"]
    .astype(str)
    .str.replace("Reviewed", "", regex=False)
    .str.strip()
)


df = df.drop_duplicates()

df.to_csv("pitchfork_verify_output.csv", index=False)




"""Supabase pipeline"""

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

scrape_time = datetime.now().isoformat()

upload_rows = []

for _, row in df.iterrows():
    upload_rows.append({
        "title": str(row["album"]),
        "artist": str(row["artist"]),
        "genre": str(row["genre"]),
        "review_date": str(row["review_date"]),
        "scraped_at": scrape_time,
        "image" : str(row["image"])
    })

df_upload = pd.DataFrame(upload_rows).drop_duplicates(subset=["title", "scraped_at"])
upload_rows = df_upload.to_dict(orient="records")

result = supabase.table("albums").upsert(upload_rows, on_conflict="title,scraped_at").execute()