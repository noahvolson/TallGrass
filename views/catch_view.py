import asyncio

import database
import logging
import math
import os
import random
import time

import discord

from collections import defaultdict
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
log_level                   = int(os.getenv('LOG_LEVEL'))
catch_cooldown_sec          = int(os.getenv('CATCH_COOLDOWN_SECONDS'))
catch_window_sec            = int(os.getenv('CATCH_WINDOW_SECONDS'))
pokeball_emoji_id           = int(os.getenv('POKEBALL_EMOJI_ID'))
soft_box_limit              = int(os.getenv('SOFT_BOX_LIMIT'))
soft_box_penalty            = int(os.getenv('SOFT_BOX_PENALTY'))

# Init logging to discord.log
logger = logging.getLogger('CatchView')
logger.setLevel(log_level)

async def _calculate_user_catch_rate(attempts, base, scaling_rate, user_id, guild_id):
    count = await database.get_pokemon_count(user_id, guild_id)
    overflow = max(count - soft_box_limit, 0)

    rate = base + round(scaling_rate * math.log1p(attempts)) - (soft_box_penalty * overflow)
    return max(rate, 1) # Users should always have a chance, even if their box is large

class CatchView(discord.ui.View):

    def __init__(self, log_handler, spawned_pokemon_id, spawned_pokemon_name, spawned_pokemon_catch_percent, spawned_pokemon_catch_scaling, is_shiny):

        if log_handler:
            logger.addHandler(log_handler)

        self.message = None # Set after sending the view
        self.cooldowns = {} # user_id -> (last_click_time, last_message)
        self.attempts = defaultdict(int) # user_id -> num_failed_attempts
        self.claimed = False
        self.claim_lock = asyncio.Lock()

        # Details of the Pokémon available for catching
        self.spawned_pokemon_id = spawned_pokemon_id
        self.spawned_pokemon_name = spawned_pokemon_name
        self.spawned_pokemon_catch_percent = spawned_pokemon_catch_percent
        self.spawned_pokemon_catch_scaling = spawned_pokemon_catch_scaling
        self.is_shiny = is_shiny

        self.flee_time = datetime.now() + timedelta(seconds=catch_window_sec)
        self._flee_task = asyncio.create_task(self._flee())

        super().__init__(timeout=None)
        self.children[0].label = f'Throw a Poké Ball!'
        self.children[0].emoji = discord.PartialEmoji(name="pokeball", id=pokeball_emoji_id)

    async def _flee(self):
        delay = (self.flee_time - datetime.now()).total_seconds()
        await asyncio.sleep(max(delay, 0))

        if self.claimed:
            return

        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)
            await self.message.reply(f'Wild {self.spawned_pokemon_name} fled!')

        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.primary)
    async def button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        async with self.claim_lock:
            if datetime.now() >= self.flee_time or self.claimed:
                await interaction.response.send_message(f'Too slow!', ephemeral=True)
                return

            user_id = interaction.user.id
            now = time.monotonic()

            last_click, last_msg = self.cooldowns.get(user_id, (0, None))
            remaining = catch_cooldown_sec - (now - last_click)

            if last_msg:
                # Need to acknowledge the interaction within 3 seconds or discord invalidates
                await interaction.response.defer()
                if remaining > 0:
                    try:
                        await last_msg.edit(content=f':hourglass: Slow down! Try again in {remaining:.1f}s.')
                    except discord.NotFound:
                        pass
                    return
                else:
                    try:
                        await last_msg.delete()
                    except discord.NotFound:
                        pass

            # Attempt to catch
            roll = random.randint(1, 100)
            current_rate = await _calculate_user_catch_rate(
                attempts=self.attempts[user_id],
                base=self.spawned_pokemon_catch_percent,
                scaling_rate=self.spawned_pokemon_catch_scaling,
                user_id=user_id,
                guild_id=interaction.guild.id
            )

            success = roll <= current_rate
            logger.debug(f'{interaction.user.display_name} Rolled: {roll}, Required: {current_rate} or lower')
            self.attempts[user_id] += 1

            if success:
                try:
                    await database.add_user_pokemon(
                        interaction.user.id,
                        interaction.guild_id,
                        self.spawned_pokemon_id,
                        self.spawned_pokemon_name,
                        self.is_shiny
                    )
                except Exception as e:
                    logger.error(f"Failed to add {'shiny ' if self.is_shiny else ''}{self.spawned_pokemon_name} to user {interaction.user.id}: {e}")
                    return

                # Update the cache
                database.increment_pokemon_count(interaction.user.id, interaction.guild_id)

                self.claimed = True
                button.disabled = True
                if last_msg:
                    await interaction.edit_original_response(view=self)
                else:
                    await interaction.response.edit_message(view=self)
                self.cooldowns = {}
                shiny_emoji = ' :sparkles: ' if self.is_shiny else ''

                # Collect stats for this Pokémon
                total_attempts = sum(self.attempts.values())
                num_users = len(self.attempts)

                attempts_lines_list = []
                for user_id, count in sorted(self.attempts.items(), key=lambda x: x[1], reverse=True):
                    member = await interaction.guild.fetch_member(user_id)
                    display_name = member.display_name
                    attempts_lines_list.append(f"- {display_name}: {count} attempt{'s' if count != 1 else ''}")

                attempts_lines = "\n".join(attempts_lines_list)
                attempts_summary = f"\n\n**:busts_in_silhouette: {num_users} user{'s' if num_users != 1 else ''} tried {total_attempts} time{'s' if total_attempts != 1 else ''} total**\n{attempts_lines}"

                message_string = (
                    f"### Gotcha! {shiny_emoji}{self.spawned_pokemon_name}{shiny_emoji} was caught by "
                    f"{interaction.user.display_name}, beating the {current_rate}% odds!{attempts_summary}"
                )

                await interaction.followup.send(message_string)
                logger.info(f"{'Shiny ' if self.is_shiny else ''}{self.spawned_pokemon_name} was caught by {interaction.user.display_name}")
            else:
                message_string = f'Oh no! The Pokémon broke free! You rolled {roll}. Required {current_rate} or lower.'
                if last_msg:
                    sent_msg = await interaction.followup.send(message_string, ephemeral=True)
                else:
                    await interaction.response.send_message(message_string, ephemeral=True)
                    sent_msg = await interaction.original_response()

                # Store the time and message object
                self.cooldowns[user_id] = (now, sent_msg)
