import asyncio
import database
import logging
import os
import random
import time

import discord

from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
log_level                   = int(os.getenv('LOG_LEVEL'))
catch_cooldown_sec          = int(os.getenv('CATCH_COOLDOWN_SECONDS'))
catch_window_sec            = int(os.getenv('CATCH_WINDOW_SECONDS'))

# Init logging to discord.log
logger = logging.getLogger('CatchView')
logger.setLevel(log_level)

class CatchView(discord.ui.View):

    def __init__(self, log_handler, spawned_pokemon_id, spawned_pokemon_name, spawned_pokemon_catch_percent, sprite_url, is_shiny):

        if log_handler:
            logger.addHandler(log_handler)

        self.message = None # Set after sending the view
        self.cooldowns = {} # user_id -> (last_click_time, last_message)
        self.claimed = False
        self.claim_lock = asyncio.Lock()

        # Details of the Pokémon available for catching
        self.spawned_pokemon_id = spawned_pokemon_id
        self.spawned_pokemon_name = spawned_pokemon_name
        self.spawned_pokemon_catch_percent = spawned_pokemon_catch_percent
        self.sprite_url = sprite_url
        self.is_shiny = is_shiny

        self.flee_time = datetime.now() + timedelta(seconds=catch_window_sec)
        self._flee_task = asyncio.create_task(self._flee())

        super().__init__(timeout=None)

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

    @discord.ui.button(label='Throw a Poké Ball!', style=discord.ButtonStyle.primary)
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
            success = roll <= self.spawned_pokemon_catch_percent
            logger.debug(f'{interaction.user.display_name} Rolled: {roll}, Required: {self.spawned_pokemon_catch_percent} or lower')

            if success:
                try:
                    await database.add_user_pokemon(
                        interaction.user.id,
                        self.spawned_pokemon_id,
                        self.spawned_pokemon_name,
                        self.sprite_url,
                        self.is_shiny
                    )
                except Exception as e:
                    logger.error(f'Failed to add {self.spawned_pokemon_name} to user {interaction.user.id}: {e}')
                    return

                self.claimed = True
                button.disabled = True
                if last_msg:
                    await interaction.edit_original_response(view=self)
                else:
                    await interaction.response.edit_message(view=self)
                self.cooldowns = {}
                message_string = f'Gotcha! {self.spawned_pokemon_name} was caught by {interaction.user.display_name}!'
                await interaction.followup.send(message_string)
                logger.info(f'{self.spawned_pokemon_name} was caught by {interaction.user.display_name}')
            else:
                message_string = 'Aww! It appeared to be caught!'
                if last_msg:
                    sent_msg = await interaction.followup.send(message_string, ephemeral=True)
                else:
                    await interaction.response.send_message(message_string, ephemeral=True)
                    sent_msg = await interaction.original_response()

                # Store the time and message object
                self.cooldowns[user_id] = (now, sent_msg)