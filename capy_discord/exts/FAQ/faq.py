import logging

import discord
from discord import app_commands
from discord import channel
from discord.ext import commands
from discord.interactions import Interaction

from capy_discord.ui.embeds import info_embed
from capy_discord.database import get_database_pool, BackendAPIError
from capy_discord.ui.embeds import info_embed, error_embed, success_embed
  
class FAQ(commands.Cog):
    
    
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.log = logging.getLogger("FAQ")    
    @app_commands.command(name="faq_create", description="Create an FAQ") #TODO: faq_create
    async def faq_create(self, interact: Interaction,question:str,answer:str) -> None:   
        await interact.response.defer(ephemeral=True)
        client = get_database_pool()
        
        try:
            faqs = await client.list_faqs(question=question.lower())
            if faqs and faqs[0]['question'] == question.lower():
                faq_id = faqs[0]['fid']
                await client.update_faq(faq_id, {"answer": answer})
                msg = f"Updated FAQ: **{question}**"
            else:
                await client.create_faq({"question": question.lower(), "answer": answer})
                msg = f"Added FAQ: **{question}**"
                
            await interact.followup.send(embed=success_embed("FAQ Management", msg))
            
                
        except BackendAPIError as e:
            self.log.exception("Failed to add/update FAQ")
            await interact.followup.send(embed=error_embed("Database Error", "Failed to save the FAQ entry."))  
    
    
    @app_commands.commands(name="faq_read", description="Read an FAQ") #TODO: faq_read
    async def faq_read(self, interact: Interaction, question:str) -> None:
        client = get_database_pool()
        try:
            faqs = await client.list_faqs(question=question.lower())
            faq_item = next((f for f in faqs if f["question"].lower() == question.lower()), None)

            if faq_item:
                await interact.response.send_message(
                    embed=info_embed(f"**{faq_item['question'].title()}**", description=faq_item['answer']),
                    ephemeral=True
                )
            else:
                await interact.response.send_message(embed=error_embed("FAQ Not Found", "No matching FAQ entry found."), ephemeral=True)
        except BackendAPIError as e:
            self.log.exception("Failed to retrieve FAQ")
            await interact.response.send_message(embed=error_embed("Database Error", "Failed to retrieve the FAQ entry."), ephemeral=True)
    
    
    @app_commands.command(name="faq_update", description="Update an FAQ") #TODO: faq_update
    async def faq_update(self, interact: Interaction, question:str, answer:str) -> None:
        await interact.response.defer(ephemeral=True)
        client = get_database_pool()
        try:
            faqs = await client.list_faqs(question=question.lower())
            faq_item = next((f for f in faqs if f["question"].lower() == question.lower()), None)

            if faq_item:
                faq_id = faq_item['fid']
                await client.update_faq(faq_id, {"answer": answer})
                await interact.followup.send(embed=success_embed("FAQ Management", f"Updated FAQ: **{question}**"))
            else:
                await interact.followup.send(embed=error_embed("FAQ Not Found", "No matching FAQ entry found."))
        except BackendAPIError as e:
            self.log.exception("Failed to update FAQ")
            await interact.followup.send(embed=error_embed("Database Error", "Failed to update the FAQ entry."))
    
    
    @app_commands.command(name="faq_delete", description="Delete an FAQ") #TODO: faq_delete
    async def faq_delete(self, interact: Interaction, question:str) -> None:
        await interact.response.defer(ephemeral=True)
        client = get_database_pool()
        try:
            faqs = await client.list_faqs(question=question.lower())
            faq_item = next((f for f in faqs if f["question"].lower() == question.lower()), None)

            if faq_item:
                await client.delete_faq(faq_item['fid'])
                await interact.followup.send(embed=success_embed("FAQ Management", f"Deleted FAQ: **{question}**"))
            else:
                await interact.followup.send(embed=error_embed("FAQ Not Found", "No matching FAQ entry found."))
        except BackendAPIError as e:
            self.log.exception("Failed to delete FAQ")
            await interact.followup.send(embed=error_embed("Database Error", "Failed to delete the FAQ entry."))
    
    
async def setup(bot: commands.Bot) -> None:
    """Set up the FAQ cog."""
    await bot.add_cog(FAQ(bot))