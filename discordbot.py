#!/usr/bin/env python3

import discord
import random

TOKEN = None

with open('discordtoken.txt', 'r') as f:
    TOKEN = f.read().strip()

client = discord.Client()

@client.event
async def on_message(message):
    if message.author == client.user:
        return
        
    if message.content == "!d20":
        msg = "{} rolled a d20 and got {}".format(message.author.mention, random.randint(1,20))
        await client.send_message(message.channel, msg)
        print(message.author, message.content)
        
@client.event
async def on_ready():
    print("Logged in as %s %s" % (client.user.name, client.user.id))
    
client.run(TOKEN)