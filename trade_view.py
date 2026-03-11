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
logger = logging.getLogger('TradeView')
logger.setLevel(log_level)

class TradeView(discord.ui.View):

    def __init__(self, log_handler, offer_user_id, offer_dex_num, offer_is_shiny, want_dex_num, want_is_shiny):

        if log_handler:
            logger.addHandler(log_handler)

        self.message = None # Set after sending the view
        self.complete = False
        self.claim_lock = asyncio.Lock()

        self.offer_user_id = offer_user_id
        self.offer_dex_num = offer_dex_num
        self.offer_is_shiny = offer_is_shiny
        self.want_dex_num = want_dex_num
        self.want_is_shiny = want_is_shiny

        super().__init__(timeout=trade_window_seconds)

    async def end_trade(self, end_label):
        if self.complete:
            return
        self.complete = True

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == 'accept_button':
                    item.label = end_label
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)

    async def on_timeout(self):
        await self.end_trade('Expired')
        logger.info(f'{self.offer_user_id} trade expired: OFFER[shiny={self.offer_is_shiny} num={self.offer_dex_num}], WANTED[shiny={self.want_is_shiny} num={self.want_dex_num}]')

    @discord.ui.button(label='Accept', style=discord.ButtonStyle.success, custom_id='accept_button')
    async def trade_button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        async with self.claim_lock:
            if self.complete:
                await interaction.response.send_message(f'This trade is no longer available', ephemeral=True)
                return

            await interaction.response.defer() # In case the db work takes too long

            if self.offer_user_id == interaction.user.id:
                await interaction.followup.send(f"You are the owner of this trade", ephemeral=True)
                return

            try:
                await database.trade_pokemon(
                    self.offer_user_id,
                    interaction.user.id,
                    self.offer_dex_num,
                    self.want_dex_num,
                    self.offer_is_shiny,
                    self.want_is_shiny
                )
                await self.end_trade('Completed')
                await interaction.followup.send("Trade successful!")
                logger.info(f'{interaction.user.id} receives shiny={self.offer_is_shiny} num={self.offer_dex_num}, {self.offer_user_id} receives shiny={self.want_is_shiny} num={self.want_dex_num}')

                # TODO Maybe add a transactions table to record trades?

            except ValueError as e:
                await interaction.followup.send(f"Trade failed: {e}", ephemeral=True)

            except aiosqlite.Error as e:
                await interaction.followup.send("A database error occurred. Please try again later.", ephemeral=True)
                logging.error("DB error during trade", exc_info=e)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel_button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        async with self.claim_lock:
            if self.complete:
                await interaction.response.send_message(f'This trade is no longer available', ephemeral=True)
                return

            await interaction.response.defer()
            if self.offer_user_id != interaction.user.id:
                await interaction.followup.send(f"You are not the owner of this trade", ephemeral=True)
                return

            await self.end_trade('Cancelled')
            logger.info(f'{interaction.user.id} cancelled their trade: OFFER[shiny={self.offer_is_shiny} num={self.offer_dex_num}], WANTED[shiny={self.want_is_shiny} num={self.want_dex_num}]')

