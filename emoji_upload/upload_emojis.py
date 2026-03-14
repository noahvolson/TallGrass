# A one-off script to upload emojis for all Pokémon to the Discord Application
# Uploaded emojis are used when displaying a user's box of caught Pokémon
# Note that Discord Applications have a hard limit of 2,000 emojis
# If we want shiny sprites, we can only include up to Gen 8

# Note: Because we only need a one-off script, I had Claude generate it to save some time

import asyncio
import aiohttp
import base64
import io
import json
import os

from dotenv import load_dotenv
from PIL import Image

load_dotenv()
APPLICATION_ID  = os.getenv("APPLICATION_ID")
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")

HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json"
}

BASE_URL  = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{dex}.png"
SHINY_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{dex}.png"

UPLOAD_COUNT    = 906
INCLUDE_SHINY   = True
EMOJI_MAP_FILE  = "emoji_upload/emoji_map.json"
FAILED_FILE     = "emoji_upload/failed.json"

def load_json_file(path: str) -> dict | list:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {} if path.endswith(".json") and "map" in path else []


def save_json_file(path: str, data: dict | list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def trim_transparent(image_data: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_data)).convert("RGBA")
    bbox = img.getbbox()  # returns (left, top, right, bottom) of non-transparent area
    if bbox:
        img = img.crop(bbox)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def fetch_sprite(session: aiohttp.ClientSession, name: str, image_url: str) -> bytes | None:
    try:
        async with session.get(image_url) as resp:
            if resp.status == 404:
                print(f"❌ {name}: sprite not found (404)")
                return None
            if resp.status != 200:
                print(f"❌ {name}: unexpected status fetching sprite ({resp.status})")
                return None
            return await resp.read()
    except aiohttp.ClientError as e:
        print(f"❌ {name}: network error fetching sprite: {e}")
        return None
    except asyncio.TimeoutError:
        print(f"❌ {name}: timed out fetching sprite")
        return None


async def upload_emoji(session: aiohttp.ClientSession, name: str, image_url: str) -> tuple[str, str | None]:
    # Fetch the sprite
    image_data = await fetch_sprite(session, name, image_url)
    if image_data is None:
        return name, None

    # Process image
    try:
        image_data = trim_transparent(image_data)
        b64 = base64.b64encode(image_data).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64}"
    except Exception as e:
        print(f"❌ {name}: could not process image: {e}")
        return name, None

    # Upload to Discord
    payload = {"name": name, "image": data_uri}
    try:
        async with session.post(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/emojis",
            headers=HEADERS,
            json=payload
        ) as resp:
            try:
                result = await resp.json(content_type=None)
            except Exception as e:
                print(f"❌ {name}: could not parse Discord response: {e}")
                return name, None

            if resp.status == 201:
                print(f"✅ Uploaded {name} → {result['id']}")
                return name, result["id"]
            else:
                print(f"❌ {name}: Discord rejected upload: {result}")
                return name, None

    except aiohttp.ClientError as e:
        print(f"❌ {name}: network error uploading to Discord: {e}")
        return name, None
    except asyncio.TimeoutError:
        print(f"❌ {name}: timed out uploading to Discord")
        return name, None


async def main():
    # Load existing progress so the script can be safely re-run
    emoji_map: dict = load_json_file(EMOJI_MAP_FILE)
    failed: list   = load_json_file(FAILED_FILE)

    already_done = set(emoji_map.keys()) | set(failed)
    if already_done:
        print(f"Resuming — {len(emoji_map)} uploaded, {len(failed)} previously failed\n")

    async with aiohttp.ClientSession() as session:
        for dex_number in range(1, UPLOAD_COUNT + 1):

            # Normal sprite
            name = f"pokemon_{dex_number}"
            if name not in already_done:
                url  = BASE_URL.format(dex=dex_number)
                _, emoji_id = await upload_emoji(session, name, url)
                if emoji_id:
                    emoji_map[name] = emoji_id
                else:
                    failed.append(name)
                # Persist after every upload so a crash loses at most one entry
                save_json_file(EMOJI_MAP_FILE, emoji_map)
                save_json_file(FAILED_FILE, failed)

                await asyncio.sleep(0.5)  # Avoid rate limiting

            # Shiny sprite
            if INCLUDE_SHINY:
                shiny_name = f"pokemon_{dex_number}_shiny"
                if shiny_name not in already_done:
                    url  = SHINY_URL.format(dex=dex_number)
                    _, emoji_id = await upload_emoji(session, shiny_name, url)
                    if emoji_id:
                        emoji_map[shiny_name] = emoji_id
                    else:
                        failed.append(shiny_name)
                    save_json_file(EMOJI_MAP_FILE, emoji_map)
                    save_json_file(FAILED_FILE, failed)

                    await asyncio.sleep(0.5)

    print(f"\n✅ Done. {len(emoji_map)} emojis uploaded.")
    if failed:
        print(f"⚠️  {len(failed)} pokemon need to be manually added:")
        for name in failed:
            print(f"  - {name}")
    else:
        print("All pokemon uploaded successfully!")


asyncio.run(main())