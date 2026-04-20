import aiosqlite

BOT_DB_FILE = "bot.db"

#
# Set up table structure
#
async def init_db():
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_pokemon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                national_dex_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_shiny BOOLEAN NOT NULL,
                FOREIGN KEY (user_id, guild_id) REFERENCES user(user_id, guild_id)
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

#
# Schema changes made after the bot went live
# TODO set up a more robust migration process
#
async def migrate():
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        version = row[0]

        if version < 1:
            # Support for tournaments
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournament (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    code TEXT NOT NULL UNIQUE,
                    active BOOLEAN NOT NULL DEFAULT 1
                );
            """)
            await db.execute("""
                CREATE TABLE tournament_team (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL REFERENCES tournament(id),
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    UNIQUE (tournament_id, user_id),
                    FOREIGN KEY (user_id, guild_id) REFERENCES user(user_id, guild_id)
                );
            """)
            await db.execute("""
                ALTER TABLE user_pokemon ADD COLUMN tournament_team_id INTEGER REFERENCES tournament_team(id)
            """)
            await db.execute("PRAGMA user_version = 1")
            await db.commit()

        # if version < 2:
        #     ... next migration
        #     await db.execute("PRAGMA user_version = 2")
        #     await db.commit()

#
# Catch rate depends on caught count. To avoid spamming the db I set up a cache
#
_pokemon_count_cache: dict[tuple[int, int], int] = {} # (user_id, guild_id) -> pokemon_count

async def get_pokemon_count(user_id: int, guild_id: int) -> int:
    key = (user_id, guild_id)

    if key not in _pokemon_count_cache:
        # Cache miss: query DB and populate
        async with aiosqlite.connect(BOT_DB_FILE) as db:
            async with db.execute("""
                SELECT COUNT(*) FROM user_pokemon WHERE user_id = ? AND guild_id = ? AND tournament_team_id IS NULL
                """, (user_id, guild_id)
            ) as cursor:
                row = await cursor.fetchone()
                _pokemon_count_cache[key] = row[0] if row else 0

    return _pokemon_count_cache[key]

def invalidate_pokemon_count(user_id: int, guild_id: int) -> None:
    _pokemon_count_cache.pop((user_id, guild_id), None)

def increment_pokemon_count(user_id: int, guild_id: int) -> None:
    key = (user_id, guild_id)
    if key in _pokemon_count_cache:
        _pokemon_count_cache[key] += 1
    # else get_pokemon_count will set the count the next time it's called

#
# Database utility functions
#
async def add_user_pokemon(user_id: int, guild_id: int, national_dex_number: int, name: str, is_shiny: bool):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            INSERT INTO user_pokemon (user_id, guild_id, national_dex_number, name, is_shiny)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, guild_id, national_dex_number, name, is_shiny))
        await db.commit()

async def remove_user_pokemon(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            DELETE FROM user_pokemon
            WHERE rowid = (
                SELECT rowid FROM user_pokemon
                WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
                LIMIT 1
            )
        """, (user_id, guild_id, national_dex_number, is_shiny))
        await db.commit()
        return db.total_changes > 0

async def get_user_pokemon_id(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool) -> int | None:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute("""
            SELECT id
            FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
            LIMIT 1
        """, (user_id, guild_id, national_dex_number, int(is_shiny)))
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None

async def user_has_pokemon(user_id: int, guild_id: int, national_dex_number: int, is_shiny: bool) -> bool:
    return await get_user_pokemon_id(user_id, guild_id, national_dex_number, is_shiny) is not None

async def get_user_box(user_id: int, guild_id: int):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute("""
            SELECT id, national_dex_number, name, is_shiny
            FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? 
            AND tournament_team_id IS NULL      -- Pokemon can only compete once
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
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
            LIMIT 1
        """, (offer_user_id, guild_id, offer_national_dex_number, offer_is_shiny))
        offer_row = await cursor.fetchone()
        await cursor.close()

        if offer_row is None:
            raise ValueError("The offering user does not own the offered Pokémon.")

        # Verify to_user owns the wanted Pokémon
        cursor = await db.execute("""
            SELECT id FROM user_pokemon
            WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
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
                    WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
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
                    WHERE user_id = ? AND guild_id = ? AND national_dex_number = ? AND is_shiny = ? AND tournament_team_id IS NULL
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

async def distribute_rare_candies(guild_id: int, quantity: int, user_id: int = None) -> int:
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        user_filter = 'AND user_id = ?' if user_id is not None else ''
        params = (quantity, guild_id, user_id) if user_id is not None else (quantity, guild_id)

        await db.execute(f"""
            INSERT INTO user (user_id, guild_id, rare_candies)
            SELECT DISTINCT user_id, guild_id, ?
            FROM user_pokemon
            WHERE guild_id = ?
            {user_filter}
            ON CONFLICT (user_id, guild_id)
            DO UPDATE SET rare_candies = rare_candies + excluded.rare_candies
        """, params)
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
            AND user_id = ? 
            AND guild_id = ?
            AND tournament_team_id IS NULL
        """, (new_dex_number, new_name, pokemon_id, user_id, guild_id))
        if cursor.rowcount == 0:
            # Skip commit so both updates are rolled back
            return False

        await db.commit()
        return True

async def create_tournament(guild_id: int, name: str, code: str):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            INSERT INTO tournament (guild_id, name, code) VALUES (?, ?, ?)
        """, (guild_id, name, code))
        await db.commit()

async def close_tournament(guild_id: int, code: str):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        await db.execute("""
            UPDATE tournament
            SET active = 0
            WHERE guild_id = ? AND code = ?
        """, (guild_id, code))
        await db.commit()

async def register_tournament_team(
        user_id: int,
        guild_id: int,
        tournament_code: str,
        team_pokemon_list: list[tuple[int, bool]]
):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        async with db.execute("""
            SELECT id FROM tournament
            WHERE code = ? AND guild_id = ? AND active = 1
        """, (tournament_code, guild_id)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return False

        tournament_id = row[0]

        try:
            cursor = await db.execute("""
                INSERT INTO tournament_team (tournament_id, user_id, guild_id)
                VALUES (?, ?, ?)
            """, (tournament_id, user_id, guild_id))
            team_id = cursor.lastrowid

            for dex_num, is_shiny in team_pokemon_list:
                cursor = await db.execute("""
                    UPDATE user_pokemon
                    SET tournament_team_id = ?
                    WHERE id = (
                        SELECT id FROM user_pokemon
                        WHERE user_id = ?
                          AND guild_id = ?
                          AND national_dex_number = ?
                          AND is_shiny = ?
                          AND tournament_team_id IS NULL
                        LIMIT 1
                    )
                """, (team_id, user_id, guild_id, dex_num, is_shiny))

                if cursor.rowcount == 0:
                    await db.rollback()
                    return False

            await db.commit()

        except aiosqlite.IntegrityError:
            await db.rollback()
            return False

        return True

async def get_active_tournament(code: str):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        cursor = await db.execute(
            "SELECT * FROM tournament WHERE code = ? AND active = 1",
            (code,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None

async def active_tournament_exists(code: str) -> bool:
    return await get_active_tournament(code) is not None

async def get_user_teams(user_id: int, guild_id: int):
    async with aiosqlite.connect(BOT_DB_FILE) as db:
        async with db.execute("""
            SELECT t.name, up.national_dex_number, up.is_shiny, up.name AS pokemon_name
            FROM tournament_team tt
            JOIN tournament t ON t.id = tt.tournament_id
            JOIN user_pokemon up ON up.tournament_team_id = tt.id
            WHERE tt.user_id = ?
              AND tt.guild_id = ?
            ORDER BY t.id
        """, (user_id, guild_id)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return {}

    teams = {}
    for name, dex_num, is_shiny, pokemon_name in rows:
        if name not in teams:
            teams[name] = []
        teams[name].append({'national_dex_number': dex_num, 'is_shiny': is_shiny, 'name': pokemon_name})

    return teams