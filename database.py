import aiosqlite

BOT_DB_FILE = "bot.db"

async def init_db():
    async with aiosqlite.connect(BOT_DB_FILE) as db:
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                rare_candies INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );
        """)
        await db.commit()

async def add_user_pokemon(user_id: int, guild_id: int, national_dex_number: int, name: str, is_shiny: bool):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            INSERT INTO user_pokemon (user_id, guild_id, national_dex_number, name, is_shiny)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, national_dex_number, name, is_shiny))
        await db.commit()

async def get_user_pokemon_id(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool) -> int | None:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute("""
            SELECT id
            FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (user_id, guild_id, national_dex_number, int(is_shiny)))
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None

async def user_has_pokemon(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool) -> bool:
    return await get_user_pokemon_id(user_id, guild_id, national_dex_number, is_shiny) is not None

async def get_all_user_pokemon(user_id: int, guild_id: int):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
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
        guild_id: int,
        offer_user_id: int,
        want_user_id: int,
        offer_national_dex_number: int,
        want_national_dex_number: int,
        offer_is_shiny: bool,
        want_is_shiny: bool
):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        # Verify from_user owns the offered Pokémon
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (offer_user_id, guild_id, offer_national_dex_number, offer_is_shiny))
        offer_row = await cursor.fetchone()
        await cursor.close()

        if offer_row is None:
            raise ValueError("The offering user does not own the offered Pokémon.")

        # Verify to_user owns the wanted Pokémon
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
            LIMIT 1
        """, (want_user_id, guild_id, want_national_dex_number, want_is_shiny))
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

async def trade_pokemon_multi(
        guild_id: int,
        offer_user_id: int,
        want_user_id: int,
        offer_pokemon: list[tuple[int, bool]],
        want_pokemon: list[tuple[int, bool]],
):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("BEGIN")
        try:
            offer_ids = []
            for dex_num, is_shiny in offer_pokemon:
                cursor = await db.execute("""
                    SELECT id FROM user_pokemon
                    WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
                    LIMIT 1
                """, (offer_user_id, guild_id, dex_num, is_shiny))
                row = await cursor.fetchone()
                await cursor.close()
                if row is None:
                    raise ValueError(f"The offering user does not own Pokémon #{dex_num} (shiny={is_shiny}).")
                offer_ids.append(row[0])

            want_ids = []
            for dex_num, is_shiny in want_pokemon:
                cursor = await db.execute("""
                    SELECT id FROM user_pokemon
                    WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ?
                    LIMIT 1
                """, (want_user_id, guild_id, dex_num, is_shiny))
                row = await cursor.fetchone()
                await cursor.close()
                if row is None:
                    raise ValueError(f"The receiving user does not own Pokémon #{dex_num} (shiny={is_shiny}).")
                want_ids.append(row[0])

            for pokemon_id in offer_ids:
                await db.execute("""
                    UPDATE user_pokemon SET user_id = ? WHERE id = ?
                """, (want_user_id, pokemon_id))

            for pokemon_id in want_ids:
                await db.execute("""
                    UPDATE user_pokemon SET user_id = ? WHERE id = ?
                """, (offer_user_id, pokemon_id))

            await db.commit()

        except Exception:
            await db.rollback()
            raise

async def distribute_rare_candies(guild_id: int, quantity: int) -> int:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            INSERT INTO user (user_id, guild_id, rare_candies)
            SELECT DISTINCT user_id, guild_id, ?
            FROM user_pokemon
            WHERE guild_id = ?
            ON CONFLICT (user_id, guild_id)
            DO UPDATE SET rare_candies = rare_candies + excluded.rare_candies
        """, (quantity, guild_id))
        await db.commit()
        return db.total_changes

async def get_rare_candies(user_id: int, guild_id: int) -> int:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        async with db.execute("""
            SELECT rare_candies FROM user
            WHERE user_id = ? AND guild_id = ?
        """, (user_id, guild_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def evolve(user_id, guild_id, pokemon_id, new_dex_number, new_name) -> bool:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute("""
            UPDATE user SET rare_candies = rare_candies - 1
            WHERE user_id = ? AND guild_id = ? AND rare_candies > 0
        """, (user_id, guild_id))
        if cursor.rowcount == 0:
            return False  # not enough candies

        cursor = await db.execute("""
            UPDATE user_pokemon SET national_dex_number = ?, name = ?
            WHERE id = ?
        """, (new_dex_number, new_name, pokemon_id))
        if cursor.rowcount == 0:
            # Don't commit — both updates are rolled back automatically
            return False

        await db.commit()
        return True
