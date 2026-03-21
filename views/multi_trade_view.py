import aiosqlite
import asyncio
import logging
import os

import database

import discord
from dotenv import load_dotenv

load_dotenv()
log_level               = int(os.getenv('LOG_LEVEL'))
trade_window_seconds    = int(os.getenv('TRADE_WINDOW_SECONDS'))

# Init logging to discord.log
logger = logging.getLogger('MultiTradeView')
logger.setLevel(log_level)

class MultiTradeView(discord.ui.View):

    def __init__(self, log_handler, offer_user_id, offer_pokemon_list, want_pokemon_list, offer_gallery, want_gallery):
        # offer_pokemon_list / want_pokemon_list: list of dicts with keys:
        #   national_dex_number, is_shiny, name

        if log_handler:
            logger.addHandler(log_handler)

        self.message = None # Set after sending the view
        self.complete = False
        self.claim_lock = asyncio.Lock()

        self.offer_user_id = offer_user_id
        self.offer_pokemon_list = offer_pokemon_list
        self.want_pokemon_list = want_pokemon_list
        self.offer_gallery = offer_gallery
        self.want_gallery = want_gallery

        super().__init__(timeout=trade_window_seconds)

    async def end_trade(self, end_label):
        if self.complete:
            return
        self.complete = True

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == 'mt_accept_button':
                    item.label = end_label
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)

    async def on_timeout(self):
        await self.end_trade('Expired')
        logger.info(
            f'{self.offer_user_id} multitrade expired: '
            f'OFFER{[(p["national_dex_number"], p["is_shiny"]) for p in self.offer_pokemon_list]}, '
            f'WANT{[(p["national_dex_number"], p["is_shiny"]) for p in self.want_pokemon_list]}'
        )

    @discord.ui.button(label='Accept', style=discord.ButtonStyle.success, custom_id='mt_accept_button')
    async def trade_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.claim_lock:
            if self.complete:
                await interaction.response.send_message('This trade is no longer available', ephemeral=True)
                return

            await interaction.response.defer()

            if self.offer_user_id == interaction.user.id:
                await interaction.followup.send('You are the owner of this trade', ephemeral=True)
                return

            try:
                await database.trade_pokemon_multi(
                    interaction.guild_id,
                    self.offer_user_id,
                    interaction.user.id,
                    [(p['national_dex_number'], p['is_shiny']) for p in self.offer_pokemon_list],
                    [(p['national_dex_number'], p['is_shiny']) for p in self.want_pokemon_list],
                )

                # Count for both users has been updated, invalidate the cache
                database.invalidate_pokemon_count(interaction.user.id, interaction.guild_id)
                database.invalidate_pokemon_count(self.offer_user_id, interaction.user.id)

                logger.info(
                    f'{interaction.user.id} accepted multitrade from {self.offer_user_id}: '
                    f'receives {[(p["national_dex_number"], p["is_shiny"]) for p in self.offer_pokemon_list]}, '
                    f'gives {[(p["national_dex_number"], p["is_shiny"]) for p in self.want_pokemon_list]}'
                )

                await self.end_trade('Completed')

                await interaction.followup.send('Trade successful!', ephemeral=True)
                try:
                    offer_user = await interaction.client.fetch_user(self.offer_user_id)
                    await offer_user.send(
                        f'Your multitrade offer was accepted!\n\n'
                        f'**You gave:**\n{self.offer_gallery}\n\n'
                        f'**You received:**\n{self.want_gallery}'
                    )
                except discord.Forbidden:
                    pass

            except ValueError as e:
                await interaction.followup.send(f'Trade failed: {e}', ephemeral=True)

            except aiosqlite.Error as e:
                await interaction.followup.send('A database error occurred. Please try again later.', ephemeral=True)
                logging.error('DB error during multitrade', exc_info=e)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.claim_lock:
            if self.complete:
                await interaction.response.send_message('This trade is no longer available', ephemeral=True)
                return

            await interaction.response.defer()
            if self.offer_user_id != interaction.user.id:
                await interaction.followup.send('You are not the owner of this trade', ephemeral=True)
                return

            await self.end_trade('Cancelled')
            logger.info(f'{interaction.user.id} cancelled their multitrade')