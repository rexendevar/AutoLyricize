"""
This script scans a specified directory for audio files, and for each file,
finds lyrics from Lyricsify.com or Genius.com (as a fallback),
and saves them to the file's metadata.
"""

import sys
import urllib
import json
from http import HTTPStatus
from bs4 import BeautifulSoup
import requests
import os
import re
import eyed3
from colorist import Color
from dotenv import load_dotenv
load_dotenv()
from concurrent.futures import ThreadPoolExecutor
import threading
import time






class RateLimiter:
    def __init__(self, max_calls, period=1.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.time()
                self.calls = [t for t in self.calls if now - t < self.period]
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return  # got a slot, proceed
                # Calculate wait time but don't sleep while holding the lock
                sleep_for = self.period - (now - self.calls[0])

            # Sleep outside the lock so other threads can still check
            time.sleep(sleep_for)



def lyricsify_find_song_lyrics(query):
    """
    Return song lyrics from Lyricsify.com for the first song found using the provided search string.
    If not found, return None.
    """
    # Search Lyricsify for the song using web scraping
    global inexact
    inexact = 0
    r = requests.get(url="https://www.lyricsify.com/lyrics/" +
                    query.lower().replace(
                        " - ", "/").replace(" ", "-"),
                    headers={
                        "User-Agent": os.getenv("HEADER")
                    })
    if "You are being rate limited" in r.text:
        1/0
        return
    link = BeautifulSoup(
        r.text,
        "html.parser")

    if (link.find("div", id="cloudflare_content")):
        cf = Notify.Notification.new("Lyrics script encountered Cloudflare; cannot continue.")
        cf.show()
        raise Exception(
            f"{Color.RED}Scraping encountered Cloudflare and cannot continue.{Color.OFF}")
        return
    divs = link.find_all("div", id=re.compile(r"lyrics_.*_details"))# The site obfuscates(?) the div name but we can bypass this with the power of regex

    # If not found, return None
    if divs is None:
        return None
    # Scrape the song html for the lyrics text
    try: song_html=str('\n'.join(str(divs[0]).split('\n')[1:-1]).replace("<br/>",""))
    except:
        return None
    return(song_html[song_html.find("[ar: "):])





inexact_url=""
def genius_find_song_lyrics(query, access_token, limiter):
    """
    Return song lyrics from Genius.com for the first song found using the provided search string.
    If not found, return None.
    Requires a Genius.com access token.
    """
    limiter.acquire()
    headers = {
        "User-Agent": os.getenv("HEADER"),
        "Authorization": "Bearer " + access_token,
    }
    for attempt in range(5):
        r = requests.get(url="https://api.genius.com/search?q=" + urllib.parse.quote(query), headers={
            "Authorization": "Bearer " + access_token,
            "User-Agent": os.getenv("HEADER")
        },timeout=10)
        if "You are being rate limited" in r.text:
            1/0
        if r.status_code == 429:
            time.sleep(2 ** attempt)  # exponential backoff
            continue
        break

    results = json.loads(r.text)
    if len(results["response"]["hits"]) <= 0:
        return None
    song = results["response"]["hits"][0]["result"]
    query_lower = query.lower()

    # Use Genius sucky search if you can and there's no exact match
    # Also sets variables to make this more transparent
    global inexact
    global inexact_url
    inexact = 0
    if query_lower.find(song["title"].lower()) <= 0 or query_lower.find(song["primary_artist"]["name"].lower()) <= 0:
        if requireexact == "y":
            return None
        inexact = 1
        inexact_url = song["url"]

    # Scrape the song URL for the lyrics text
    page = requests.get(song["url"], headers=headers)
    html = BeautifulSoup(page.text, "html.parser")
    if (html.find("div", id="cloudflare_content")):
        cf = Notify.Notification.new("Lyrics script encountered Cloudflare; cannot continue.")
        cf.show()
        raise Exception(
            f"{Color.RED}Scraping encountered Cloudflare and cannot continue.{Color.OFF}")
    target_divs = html.find_all("div", {'data-lyrics-container': "true"})
    lyrics = []

    # Processing the fetched data
    for div in target_divs:
        if div is None:
            return None
        else:
            lyrics = "\n".join("\n".join(div.strings) for div in target_divs).split("\n")
    final_lyrics = "\n".join(lyrics)
    if final_lyrics == "":
        inexact = 0
        return "inst"
    final_lyrics = final_lyrics.replace("(\n","(").replace("\n)",")").replace(" \n"," ").replace("\n "," ").replace("\n]","]").replace("\n,",",").replace("\n'\n","\n'").replace("\n\n[","\n[").replace("\n[","\n\n[")
    # Removing unwanted line breaks lol
    return final_lyrics


def lrclib(query: str, accept_unsynced: bool) -> str:
    h = {
        "User-Agent": "AutoLyricize https://github.com/rexendevar/AutoLyricize pls make an issue if my tool is a pain i love you",
    }

    p = {
        "q": query,
    }

    r = requests.get("https://lrclib.net/api/search", headers=h, params=p)#, timeout=10)
    if r.status_code == HTTPStatus.OK:
        if r.json():
            if os.getenv("I_WANT_SYNCED_LYRICS") == "True":
                s = r.json()[0].get("syncedLyrics")
            else:
                if accept_unsynced:
                    s = r.json()[0].get("plainLyrics")
                else:
                    return
            if s:
                return s
    return

# Hyperlink on inexact match
def link(uri, label=None):
    if label is None:
        label = uri
    parameters = ''
    # OSC 8 ; params ; URI ST <name> OSC 8 ;; ST
    escape_mask = '\033]8;{};{}\033\\{}\033]8;;\033\\'
    return escape_mask.format(parameters, uri, label)


def process_entry(i, file, short, limiter):
    if any(tag in file for tag in EXCLUSIONS):
        print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Skipped{Color.OFF} : File manually excluded               : " +
                short)
        return

    try: audio_file = eyed3.load(file.strip())
    except:
        print(str(i+1) + "\tof " + str(total) + f" : {Color.RED}Failed{Color.OFF}  : File does not appear to exist        : " +
                short)
        return
    if audio_file is None:
        print(str(i+1) + "\tof " + str(total) + f" : {Color.RED}Failed{Color.OFF}  : Unsupported file format              : " +
                short)
        return

    existing_lyrics = ""
    try:
        for lyric in audio_file.tag.lyrics:
            existing_lyrics += lyric.text
    except:
        existing_lyrics = ""
    if len(existing_lyrics) > 0:
        if overwrite != 'y':
            print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Skipped{Color.OFF} : File already has lyrics              : " +
                short)
            return
        elif protect_alreadysynced:
            stop = False
            LRC_tags = "[ti:", "[ar:", "[al:", "[au:", "[lr:", "[length:", "[by:", "[offset:", "[re:", "[tool:", "[ve:", "[#:"
            for line in existing_lyrics.split():
                if any(tag in line for tag in LRC_tags):
                    #print("synced (tag)")
                    stop = True
                    break

                if len(line) >= 10 and line[0] == "[" and ":" in line[:10] \
                    and "." in line[:10] and "]" in line:
                    #print("synced (stamp)")
                    stop = True
                    break
            if stop:
                print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Skipped{Color.OFF} : File already has synced lyrics       : " +
                    short)
                return
    # Note: re.sub... removes anything in brackets - used for "(feat. ...) as this improves search results"
    try:
        query = re.sub(r" \[^]+\)", "",
                audio_file.tag.artist + " - " + audio_file.tag.title)
    except:
        query = re.sub(r" \[^]+\)", "", short[:-4])
        print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Warning{Color.OFF} : No info, setting query to filename   : " +
            short)

    lyrics = None

    site_used = "LRCLIB   "
    try:
        lyrics = lrclib(query, evenifunsynced == "y")
    except Exception as e:
        print(f"{Color.RED}Error getting LRCLIB lyrics for:    " + short + f"{Color.OFF}")
        raise e

    # Calling Lyricsify script
    if os.getenv("I_WANT_SYNCED_LYRICS") == "True":
        if not lyrics:
            site_used = "Lyricsify"
            try:
                lyrics = lyricsify_find_song_lyrics(query)
            except Exception:
                print(f"{Color.RED}Lyricsify probably rate-limited: " + short + f"{Color.OFF}")
                #raise e


    # Calling Genius script
    if lyrics is None and genius_access_token is not None and ( len(existing_lyrics) == 0 or evenifunsynced == "y" ):
        site_used = "Genius   "
        try:
            lyrics = genius_find_song_lyrics(query, genius_access_token, limiter)
        except Exception:
            print(f"{Color.RED}Genius probably rate-limited: " + short + f"{Color.OFF}")
            #raise e


    # Dealing with double lyrics tags. These were a pain in the ass
    if audio_file.tag is not None:
        if b'USLT' in audio_file.tag.frame_set and lyrics is not None :
            pass
            del audio_file.tag.frame_set[b'USLT']
            audio_file.tag.save() # Utterly villainous way to delete the previous lyrics
            # If this throws an error you should run print(audio_file.tag.frame_set.keys()) to check what tag to use instead
            # USLT is lyrics. b'USLT' means it's stored in bytes instead of as a string


        # Saving tags and logging success
        if lyrics is not None:
            if lyrics == "inst":
                print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Success{Color.OFF} : Genius says song is an instrumental  : " +
                    short)
                return
            audio_file.tag.lyrics.set(lyrics)
            audio_file.tag.save()
            if inexact == 1:
                # Success with inexact lyrics match
                print(str(i+1) + "\tof " + str(total) + f" : {Color.GREEN}Success{Color.OFF} : Lyrics from " + site_used + f" saved to  {Color.YELLOW}" + link(inexact_url, "(i)") + f"{Color.OFF}  : " +
                    short)
            else:
                # Success with perfect match
                print(str(i+1) + "\tof " + str(total) + f" : {Color.GREEN}Success{Color.OFF} : Lyrics from " + site_used + " saved to       : " +
                    short)
        # Logging failures
        elif evenifunsynced != "y" and len(existing_lyrics) > 0:
            # No Lyricsify results when only synced lyrics are allowed
            print(str(i+1) + "\tof " + str(total) + f" : {Color.YELLOW}Failed{Color.OFF}  : No synced lyrics found, preserving   : " +
            short)
        else:
            # No lyrics found at all
            print(str(i+1) + "\tof " + str(total) + f" : {Color.RED}Failed{Color.OFF}  : Lyrics not found for                 : " +
            short)
    else:
        print(str(i+1) + "\tof " + str(total) + f" : {Color.RED}Failed{Color.OFF}  : File's all fucked up                 : " +
            short)


# Start of the main script
if (len(sys.argv) < 2) and not os.getenv("STATIC_WORKING_DIR"):
    raise NameError(
        "The song directory path has not been provided as a parameter.")
if len(sys.argv) >= 2:
    song_dir = sys.argv[1]
else:
    song_dir = os.getenv("STATIC_WORKING_DIR")


# Resetting files
try: os.remove('current.txt')
except OSError: pass
open('current.txt', 'a').close()
try: os.remove('short.txt')
except OSError: pass
open('short.txt', 'a').close()
inexact = 0


# Tallying all the tracks
with open('current.txt', 'a') as current, open('short.txt', 'a') as short:
    total = 0
    for folder, subs, files in os.walk(song_dir):
        for file in files:
            current.write(folder + '/' + file + '\n')
            short.write(file + '\n')
            total += 1


# Environment variables and user input
genius_access_token = os.getenv("GENIUS_ACCESS_TOKEN")
if len(genius_access_token) == 0:
    genius_access_token = None
if genius_access_token is None:
    print(f"{Color.YELLOW}The GENIUS_ACCESS_TOKEN environment variable has not been defined. Genius searches will not be conducted.{Color.OFF}")

if total == 0:
    print("Directory is empty or does not exist.")
else:
    yesno = [ "y", "n" ]
    overwrite = input("Overwrite current lyrics? y/N ").lower()
    if overwrite not in yesno:
        print(f"{Color.YELLOW}Interpreting unknown response as no{Color.OFF}")
        evenifunsynced = "n"
    elif overwrite == "y" and os.getenv("I_WANT_SYNCED_LYRICS") == "True":
        evenifunsynced = input("Even if the new ones are unsynced? y/N ").lower()
        if evenifunsynced != "y":
            print(f"{Color.YELLOW}Intepreting unknown response as no{Color.OFF}")
            evenifunsynced = "n"
    requireexact = input("Require exact artist and title? (Recommended with large folders!!!) Y/n ").lower()
    if requireexact not in yesno:
        print(f"{Color.YELLOW}Interpreting unknown response as yes{Color.OFF}")
        requireexact = "y"
    print("\n")



protect_alreadysynced = True


# To suppress CRC check failed warnings - as a pre-existing CRC issue should not affect lyrics
eyed3.log.setLevel("ERROR")

shlong = open("short.txt", 'r')
short = shlong.readlines()
currong = open('current.txt', 'r')
current = currong.readlines()

with ThreadPoolExecutor(max_workers=50) as executor:
    limiter = RateLimiter(max_calls=100, period=1.0)
    for i, file in enumerate(current):
        executor.submit(process_entry, i, file.strip(), short[i].strip(), limiter)


os.remove('current.txt')
os.remove('short.txt')


# To generate lrc files from AutoLyricize-processed audio files if needed (bash script, requires exiftool):
# for f in *; do lrc="$(exiftool -lyrics "$f" | tail -c +35 | sed 's/\.\./\n/g' | sed 's/\.\[/\n[/g')"; if [ -n "$lrc" ]; then echo "$lrc" > "${f%.*}".lrc; fi; done
