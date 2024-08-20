import os
import requests
from discord.ext import commands, tasks
import discord
import json
from configparser import ConfigParser
from difflib import get_close_matches
from datetime import datetime, timezone
import string
from discord.ext.commands import DefaultHelpCommand

# Load configuration from config.ini
config = ConfigParser()
config.read('config.ini')

# Read the Discord bot token and channel IDs from the config file
DISCORD_TOKEN = config.get('discord', 'token')
CHANNEL_IDS = config.get('discord', 'channel_ids', fallback="").split(',')
COMMAND_PREFIX = config.get('discord', 'prefix', fallback="!").split(',')

# Convert channel IDs to integers and filter out any empty strings
CHANNEL_IDS = [int(id.strip()) for id in CHANNEL_IDS if id.strip()]

API_URL = 'https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/spark-tracks'
MODES_SMART_URL = 'https://api.nitestats.com/v1/epic/modes-smart'
SHOP_API_URL = 'https://fortnite-api.com/v2/shop'
SONGS_FILE = 'known_songs.json'  # File to save known songs

# Set up Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent

class CustomHelpCommand(DefaultHelpCommand):
    def __init__(self):
        super().__init__()
        self.no_category = 'Available Commands'
        self.command_attrs['help'] = 'Shows this help message'

    async def send_bot_help(self, mapping):
        embed = discord.Embed(
            title="Festival Tracker Help",
            description="A simple bot to check Fortnite Festival song data. [Source](https://github.com/hmxmilohax/festivalinfobot)",
            color=0x8927A1
        )

        for cog, commands in mapping.items():
            if cog:
                name = cog.qualified_name
                filtered = await self.filter_commands(commands, sort=True)
                if filtered:
                    value = '\n'.join([f"`{COMMAND_PREFIX[0]}{cmd.name}`: {cmd.short_doc}" for cmd in filtered])
                    embed.add_field(name=name, value=value, inline=False)
            else:
                filtered = await self.filter_commands(commands, sort=True)
                if filtered:
                    value = '\n'.join([f"`{COMMAND_PREFIX[0]}{cmd.name}`: {cmd.short_doc}" for cmd in filtered])
                    embed.add_field(name=self.no_category, value=value, inline=False)

        embed.set_footer(text=f"Type {COMMAND_PREFIX[0]}help <command> for more details on a command.")
        channel = self.get_destination()
        await channel.send(embed=embed)

    async def send_command_help(self, command):
        embed = discord.Embed(
            title=f"Help with `{COMMAND_PREFIX[0]}{command.name}`",
            description=command.help or "No description provided.",
            color=0x8927A1
        )

        # Properly format the usage with the command signature
        usage = f"`{COMMAND_PREFIX[0]}{command.qualified_name} {command.signature}`" if command.signature else f"`{COMMAND_PREFIX[0]}{command.qualified_name}`"
        embed.add_field(name="Usage", value=usage, inline=False)

        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(command.aliases), inline=False)

        channel = self.get_destination()
        await channel.send(embed=embed)

bot = commands.Bot(
    command_prefix=COMMAND_PREFIX, 
    intents=intents, 
    help_command=CustomHelpCommand()
)

class PaginatorView(discord.ui.View):
    def __init__(self, embeds, user_id):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.user_id = user_id
        self.current_page = 0
        self.total_pages = len(embeds)
        self.add_buttons()

    def add_buttons(self):
        self.clear_items()
        # "First" button
        self.add_item(FirstButton(style=discord.ButtonStyle.primary, label='First', user_id=self.user_id))
        
        # "Previous" button
        if self.current_page > 0:
            self.add_item(PreviousButton(style=discord.ButtonStyle.primary, label='Previous', user_id=self.user_id))
        else:
            self.add_item(PreviousButton(style=discord.ButtonStyle.secondary, label='Previous', disabled=True, user_id=self.user_id))

        # "Page#" button
        self.add_item(PageNumberButton(label=f"Page {self.current_page + 1}/{self.total_pages}", user_id=self.user_id))

        # "Next" button
        if self.current_page < self.total_pages - 1:
            self.add_item(NextButton(style=discord.ButtonStyle.primary, label='Next', user_id=self.user_id))
        else:
            self.add_item(NextButton(style=discord.ButtonStyle.secondary, label='Next', disabled=True, user_id=self.user_id))
        
        # "Last" button
        self.add_item(LastButton(style=discord.ButtonStyle.primary, label='Last', user_id=self.user_id))

    def get_embed(self):
        return self.embeds[self.current_page]

    def update_buttons(self):
        self.add_buttons()

    async def on_timeout(self):
        try:
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)
        except discord.NotFound:
            print("Message was not found when trying to edit after timeout.")
        except Exception as e:
            print(f"An error occurred during on_timeout: {e}")

class FirstButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id')
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(f"This is not your session. Please use the {COMMAND_PREFIX[0]}tracklist command to start your own session.", ephemeral=True)
            return
        view: PaginatorView = self.view
        view.current_page = 0
        embed = view.get_embed()
        view.update_buttons()
        await interaction.response.edit_message(embed=embed, view=view)

class PreviousButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id')
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(f"This is not your session. Please use the {COMMAND_PREFIX[0]}tracklist command to start your own session.", ephemeral=True)
            return
        view: PaginatorView = self.view
        view.current_page -= 1
        embed = view.get_embed()
        view.update_buttons()
        await interaction.response.edit_message(embed=embed, view=view)

class PageNumberButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id')
        super().__init__(*args, **kwargs)

class NextButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id')
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(f"This is not your session. Please use the {COMMAND_PREFIX[0]}tracklist command to start your own session.", ephemeral=True)
            return
        view: PaginatorView = self.view
        view.current_page += 1
        embed = view.get_embed()
        view.update_buttons()
        await interaction.response.edit_message(embed=embed, view=view)

class LastButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id')
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(f"This is not your session. Please use the {COMMAND_PREFIX[0]}tracklist command to start your own session.", ephemeral=True)
            return
        view: PaginatorView = self.view
        view.current_page = view.total_pages - 1
        embed = view.get_embed()
        view.update_buttons()
        await interaction.response.edit_message(embed=embed, view=view)

def remove_punctuation(text):
    return text.translate(str.maketrans('', '', string.punctuation))

def fuzzy_search_tracks(tracks, search_term):
    # Remove punctuation from the search term
    search_term = remove_punctuation(search_term.lower())  # Case-insensitive search
    exact_matches = []
    fuzzy_matches = []
    
    for track in tracks.values():
        title = remove_punctuation(track['track']['tt'].lower())
        artist = remove_punctuation(track['track']['an'].lower())
        
        # Check for exact matches first
        if search_term in title or search_term in artist:
            exact_matches.append(track)
        # Use fuzzy matching for close but not exact matches
        elif any(get_close_matches(search_term, [title, artist], n=1, cutoff=0.7)):
            fuzzy_matches.append(track)
    
    # Prioritize exact matches over fuzzy matches
    return exact_matches if exact_matches else fuzzy_matches

def fetch_available_jam_tracks():
    try:
        response = requests.get(API_URL)
        data = response.json()

        # Ensure that the data is a dictionary and filter tracks that have the "track" property
        if isinstance(data, dict):
            available_tracks = {}
            for k, v in data.items():
                if isinstance(v, dict) and 'track' in v:
                    # Remove trailing spaces from relevant fields
                    v['track']['an'] = v['track']['an'].strip()
                    v['track']['tt'] = v['track']['tt'].strip()
                    available_tracks[k] = v
            return available_tracks
        else:
            print('Unexpected data format')
            return None
    except Exception as e:
        print(f'Error fetching available jam tracks: {e}')
        return None

def fetch_daily_shortnames():
    try:
        response = requests.get(MODES_SMART_URL)
        data = response.json()

        channels = data.get('channels', {})
        client_events_data = channels.get('client-events', {})
        states = client_events_data.get('states', [])

        # Current date with timezone awareness
        current_time = datetime.now(timezone.utc)
        
        # Filter and sort the states by validFrom date
        valid_states = [state for state in states if datetime.fromisoformat(state['validFrom'].replace('Z', '+00:00')) <= current_time]
        valid_states.sort(key=lambda x: datetime.fromisoformat(x['validFrom'].replace('Z', '+00:00')), reverse=True)

        if not valid_states:
            print("No valid states found")
            return None

        # Get the activeEvents from the most recent valid state
        active_events = valid_states[0].get('activeEvents', [])

        daily_tracks = {}
        for event in active_events:
            event_type = event.get('eventType', '')
            active_since = event.get('activeSince', '')
            active_until = event.get('activeUntil', '')

            # Convert dates to timezone-aware datetime objects
            active_since_date = datetime.fromisoformat(active_since.replace('Z', '+00:00')) if active_since else None
            active_until_date = datetime.fromisoformat(active_until.replace('Z', '+00:00')) if active_until else None

            if event_type.startswith('PilgrimSong.') and active_since_date and active_until_date:
                # Check if the current date falls within the active period
                if active_since_date <= current_time <= active_until_date:
                    shortname = event_type.replace('PilgrimSong.', '')
                    daily_tracks[shortname] = {
                        'activeSince': active_since,
                        'activeUntil': active_until
                    }

        return daily_tracks

    except Exception as e:
        print(f'Error fetching daily shortnames: {e}')
        return None

def generate_shop_tracks_embeds(tracks, title, chunk_size=5):
    embeds = []

    for i in range(0, len(tracks), chunk_size):
        embed = discord.Embed(title=title, color=0x8927A1)
        chunk = tracks[i:i + chunk_size]
        for track in chunk:
            # Convert duration from seconds to a more readable format
            duration_minutes = track['duration'] // 60
            duration_seconds = track['duration'] % 60
            duration_str = f"{duration_minutes}m {duration_seconds}s"

            # Convert inDate and outDate to Discord timestamp format
            in_date_ts = int(datetime.fromisoformat(track['inDate'].replace('Z', '+00:00')).timestamp()) if track.get('inDate') else None
            out_date_ts = int(datetime.fromisoformat(track['outDate'].replace('Z', '+00:00')).timestamp()) if track.get('outDate') else None
            
            in_date_display = f"<t:{in_date_ts}:R>" if in_date_ts else "Unknown"
            out_date_display = f"<t:{out_date_ts}:R>" if out_date_ts else "Unknown"

            # Inline difficulty as boxes
            difficulty = track['difficulty']
            difficulty_str = (
                f"Lead: {generate_difficulty_bar(difficulty.get('guitar', 0))} "
                f"Bass: {generate_difficulty_bar(difficulty.get('bass', 0))} "
                f"Drums: {generate_difficulty_bar(difficulty.get('drums', 0))} "
                f"Vocals: {generate_difficulty_bar(difficulty.get('vocals', 0))} "
            )

            embed.add_field(name="", value="\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\n", inline=False)
            embed.add_field(
                name="",
                value=(
                    f"{track['title']} *{track['artist']}*, {track['releaseYear']} - {duration_str}\n"
                    f"Added {in_date_display} - Leaving {out_date_display}\n"
                    f"`{difficulty_str}`"
                ),
                inline=False
            )
        embeds.append(embed)

    return embeds

def generate_tracks_embeds(tracks, title, daily_shortnames, chunk_size=5):
    embeds = []
    
    for i in range(0, len(tracks), chunk_size):
        embed = discord.Embed(title=title, color=0x8927A1)
        chunk = tracks[i:i + chunk_size]
        for track in chunk:
            shortname = track['track']['sn']
            active_until = daily_shortnames.get(shortname)

            if active_until:
                active_until_date = datetime.fromisoformat(active_until.replace('Z', '+00:00'))
                human_readable_until = active_until_date.strftime("%B %d, %Y, %I:%M %p UTC")
                embed.add_field(name="", value=f"{track['track']['tt']} - *{track['track']['an']}*\nLeaving {human_readable_until}", inline=False)
            else:
                embed.add_field(name="", value=f"{track['track']['tt']} - *{track['track']['an']}*", inline=False)
        embeds.append(embed)
    
    return embeds

def generate_difficulty_bar(difficulty, max_blocks=7):
    # Map difficulty from a 0-6 range to a 1-7 range
    scaled_difficulty = difficulty + 1  # Convert 0-6 range to 1-7
    filled_blocks = '■' * scaled_difficulty
    empty_blocks = '□' * (max_blocks - scaled_difficulty)
    return filled_blocks + empty_blocks

def generate_track_embed(track_data, is_new=False):
    track = track_data['track']
    title = f"New song found:\n{track['tt']}" if is_new else track['tt']
    placeholder_id = track.get('ti', 'sid_placeholder_00').split('_')[-1].zfill(2)  # Extract the placeholder ID
    embed = discord.Embed(title="", description=f"**{title}** - *{track['an']}*", color=0x8927A1)
    
    # Add various fields to the embed
    embed.add_field(name="\n", value="", inline=False)
    embed.add_field(name="Release Year", value=track['ry'], inline=True)
    embed.add_field(name="Album", value=track.get('ab', 'N/A'), inline=True)
    embed.add_field(name="Genre", value=", ".join(track.get('ge', ['N/A'])), inline=True)
    embed.add_field(name="Duration", value=f"{track['dn'] // 60}m {track['dn'] % 60}s", inline=True)
    embed.add_field(name="Shortname", value=track['sn'], inline=True)
    embed.add_field(name="Song ID", value=f"{placeholder_id}", inline=True)
    embed.add_field(name="Key", value=f'{track["mk"]} {track["mm"]}', inline=True)
    embed.add_field(name="BPM", value=track["mt"], inline=True)
    
    # Add Last Modified field if it exists and format it to be more human-readable
    if 'lastModified' in track_data:
        last_modified = datetime.fromisoformat(track_data['lastModified'].replace('Z', '+00:00'))
        human_readable_date = last_modified.strftime("%B %d, %Y")
        embed.add_field(name="Last Modified", value=human_readable_date, inline=True)
    
    # Add Song Rating
    rating = track.get('ar', 'N/A')
    if rating == 'T':
        rating_description = 'Mature'
    elif rating == 'E':
        rating_description = 'Everyone'
    else:
        rating_description = 'Unknown'
    
    embed.add_field(name="Rating", value=rating_description, inline=True)
    
    # Difficulty bars
    vocals_diff = track['in'].get('vl', 0)
    guitar_diff = track['in'].get('gr', 0)
    bass_diff = track['in'].get('ba', 0)
    drums_diff = track['in'].get('ds', 0)
    pro_vocals_diff = track['in'].get('pv', 0)
    pro_guitar_diff = track['in'].get('pg', 0)
    pro_bass_diff = track['in'].get('pb', 0)
    pro_drums_diff = track['in'].get('pd', 0)

    # Construct the vertical difficulty bars
    difficulties = (
        f"Lead:      {generate_difficulty_bar(guitar_diff)}\n"
        f"Bass:      {generate_difficulty_bar(bass_diff)}\n"
        f"Drums:     {generate_difficulty_bar(drums_diff)}\n"
        f"Vocals:    {generate_difficulty_bar(vocals_diff)}\n"
        f"Pro Lead:  {generate_difficulty_bar(pro_guitar_diff)}\n"
        f"Pro Bass:  {generate_difficulty_bar(pro_bass_diff)}\n"
        f"Pro Drums: {generate_difficulty_bar(pro_drums_diff)}"
    )

    # Add difficulties to embed
    embed.add_field(name="Difficulties", value=f"```{difficulties}```", inline=False)
    
    # Add the album art
    embed.set_thumbnail(url=track['au'])
    
    return embed

def save_known_songs_to_disk(songs):
    with open(SONGS_FILE, 'w') as file:
        json.dump(list(songs), file)

def load_known_songs_from_disk():
    if os.path.exists(SONGS_FILE):
        with open(SONGS_FILE, 'r') as file:
            return set(json.load(file))
    return set()

def fetch_shop_tracks():
    try:
        response = requests.get(SHOP_API_URL)
        data = response.json()

        # Check if 'data' and 'entries' keys exist in the response
        if 'data' in data and 'entries' in data['data']:
            entries = data['data']['entries']
            available_tracks = {}

            for entry in entries:
                in_date = entry.get('inDate')
                out_date = entry.get('outDate')
                
                if entry.get('tracks'):
                    for track in entry['tracks']:
                        dev_name = track.get("devName")
                        if dev_name and 'sid_placeholder' in track['id']:
                            if dev_name not in available_tracks:
                                available_tracks[dev_name] = {
                                    "id": track["id"],
                                    "devName": dev_name,
                                    "title": track.get("title", "Unknown Title").strip() if track.get("title") else "Unknown Title",
                                    "artist": track.get("artist", "Unknown Artist").strip() if track.get("artist") else "Unknown Artist",
                                    "releaseYear": track.get("releaseYear", "Unknown Year"),
                                    "duration": track.get("duration", 0),
                                    "difficulty": track.get("difficulty", {}),
                                    "inDate": in_date,  # Assign entry-level inDate
                                    "outDate": out_date  # Assign entry-level outDate
                                }

            if not available_tracks:
                print('No tracks found in the shop.')
                return None

            return available_tracks  # Return dictionary keyed by devName

    except Exception as e:
        print(f'Error fetching shop tracks: {e}')
        return None

@tasks.loop(minutes=15)
async def check_for_new_songs():
    if not CHANNEL_IDS:
        print("No channel IDs provided; skipping the 1-minute probe.")
        return

    tracks = fetch_available_jam_tracks()

    if not tracks:
        print('Could not fetch tracks.')
        return

    # Load known songs from disk (moved here to ensure the latest known songs are loaded)
    known_songs = load_known_songs_from_disk()

    current_songs = {track['track']['sn'] for track in tracks.values()}  # Get shortnames of current songs

    # Find new songs
    new_songs = current_songs - known_songs

    if new_songs:
        print(f"New songs detected: {new_songs}")
        for new_song_sn in new_songs:
            track_data = next((track for track in tracks.values() if track['track']['sn'] == new_song_sn), None)
            if track_data:
                embed = generate_track_embed(track_data, is_new=True)
                for channel_id in CHANNEL_IDS:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)

    # Save the current songs to disk
    save_known_songs_to_disk(current_songs)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    if CHANNEL_IDS:
        check_for_new_songs.start()  # Start the song check loop only if there are channel IDs

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    # Start the song check loop
    check_for_new_songs.start()

@bot.command(name='search', help='Search for a track by name or artist.')
async def search(ctx, *, query: str = None):
    if query is None:
        await ctx.send("Please provide a search term.")
        return
    
    # Fetch the tracks from the jam API
    tracks = fetch_available_jam_tracks()
    if not tracks:
        await ctx.send('Could not fetch tracks.')
        return

    # Fetch the daily shortnames data for later comparison
    daily_shortnames_data = fetch_daily_shortnames()

    # Perform fuzzy search on the fetched tracks
    matched_tracks = fuzzy_search_tracks(tracks, query)
    if not matched_tracks:
        await ctx.send('No tracks found matching your search.')
        return

    # Fetch the shop tracks for later comparison
    shop_tracks = fetch_shop_tracks()

    if len(matched_tracks) == 1:
        embed = generate_track_embed(matched_tracks[0])
        track_devname = matched_tracks[0]['track']['sn']

        # Check if the song is currently in the shop
        if shop_tracks and track_devname in shop_tracks:
            out_date = shop_tracks[track_devname].get('outDate')
            if out_date:
                out_date_ts = datetime.fromisoformat(out_date.replace('Z', '+00:00'))
                human_readable_out_date = out_date_ts.strftime("%B %d, %Y")
                embed.add_field(name="Shop", value=f"Currently in the shop until {human_readable_out_date}.", inline=False)
            else:
                embed.add_field(name="Shop", value="Currently in the shop!", inline=False)

        # Check if the song is currently in the daily rotation
        if daily_shortnames_data and track_devname in daily_shortnames_data:
            active_until = daily_shortnames_data[track_devname]['activeUntil']
            active_until_date = datetime.fromisoformat(active_until.replace('Z', '+00:00'))
            human_readable_until = active_until_date.strftime("%B %d, %Y")
            embed.add_field(name="Daily Jam Track", value=f"Free in daily rotation until {human_readable_until}.", inline=False)

        await ctx.send(embed=embed)
    else:
        # More than one match, prompt user to choose
        options = [f"{i + 1}. **{track['track']['tt']}** by *{track['track']['an']}*" for i, track in enumerate(matched_tracks)]
        options_message = "\n".join(options)
        await ctx.send(f"I found multiple tracks matching your search. Please choose the correct one by typing the number:\n{options_message}")
        
        def check(m):
            return m.author == ctx.author

        try:
            msg = await bot.wait_for("message", check=check, timeout=30)
            if not msg.content.isdigit() or not 1 <= int(msg.content) <= len(matched_tracks):
                await ctx.send("Search cancelled.")
                return

            chosen_index = int(msg.content) - 1
            chosen_track = matched_tracks[chosen_index]
            embed = generate_track_embed(chosen_track)
            track_devname = chosen_track['track']['sn']

            # Check if the song is currently in the shop
            if shop_tracks and track_devname in shop_tracks:
                out_date = shop_tracks[track_devname].get('outDate')
                if out_date:
                    out_date_ts = datetime.fromisoformat(out_date.replace('Z', '+00:00'))
                    human_readable_out_date = out_date_ts.strftime("%B %d, %Y")
                    embed.add_field(name="Shop", value=f"Currently in the shop until {human_readable_out_date}.", inline=False)
                else:
                    embed.add_field(name="Shop", value="Currently in the shop!", inline=False)

            # Check if the song is currently in the daily rotation
            if daily_shortnames_data and track_devname in daily_shortnames_data:
                active_until = daily_shortnames_data[track_devname]['activeUntil']
                active_until_date = datetime.fromisoformat(active_until.replace('Z', '+00:00'))
                human_readable_until = active_until_date.strftime("%B %d, %Y")
                embed.add_field(name="Daily Jam Track", value=f"Free in daily rotation until {human_readable_until}.", inline=False)

            await ctx.send(embed=embed)
        except TimeoutError:
            await ctx.send("You didn't respond in time. Search cancelled.")

@bot.command(name='daily', help='Display the tracks currently in daily rotation.')
async def daily_tracks(ctx):
    tracks = fetch_available_jam_tracks()
    daily_shortnames_data = fetch_daily_shortnames()

    if not tracks or not daily_shortnames_data:
        await ctx.send('Could not fetch tracks or daily shortnames.')
        return
    
    daily_tracks = []
    for track in tracks.values():
        shortname = track['track'].get('sn')

        if shortname in daily_shortnames_data:
            event_data = daily_shortnames_data[shortname]

            # Extract both activeSince and activeUntil from the event_data dictionary
            active_since_iso = event_data.get('activeSince', '')
            active_until_iso = event_data.get('activeUntil', '')

            # Convert to unix timestamps for Discord
            active_until_ts = int(datetime.fromisoformat(active_until_iso.replace('Z', '+00:00')).timestamp()) if active_until_iso else None
            active_since_ts = int(datetime.fromisoformat(active_since_iso.replace('Z', '+00:00')).timestamp()) if active_since_iso else None

            title = track['track'].get('tt')
            artist = track['track'].get('an')

            daily_tracks.append({
                'track': track,
                'title': title,
                'artist': artist,
                'activeSince': active_since_ts,
                'activeUntil': active_until_ts
            })

    # Sort the tracks first by 'Leaving' time (activeUntil), then alphabetically by title
    daily_tracks.sort(key=lambda x: (x['activeUntil'] or float('inf'), x['title'].lower()))

    if daily_tracks:
        embeds = []
        chunk_size = 10  # Limit the number of tracks per embed to 5 for readability
        
        for i in range(0, len(daily_tracks), chunk_size):
            embed = discord.Embed(title="Daily Rotation Tracks", color=0x8927A1)
            chunk = daily_tracks[i:i + chunk_size]
            for entry in chunk:
                track = entry['track']
                active_since_ts = entry['activeSince']
                active_until_ts = entry['activeUntil']
                title = entry['title']
                artist = entry['artist']

                # Format timestamps in Discord format
                active_since_display = f"<t:{active_since_ts}:R>" if active_since_ts else "Unknown"
                active_until_display = f"<t:{active_until_ts}:R>" if active_until_ts else "Unknown"
                embed.add_field(name="", value="\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\\_\n", inline=False)
                embed.add_field(
                    name="",
                    value=f"{title if title else 'Unknown Title'} - *{artist if artist else 'Unknown Artist'}*\nAdded: {active_since_display} - Leaving: {active_until_display}",
                    inline=False
                )
            embeds.append(embed)

        view = PaginatorView(embeds, ctx.author.id)
        view.message = await ctx.send(embed=view.get_embed(), view=view)
    else:
        await ctx.send("No daily tracks found.")

@bot.command(name='count', help='Show the total number of available tracks in Fortnite Festival.')
async def count_tracks(ctx):
    tracks = fetch_available_jam_tracks()
    if not tracks:
        await ctx.send('Could not fetch tracks.')
        return
    
    total_tracks = len(tracks)
    embed = discord.Embed(
        title="Total Available Songs",
        description=f"There are currently **{total_tracks}** available songs available in Fortnite Festival.",
        color=0x8927A1
    )

    await ctx.send(embed=embed)

@bot.command(name='tracklist', help='Browse through the full list of available tracks.')
async def tracklist(ctx):
    tracks = fetch_available_jam_tracks()
    if not tracks:
        await ctx.send('Could not fetch tracks.')
        return

    # Use a dictionary to ensure only unique tracks are included
    unique_tracks = {}
    for track_id, track in tracks.items():
        track_sn = track['track']['sn']  # Using the shortname as a unique identifier
        if track_sn not in unique_tracks:
            unique_tracks[track_sn] = track

    # Convert the unique_tracks dictionary to a list and sort it alphabetically by track title
    track_list = sorted(unique_tracks.values(), key=lambda x: x['track']['tt'].lower())

    if not track_list:
        await ctx.send('No tracks available.')
        return

    # Calculate total tracks and update the title
    total_tracks = len(track_list)
    title = f"Available Tracks (Total: {total_tracks})"

    # Generate paginated embeds with 10 tracks per embed
    embeds = generate_tracks_embeds(track_list, title, daily_shortnames={}, chunk_size=10)
    
    # Initialize the paginator view
    view = PaginatorView(embeds, ctx.author.id)
    view.message = await ctx.send(embed=view.get_embed(), view=view)

@bot.command(name='shop', help='Browse through the tracks currently available in the shop.')
async def shop_tracks(ctx):
    tracks = fetch_shop_tracks()
    if not tracks:
        await ctx.send('Could not fetch shop tracks.')
        return
    
    # Sort the tracks alphabetically by title
    tracks = list(tracks.values())
    tracks.sort(key=lambda x: x['title'].lower())

    if not tracks:
        await ctx.send('No tracks available in the shop.')
        return

    # Calculate total tracks and update the title
    total_tracks = len(tracks)
    title = f"Shop Tracks (Total: {total_tracks})"

    # Generate paginated embeds with 7 tracks per embed
    embeds = generate_shop_tracks_embeds(tracks, title, chunk_size=7)
    
    # Initialize the paginator view
    view = PaginatorView(embeds, ctx.author.id)
    view.message = await ctx.send(embed=view.get_embed(), view=view)

bot.run(DISCORD_TOKEN)

