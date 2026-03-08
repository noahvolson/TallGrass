# A one-time script to upload emojis for all Pokémon to the Discord Application
# Uploaded emojis are used when displaying a user's box of caught Pokémon
# Note that Discord Applications have a hard limit of 2,000 emojis
# If we want shiny sprites, we can only include up to Gen 8

import aiohttp
import asyncio
import base64
import io
import os

from dotenv import load_dotenv
from PIL import Image

load_dotenv()
APPLICATION_ID  = os.getenv("APPLICATION_ID")
DISCORD_TOKEN   = os.getenv('DISCORD_TOKEN')
UPLOAD_COUNT    = int(os.getenv("UPLOAD_COUNT"))
INCLUDE_SHINY   = bool(int(os.getenv("INCLUDE_SHINY")))

HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json"
}

def trim_transparent(image_data: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_data)).convert("RGBA")
    bbox = img.getbbox()  # returns (left, top, right, bottom) of non-transparent area
    if bbox:
        img = img.crop(bbox)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def upload_emoji(session, name: str, image_url: str):
    # Fetch the sprite
    async with session.get(image_url) as resp:
        image_data = await resp.read()

    image_data = trim_transparent(image_data)  # crop before encoding

    # Discord requires base64 encoded image
    b64 = base64.b64encode(image_data).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"

    payload = {"name": name, "image": data_uri}

    async with session.post(
            f"https://discord.com/api/v10/applications/{APPLICATION_ID}/emojis",
            headers=HEADERS,
            json=payload
    ) as resp:
        result = await resp.json()
        if resp.status == 201:
            print(f"✅ Uploaded {name} → {result['id']}")
            return name, result["id"]
        else:
            print(f"❌ Failed {name}: {result}")
            return name, None


async def main():
    # PokeAPI sprite URL pattern
    BASE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{dex}.png"
    SHINY_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{dex}.png"

    emoji_map = {}  # will save name → id mappings

    async with aiohttp.ClientSession() as session:
        for dex_number in range(1, UPLOAD_COUNT + 1):

            name = f"pokemon_{dex_number}"  # e.g. pokemon_25 for Pikachu
            url = BASE_URL.format(dex=dex_number)
            result_name, emoji_id = await upload_emoji(session, name, url)
            if emoji_id:
                emoji_map[f"{dex_number}"] = emoji_id

            await asyncio.sleep(0.5) # Avoid rate limiting

            if INCLUDE_SHINY:
                name = f"pokemon_{dex_number}_shiny"  # e.g. pokemon_25_shiny for shiny Pikachu
                url = SHINY_URL.format(dex=dex_number)
                result_name, emoji_id = await upload_emoji(session, name, url)
                if emoji_id:
                    emoji_map[f"{dex_number}_shiny"] = emoji_id

                await asyncio.sleep(0.5)

    # Save the map with ids
    import json
    with open("emoji_map.json", "w") as f:
        json.dump(emoji_map, f, indent=2)
    print("Saved emoji_map.json")


asyncio.run(main())
