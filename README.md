# iPod Artist Photos

> **Please read first**
>
> - **Forked from PodBox.** `art_fetch.py` is a modified copy of the artwork
>   tool from [PodBox](https://github.com/anthonyfletcher/podbox)
>   ([`tools/art_fetch`](https://github.com/anthonyfletcher/podbox/tree/master/tools/art_fetch),
>   version 3.8). This is an unofficial fork and isn't affiliated with or
>   endorsed by the PodBox project. Please report problems with this tool
>   here, not to PodBox.
> - **Written with AI.** The changes to `art_fetch.py`, and the new
>   `artist_fallback.py`, `artist_bios.py` and `Fetch iPod Artist Photos.bat`,
>   were written with the help of Claude, an AI assistant made by Anthropic,
>   at my direction.
>   I've used them on my own iPod Classic, but they haven't been tested more
>   widely.
> - **Use at your own risk.** The tool writes picture files into your iPod's
>   music folders and updates its database. Keep a backup of your music.

A one-click Windows tool that fills the **Artist Portraits** menu of an iPod
running [PodBox](https://github.com/anthonyfletcher/podbox), the Rockbox-based
firmware for the iPod Classic and iPod Video.

Double-click one file and it:

1. finds a photo of every artist on your iPod, from Last.fm, Deezer,
   fanart.tv and TheAudioDB;
2. uses an album cover for any artist with no photo anywhere, so nobody is
   left blank;
3. writes a biography and a banner photo for each artist, for the
   **Artist Bio** screen (hold Select on Now Playing);
4. updates the iPod's database and art cache, so the pictures are there as
   soon as you eject it, with nothing to do on the iPod itself.

---

## What you need

- A Windows PC.
- An iPod running PodBox that has been **switched on at least once** since
  PodBox was last installed or updated. (The database tools refuse to run
  until it has.)
- Music on the iPod arranged as `Music\Artist\Album\` folders, as PodBox and
  most sync tools do. Album folders can be named any way you like:
  `OK Computer`, `1997 - OK Computer` and `Radiohead - OK Computer` all work.
  A year in front isn't needed.

---

## Installing

You only need to do this once.

### 1. Install Python

1. Download Python 3 from [python.org/downloads](https://www.python.org/downloads/).
2. Run the installer. On its first screen, **tick "Add python.exe to PATH"**
   before clicking **Install Now**. If you miss this box, the tool can't find
   Python.

To check it worked, open **Command Prompt** (press the Windows key, type
`cmd`, press Enter) and type:

```
python --version
```

It should print something like `Python 3.12.4`.

### 2. Install the libraries the tool uses

In the same Command Prompt window, type:

```
pip install requests pillow mutagen opencv-python
```

Wait for it to finish, then close the window.

### 3. Download this tool

1. At the top of this page, click the green **Code** button, then
   **Download ZIP**.
2. Open your Downloads folder, right-click the ZIP and choose
   **Extract All**. Put it somewhere permanent, for example
   `Documents\iPod Artist Photos`.

You should now have these files in that folder:

| File | What it is |
|---|---|
| `Fetch iPod Artist Photos.bat` | The one you double-click. It runs everything below in order. |
| `art_fetch.py` | Finds artist photos online. |
| `artist_fallback.py` | Uses an album cover when no photo can be found. |
| `artist_bios.py` | Writes each artist's bio and banner for the Artist Bio screen. |

Keep them together in the same folder.

### 4. Add your free Last.fm key (recommended)

Last.fm has the most artist photos, but it only answers the tool if you give
it a free API key:

1. Sign in to Last.fm (or create a free account), then go to
   [last.fm/api/account/create](https://www.last.fm/api/account/create). Any
   name and description will do; leave the callback box empty.
2. Copy the **API key** and **Shared secret** it shows you.
3. Optionally, get a free fanart.tv key too, from
   [fanart.tv/get-an-api-key](https://fanart.tv/get-an-api-key/). It adds
   more photos for well-known artists.
4. Open Command Prompt **in the tool's folder** (open the folder in File
   Explorer, click the address bar, type `cmd` and press Enter), then type:

   ```
   python art_fetch.py --install-credentials --prompt-credentials
   ```

   Paste each key when asked, and press Enter to skip any you don't have.

The keys are saved on your PC, in
`%APPDATA%\RockboxArtistArt\artist_art_credentials.json`, not in this folder,
so they aren't shared if you share the folder. Without any keys the tool
still works using Deezer and TheAudioDB, but finds fewer photos.

### 5. Tell it where your iPod is

The tool assumes your iPod shows up as drive **G:** with its music in
`G:\Music`. If yours is different:

1. Plug in the iPod and look in **File Explorer > This PC** to see its drive
   letter.
2. Right-click `Fetch iPod Artist Photos.bat` and choose **Edit** (on
   Windows 11, **Show more options > Edit**).
3. Near the top, change these two lines to match, for example for drive `E:`:

   ```
   set "IPOD=E:"
   set "MUSIC=E:\Music"
   ```

4. Save and close.

---

## Using it

1. Plug in the iPod and wait for it to appear in File Explorer.
2. Double-click **Fetch iPod Artist Photos.bat**.
3. Let it run. The first time takes a while, roughly a few seconds per
   artist. You can press **Ctrl+C** to stop at any point; next time it carries
   on where it left off.
4. When it says it has finished, eject the iPod as normal. The pictures are
   in **Artist Portraits** when it restarts.

If Windows shows **"Windows protected your PC"** the first time, click
**More info**, then **Run anyway**. That appears for any downloaded `.bat`
file.

### What each run does

| Step | What happens |
|---|---|
| Before step 1 | Album covers that were standing in for missing photos are set aside, so those artists are searched for again. |
| 1. Fetch photos | Looks for a photo of each artist that doesn't have one yet. Artists with a real photo already are skipped. |
| 2. Album cover fallback | Any artist still without a photo gets the cover of their biggest album, squared, instead. |
| 3. Fetch bios | Writes a bio and banner for each artist that doesn't have one yet (see **Artist bios** below). |
| 4. Update database | Runs PodBox's database tool on the iPod. |
| 5. Update art cache | Runs PodBox's art cache tool, so the new pictures show straight away. |

At the end it prints a summary, and saves two lists in the tool's folder:

- **Artists using album cover.txt**: artists showing an album cover because
  no photo was found.
- **Artists without photos.txt**: artists with no photo and no album art at
  all.
- **Artists without bios.txt**: artists no bio could be found for.

### After each sync

Run it again whenever you've added music. Artists that are already done are
skipped, so repeat runs are quick. Each artist still on the album-cover list
is looked up again every time, so photos for them appear once Last.fm or
Deezer gets one.

### Updating the iPod's database

Steps 4 and 5 use PodBox's own PC tools, which come with PodBox and are
already on your iPod, in `.rockbox\tools\` (`database_pb.exe` and
`artcache_pb.exe`). There is nothing extra to install, and you don't need to
run anything on the iPod.

If either step says **FAILED**, do it on the iPod instead: eject it, then go
to **Settings > General Settings > System > Library Maintenance** and choose
**Update Database**, then **Update Art Cache**.

### Adding a photo yourself

To use your own picture for an artist, save any square-ish JPEG as
`folder.jpg` in that artist's folder on the iPod, replacing the one there,
then run the tool again (or **Update Art Cache** on the iPod). The tool never
replaces a photo you've put there yourself.

PodBox also reads artist pictures from `Artwork\People\<Artist>.jpg` at the
root of the iPod, and a picture there takes priority over the artist
folder's `folder.jpg`. If an artist shows the wrong picture, check there
first.

### Artist bios

Step 3 writes two files per artist into `Artwork\Bios` at the root of the
iPod, which the **Artist Bio** screen reads:

- `<Artist>.txt`: the name, a line of genre, home town and dates (birth to
  death for a person, start to end for a band), then the biography.
- `<Artist>.jpg`: a 320 x 160 banner from the artist's photo, cropped so
  the faces stay in view.

The bio is the introduction of the artist's English Wikipedia article. Where
there is none it comes from Last.fm (with your Last.fm key) or Discogs, and
failing those a line of facts. Before looking anything up it checks which
artist yours is: when several share the name (a singer called Dijon, and the
city), it picks the one whose albums match your album folders. A very long
bio is swapped for a much shorter one from another source when there is one.

Photos come from TheAudioDB, Deezer, Discogs or Wikipedia, or the cover of
one of the artist's albums when none has one. What was downloaded is kept on
the PC (in `%APPDATA%\RockboxArtistArt\bios`), so a later run only looks up
new artists.

To write your own bio or banner, edit or replace the file in
`Artwork\Bios`; the tool leaves a file you've changed alone. To look every
artist up again, run `python artist_bios.py "G:\Music" --refresh`, or for one
artist add `--only "Artist Name"`. `--retry-not-found` looks again for the
artists on the no-bio list.

The Artist Bio screen needs a PodBox build that includes it.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| `'python' is not recognized` | Python wasn't added to PATH. Run the Python installer again, choose **Modify**, and tick **Add Python to environment variables**. |
| `No module named requests` (or `PIL`, `mutagen` or `cv2`) | Step 2 of installing didn't finish. Run `pip install requests pillow mutagen opencv-python` again. |
| An artist has the wrong bio | Edit that artist's `.txt` in `Artwork\Bios` on the iPod; the tool leaves a file you've changed alone. Deleting it only brings the same bio back next run. |
| `Can't find G:\Music` | The iPod isn't plugged in, or is on a different drive. See **Tell it where your iPod is**. |
| An artist gets the wrong person's photo | Delete that artist's `folder.jpg` on the iPod and add one yourself (see **Adding a photo yourself**). |
| An artist is never found | Check the artist's name is spelled correctly in your music tags. The tool searches by the name in your tags. |
| Database or art cache step says FAILED | Switch the iPod on once with PodBox, then try again, or run the update on the iPod (see **Updating the iPod's database**). |

---

## Where this comes from

`art_fetch.py` is a modified copy of the artwork tool that comes with PodBox,
[`tools/art_fetch`](https://github.com/anthonyfletcher/podbox/tree/master/tools/art_fetch)
(version 3.8), which downloads artist and album art for a Rockbox-style music
library.

### Why it was forked

The original is a general artwork fetcher. Run against a real iPod library to
fill Artist Portraits, it left many artists with no picture:

- Last.fm often refused its requests or returned image links that no longer
  worked.
- Smaller artists missing from Last.fm, fanart.tv and TheAudioDB got nothing.
- An artist with no photo anywhere was left blank, even when their album
  covers were on the iPod.
- Getting new pictures to show on the iPod took several separate steps,
  some of them on the iPod itself.

### Changes from the original

**`art_fetch.py`**

- **More reliable Last.fm.** Last.fm pages are requested the way a web
  browser asks for them, and when Last.fm refuses (HTTP 403 or 406) two other
  ways are tried, with a pause between, before giving up.
- **Every lookup retries when a site is busy.** A "too many requests" (429) or
  "temporarily unavailable" (5xx) answer from any source is waited out and
  tried again, instead of losing that source for the artist.
- **Broken image links retried** at the other sizes Last.fm offers.
- **Errors are shown** rather than skipped silently.
- **Only the artist's own photos.** Pictures of similar artists are no longer
  picked up from Last.fm pages.
- **New source: Deezer.** Free, needs no key, and covers many smaller
  artists. Several artists can share a name, so a Deezer photo is only used
  when one of that artist's Deezer albums matches one of your album folders
  (ignoring endings such as "- EP" and "(Deluxe)").

**`artist_fallback.py`** (new): for an artist with no photo, squares the cover
of their biggest album (embedded in the tracks, or the album's `folder.jpg` or
`cover.jpg`) into the artist's `folder.jpg`, as a baseline JPEG the iPod can
read. With `--remove` it takes those stand-in covers away again, leaving any
picture you've added yourself.

**`artist_bios.py`** (new): bios and banner photos for PodBox's Artist Bio
screen. See **Artist bios** above.

**`Fetch iPod Artist Photos.bat`** (new): runs everything above in order,
then updates the database and art cache with PodBox's tools.

---

## Licence

`art_fetch.py` comes from PodBox, which is licensed under the GNU General
Public License, version 2. This modified copy is under the same licence; see
`LICENSE`.
