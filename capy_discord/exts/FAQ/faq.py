import logging

import discord
from discord import app_commands
from discord import channel
from discord.ext import commands
from discord.interactions import Interaction

from capy_discord.ui.embeds import info_embed
from capy_discord.database import get_database_pool, BackendAPIError
from capy_discord.ui.embeds import info_embed, error_embed, success_embed

# class FAQ(commands.Cog):
#     def __init__(self, bot: commands.Bot) -> None:
#         self.bot = bot
#         self.storage_tag = "--- FAQ STORAGE ---"
#         self.faq_cache = {}  # This is where we'll keep the FAQs in memory
#         self.storage_channel_id = 1484656929455214803  # Replace with channel ID
#     async def _get_or_create_storage(self) -> discord.Message:
#         channel = self.bot.get_channel(self.storage_channel_id)     
#         async for message in channel.history(limit=100):
#             if message.author == self.bot.user and message.content.startswith(self.storage_tag):
#                 return message
#         initial_content = f"{self.storage_tag}\n"  # Start with the tag and a newline
#         return await channel.send(initial_content) #send storage message if not found
        
#     async def _load_faqs(self) -> None:
#         message = await self._get_or_create_storage()
#         self.faq_cache = {}
#         lines = message.content.splitlines()[1:]  # Skip the first line (the tag
#         for line in lines:
#             if ": " in line:
#                 question, answer = line.split(": ", 1)
#                 self.faq_cache[question.strip()] = answer.strip()
    
#     async def _save_faqs(self) -> None:
#         message = await self._get_or_create_storage()
        
#         lines = [self.storage_tag]  # Start with the tag
#         for question, answer in self.faq_cache.items():
#             lines.append(f"{question}: {answer}")
        
#         new_faq = '\n'.join(lines)
#         await message.edit(content=new_faq)
        
#     @app_commands.command(name="faq_add", description="Add a question and answer to the FAQ")
#     # @app_commands.check.has_permissions(administrator=True)
#     async def faq_add(self, interact: discord.Interaction, question: str, answer: str) -> None:
#         self.faq_cache[question.lower()] = answer
#         await interact.response.send_message(embed=info_embed(f"Added FAQ: **{question}**", description="Add a question and answer to the FAQ"), ephemeral=True)
#         await self._save_faqs()
    
    
#     @app_commands.command(name="faq", description="Get the answer to a question from the FAQ")
#     async def faq(self, interact: discord.Interaction, question: str) -> None:
#         answer = self.faq_cache.get(question.lower())
#         if answer:
#             await interact.response.send_message(embed=info_embed(f"**{question}**\n{answer}", description="Add a question and answer to the FAQ"), ephemeral=True)
#         else:
#             await interact.response.send_message(embed=info_embed("Question not found in FAQ.", description="Add a question and answer to the FAQ"), ephemeral=True)

#     @app_commands.command(name="faq_remove", description="Remove a question and answer from the FAQ")
#     # @app_commands.check.has_permissions(administrator=True)
#     async def faq_remove(self, interact: discord.Interaction, question: str) -> None:
#         print(self.faq_cache)
#         del self.faq_cache[question.lower()]
#         await interact.response.send_message(embed=info_embed(f"Removed FAQ: **{question}**", description="Removed a question and answer from the FAQ"), ephemeral=True)
#         await self._save_faqs()


#     @app_commands.command(name="faq_make",description="Make a FAQ channel")
#     async def faq_make(self, interact: discord.Interaction) -> None:
#         guild = interact.guild
#         new_channel = await guild.create_text_channel(
#             name="FAQ",
#             reason=f"Channel requested by {interact.user.name}" # Shows up in the Audit Log
#         )
#         self.storage_channel_id = new_channel.id
#         await interact.response.send_message(embed=info_embed(f"FAQ channel created: {new_channel.mention}", description="Add a question and answer to the FAQ"), ephemeral=True)
        
class FAQ(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.log = logging.getLogger("FAQ")    
    @app_commands.command(name="faq_create", description="Create an FAQ") #TODO: faq_create
    async def faq_create(self, interact: Interaction,question:str,answer:str) -> None:   
        await interact.response.defer(ephemeral=True)
        client = get_database_pool()
        
        try:
            faqs = client.list_faqs(question=question.lower())
            if faqs and faqs[0]['question'] == question.lower():
                faq_id = faqs[0]['fid']
                
        except BackendAPIError as e:
            self.log.exception("Failed to add/update FAQ")
            await interact.followup.send(embed=error_embed("Database Error", "Failed to save the FAQ entry."))
        
        return  
    
    
    @app_commands.commands(name="faq_read", description="Read an FAQ") #TODO: faq_read
    async def faq_read(self, interact: Interaction, question:str) -> None:
        return
    
    
    @app_commands.command(name="faq_update", description="Update an FAQ") #TODO: faq_update
    async def faq_update(self, interact: Interaction, question:str, answer:str) -> None:
        return
    
    
    @app_commands.command(name="faq_delete", description="Delete an FAQ") #TODO: faq_delete
    async def faq_delete(self, interact: Interaction, question:str) -> None:
        return
    
    
async def setup(bot: commands.Bot) -> None:
    """Set up the FAQ cog."""
    await bot.add_cog(FAQ(bot))