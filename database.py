import aiosqlite

async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_pokemon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                national_dex_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_shiny BOOLEAN NOT NULL
            );
        """)
        await db.commit()

async def add_user_pokemon(user_id: int, guild_id: int, national_dex_number: int, name: str, is_shiny: bool):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT INTO user_pokemon (user_id, guild_id, national_dex_number, name, is_shiny)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, national_dex_number, name, is_shiny))
        await db.commit()

async def user_has_pokemon(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool) -> bool:
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT 1
            FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (user_id, guild_id, national_dex_number, int(is_shiny)))
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

async def get_all_user_pokemon(user_id: int, guild_id: int):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id, national_dex_number, name, is_shiny
            FROM user_pokemon
            WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id))
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": row[0],
                "national_dex_number": row[1],
                "name": row[2],
                "is_shiny": bool(row[3])
            }
            for row in rows
        ]

async def trade_pokemon(
        offer_user_id: int,
        want_user_id: int,
        offer_national_dex_number: int,
        want_national_dex_number: int,
        offer_is_shiny: bool,
        want_is_shiny: bool
):
    async with aiosqlite.connect("bot.db") as db:
        # Verify from_user owns the offered Pokémon
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE user_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (offer_user_id, offer_national_dex_number, offer_is_shiny))
        offer_row = await cursor.fetchone()
        await cursor.close()

        if offer_row is None:
            raise ValueError("The offering user does not own the offered Pokémon.")

        # Verify to_user owns the wanted Pokémon
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE user_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (want_user_id, want_national_dex_number, want_is_shiny))
        want_row = await cursor.fetchone()
        await cursor.close()

        if want_row is None:
            raise ValueError("The receiving user does not own the wanted Pokémon.")

        offer_id = offer_row[0]
        want_id = want_row[0]

        # Swap owners
        await db.execute("""
            UPDATE user_pokemon SET user_id = ? WHERE id = ?
        """, (want_user_id, offer_id))

        await db.execute("""
            UPDATE user_pokemon SET user_id = ? WHERE id = ?
        """, (offer_user_id, want_id))

        await db.commit()
