import asyncio
import aiosqlite

async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_pokemon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                national_dex_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                nickname TEXT NOT NULL,
                image_url TEXT NOT NULL,
                is_shiny BOOLEAN NOT NULL
            );
        """)
        await db.commit()

async def add_user_pokemon(user_id: int, national_dex_number: int, name: str, nickname: str, image_url: str, is_shiny: bool):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT INTO user_pokemon (user_id, national_dex_number, name, nickname, image_url, is_shiny)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, national_dex_number, name, nickname, image_url, is_shiny))
        await db.commit()

async def get_all_user_pokemon(user_id: int):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id, national_dex_number, name, nickname, image_url, is_shiny
            FROM user_pokemon
            WHERE user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": row[0],
                "national_dex_number": row[1],
                "name": row[2],
                "nickname": row[3],
                "image_url": row[4],
                "is_shiny": bool(row[5])
            }
            for row in rows
        ]

async def trade_pokemon(from_user_id: int, to_user_id: int, pokemon_id: int):
    async with aiosqlite.connect("bot.db") as db:
        # Make sure the Pokémon belongs to the from_user
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE id = ? AND user_id = ?
        """, (pokemon_id, from_user_id))
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            raise ValueError("This Pokémon does not belong to the user.")

        # Swap the owner
        await db.execute("""
            UPDATE user_pokemon
            SET user_id = ?
            WHERE id = ?
        """, (to_user_id, pokemon_id))
        await db.commit()
