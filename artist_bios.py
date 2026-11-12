"""
artist_bios.py -- artist bios and banner photos for PodBox's Artist Bio screen.

For every artist folder in the iPod's music folder it finds the artist's
biography and a photo, and writes two files into the iPod's Artwork\\Bios
folder, which Artist Bio (hold Select on Now Playing) reads:

  <Artist>.txt   the name, a line of genre, place and dates, then the bio
  <Artist>.jpg   a 320 x 160 banner, cropped so the faces stay in view

Who the artist is gets settled first, so a same-named page can't slip in
("Dijon" the singer, not the city): Wikidata when only one musician or band
has the name, otherwise MusicBrainz, choosing the one whose albums match the
album folders you have. The bio is that artist's English Wikipedia
introduction, else their Last.fm or Discogs bio, else a line of facts.
Photos come from TheAudioDB, Deezer, Discogs or Wikipedia, and an album cover
when none of those has one.

Artists already done are skipped, so a re-run only fetches the new ones. A
bio or banner you have edited or replaced yourself is never overwritten.
What was downloaded is kept on this computer, beside art_fetch's settings.

Usage:
  python artist_bios.py "G:\\Music"
      the iPod is the folder holding Music (here G:\\), so the files go in
      G:\\Artwork\\Bios
  python artist_bios.py "G:\\Music" --ipod "G:\\"
  python artist_bios.py "G:\\Music" --refresh            fetch every bio again
  python artist_bios.py "G:\\Music" --only "Radiohead"   one artist (repeatable)

Setup (once):
  pip install requests pillow mutagen opencv-python
"""
from __future__ import annotations

import argparse, hashlib, io, json, math, os, re, sys, time, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

try:
    import cv2, numpy as np, requests
    from PIL import Image, ImageOps
    import art_fetch as af
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to art_fetch.py, and run: "
          "pip install requests pillow mutagen opencv-python")
    sys.exit(1)

MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
AUDIODB = "https://www.theaudiodb.com/api/v1/json/123/"   # free public key, 30 requests/min
UA = {"User-Agent": "ipod-artist-photos/0.1 (https://github.com/Polytracker/ipod-artist-photos)"}

# The Artist Bio screen: 320 wide, a fixed-height banner, the name over its foot
W = 320
BAN_MIN = BAN_MAX = 160
NAME_STRIP = 40
BIO_CHARS = None          # no limit: the whole introduction

CACHE = af.get_config_path().parent / "bios"      # downloads, kept between runs
MISSING_LIST = HERE / "Artists without bios.txt"


def model_path():
    p = CACHE / "face_detection_yunet_2023mar.onnx"
    if not p.exists() or p.stat().st_size < 100_000:
        print("Downloading the face detection model (230 KB)...")
        r = requests.get(MODEL_URL, headers=UA, timeout=60)
        r.raise_for_status()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    return str(p)

def find_faces(img, threshold=0.5):
    """Faces as (x, y, w, h, eye_y, score) in the image's own pixels.
    Background faces (crowds, posters) much smaller than the main one are dropped."""
    bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    s = 2 if max(w, h) < 800 else 1          # small photos: enlarge so distant faces are found
    if max(w, h) * s > 2400:                  # very large photos: shrink for speed
        s = 2400 / max(w, h)
    sw, sh = int(w * s), int(h * s)
    det = cv2.FaceDetectorYN.create(model_path(), "", (sw, sh), threshold)
    _, fs = det.detect(cv2.resize(bgr, (sw, sh)))
    if fs is None:
        return []
    faces = [(f[0] / s, f[1] / s, f[2] / s, f[3] / s, (f[5] + f[7]) / 2 / s, float(f[-1])) for f in fs]
    big = max(f[3] for f in faces)
    best = max(f[5] for f in faces)
    keep = [f for f in faces if f[3] >= 0.35 * big and (f[5] >= 0.52 or f[5] >= best - 0.05)]
    return keep or [max(faces, key=lambda f: f[5])]

def find_faces_any_way_up(img):
    """Faces as normal; if none, look again with the photo turned upside down
    (faces mapped back to the original orientation)."""
    faces = find_faces(img)
    if faces:
        return faces, ""
    w, h = img.size
    flipped = find_faces(img.rotate(180))
    if flipped:
        return [(w - x - fw, h - y - fh, fw, fh, h - ey, sc) for x, y, fw, fh, ey, sc in flipped], "upside-down faces"
    return [], ""

def busiest_band(img, band_h):
    """Top of the horizontal strip of height band_h with the most detail (edges).
    On a plain sky or wall, that's where the person or subject is."""
    g = np.array(img.convert("L").resize((min(img.size[0], 640), int(img.size[1] * min(img.size[0], 640) / img.size[0]))), dtype=np.float32)
    k = img.size[1] / g.shape[0]
    e = np.abs(cv2.Laplacian(g, cv2.CV_32F)).sum(axis=1)
    bh = max(1, int(band_h / k))
    if bh >= len(e):
        return 0
    sums = np.convolve(e, np.ones(bh), mode="valid")
    return int(np.argmax(sums) * k)

def face_box(faces, w, h):
    """Box around all faces with room for hair and chin, or None."""
    if not faces:
        return None
    top = max(0, min(y - 0.6 * fh for x, y, fw, fh, *_ in faces))
    bot = min(h, max(y + 1.15 * fh for x, y, fw, fh, *_ in faces))
    left = max(0, min(x - 0.3 * fw for x, y, fw, fh, *_ in faces))
    right = min(w, max(x + 1.3 * fw for x, y, fw, fh, *_ in faces))
    return left, top, right, bot

def make_banner(img, faces, centre=False):
    """320 px wide banner keeping every face above the name strip."""
    w, h = img.size
    k = W / w
    box = face_box(faces, w, h)
    if box:
        top, bot = box[1], box[3]
    elif centre:
        top, bot = h * 0.35, h * 0.65
    else:                                     # no faces: frame the most detailed strip
        bh = (BAN_MIN - NAME_STRIP) / k
        top = busiest_band(img, bh)
        bot = top + bh
    need = math.ceil((bot - top) * k) + NAME_STRIP
    ban = min(BAN_MAX, max(BAN_MIN, need))
    ch = min(h, ban / k)                      # crop height in source pixels
    ban = round(ch * k)
    spare = ch - (bot - top) - NAME_STRIP / k
    if spare >= 0 or not faces:
        y0 = top - max(0, spare) * 0.35               # a little headroom, rest goes below
    else:                                     # close-up: keep the eyes, lose some hair or chin
        eyes = sum(f[4] for f in faces) / len(faces)
        y0 = eyes - 0.38 * ch
    y0 = min(max(0, y0), h - ch)
    crop = img.crop((0, int(y0), w, int(y0 + ch)))
    note = "" if box else ("album cover" if centre else "no faces: most detailed strip")
    if box and need > BAN_MAX:
        note = f"faces need {need}px: eyes kept"
    return crop.resize((W, max(1, ban)), Image.LANCZOS), note

def clean_bio(text):
    """Tidy a bio for the iPod: drop bracketed native-script names and pronunciation
    guides, e.g. "Kenji Kawai (川井 憲次, Kawai Kenji)", and stray quotes."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = re.sub(r"\(\s*[;,]\s*", "(", text)       # "(; born 1952)" -> "(born 1952)"
    text = re.sub(r"\(\s*\)", "", text)
    def drop(m):
        inner = m.group(1)
        if re.search(r"[^\x00-\u024F\u2010-\u2027]", inner) or re.search(r"/[^/]+/|pronounced|listen", inner, re.I):
            return ""
        return m.group(0)
    # "青葉市子 (Ichiko Aoba) is..." -> "Ichiko Aoba is..."
    text = re.sub(r"[^\x00-\u024F\u2010-\u2027\s(),.;:'\"]+(?:\s+[^\x00-\u024F\s(),.;:'\"]+)*\s*\(([^()]*[A-Za-z][^()]*)\)",
                  lambda m: m.group(1), text)
    text = re.sub(r"\s*\(([^()]*)\)", drop, text)
    text = re.sub(r"[\u3000-\u9FFF\uAC00-\uD7AF\uFF00-\uFFEF]+[,、]?\s*", "", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip(" '\"‘’“”")

def trim_bio(text, limit=BIO_CHARS):
    """Clean each paragraph and keep the paragraph breaks. No cut unless a limit is set."""
    paras = [clean_bio(p) for p in re.split(r"\n\s*\n|\n", text or "")]
    text = "\n".join(p for p in paras if p)
    if not limit or len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > limit * 0.5 else cut.rsplit(" ", 1)[0] + "…"

def pick_image(a):
    """Prefer wide fanart (good for banners), then the artist thumb."""
    for key in ("strArtistFanart", "strArtistFanart2", "strArtistFanart3",
                "strArtistThumb", "strArtistWideThumb"):
        if a.get(key):
            return key.replace("strArtist", "").lower(), a[key]
    return None, None

def genre_place(a):
    """Genre and home town/country from TheAudioDB, e.g. "Indie · London"."""
    bits = [a.get("strGenre"), a.get("strCountry") and a["strCountry"].split(",")[0]]
    return " · ".join(b.strip() for b in bits if b and b.strip())

def mb_genre_place(mb):
    """Genre and place from MusicBrainz, for artists TheAudioDB doesn't have."""
    if not mb:
        return ""
    genre = mb["tags"][0].title() if mb.get("tags") else ""
    return " · ".join(b for b in (genre, mb.get("country") or "") if b)

def year(v):
    v = str(v or "").strip()[:4]
    return v if len(v) == 4 and v.isdigit() and v != "0000" else ""

def life_dates(person, begin, end):
    """Person: birth to death ("1971–2020", or "b. 1985" if living).
    Band: start to end ("2001–2007", or "1993–" if still going)."""
    begin, end = year(begin), year(end)
    if person:
        if begin and end:
            return f"{begin}–{end}"
        return f"b. {begin}" if begin else (f"d. {end}" if end else "")
    if begin:
        return f"{begin}–{end}"
    return f"until {end}" if end else ""

def audiodb_dates(a):
    """Fallback when MusicBrainz has no dates."""
    person = bool(a.get("strGender")) or (year(a.get("intBornYear")) and not year(a.get("intFormedYear")))
    if person:
        return life_dates(True, a.get("intBornYear"), a.get("intDiedYear"))
    return life_dates(False, a.get("intFormedYear"), a.get("strDisbanded") and a.get("intDiedYear"))

def mb_dates(mb):
    if not mb:
        return ""
    return life_dates(mb.get("type") == "Person", mb.get("begin"), mb.get("end"))

def join_subtitle(*bits):
    return " · ".join(b for b in bits if b)

def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip(". ")

MUSIC_WORDS = ("band", "musician", "singer", "rapper", "group", "duo", "trio", "producer",
               "songwriter", "composer", "dj", "guitarist", "pianist", "drummer", "record",
               "music", "artist", "vocalist", "ensemble", "orchestra", "collective")

def norm(s):
    s = (s or "").lower().replace("&", "and")
    s = re.sub(r"\(\d+\)$", "", s.strip())             # Discogs "Name (2)"
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[^\w]", "", s)

def strip_markup(text):
    """Remove HTML and Discogs [a=...] style markup from a bio."""
    text = re.sub(r"<a [^>]*>Read more on Last\.fm</a>\.?", "", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[(?:a|l|m|r)=([^\]]+)\]", r"\1", text)       # [a=Name] -> Name
    text = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", text)
    text = re.sub(r"\[/?[biu]\]", "", text)
    text = re.sub(r"\[[almr]\d+\]", "", text)                       # [a12345] -> (drop)
    return re.sub(r"\s+", " ", text).strip()

def discogs_artist(artist, session, token):
    """Returns (photo_url, profile) from Discogs, or (None, None)."""
    h = dict(UA, Authorization=f"Discogs token={token}")
    r = session.get("https://api.discogs.com/database/search",
                    params={"q": artist, "type": "artist", "per_page": 5}, headers=h, timeout=20)
    r.raise_for_status()
    time.sleep(1.1)                                    # 60 requests/min
    for hit in r.json().get("results", []):
        if norm(hit.get("title")) != norm(artist):
            continue
        d = session.get(hit["resource_url"], headers=h, timeout=20)
        d.raise_for_status()
        time.sleep(1.1)
        d = d.json()
        imgs = sorted(d.get("images") or [], key=lambda i: (i.get("type") != "primary",
                                                             -(i.get("width", 0) * i.get("height", 0))))
        return (imgs[0]["uri"] if imgs else None), strip_markup(d.get("profile"))
    return None, None

def lastfm_bio(artist, session, key, mbid=None):
    params = {"method": "artist.getinfo", "api_key": key, "format": "json"}
    params.update({"mbid": mbid} if mbid else {"artist": artist, "autocorrect": 1})
    r = session.get("https://ws.audioscrobbler.com/2.0/", params=params, headers=UA, timeout=20)
    r.raise_for_status()
    b = (r.json().get("artist") or {}).get("bio") or {}
    raw = b.get("content") or b.get("summary") or ""
    raw = re.split(r"User-contributed text is available|<a href=\"https?://www\.last\.fm[^>]*>Read more", raw)[0]
    paras = [strip_markup(p) for p in re.split(r"\n\s*\n|\n", raw)]
    bio = "\n".join(p for p in paras if p)
    return bio if len(bio) > 40 else None

WIKI_UA = {"User-Agent": "ipod-artist-photos/0.1 (https://github.com/Polytracker/ipod-artist-photos) bio_test"}

def wiki_get(session, url, params=None):
    """Wikipedia request with its preferred User-Agent, a pause, and back-off on 429."""
    for attempt in range(4):
        time.sleep(0.25)
        r = session.get(url, params=params, headers=WIKI_UA, timeout=20)
        if r.status_code != 429:
            return r
        wait = int(r.headers.get("Retry-After", "0") or 0) or 15 * (attempt + 1)
        print(f"     wikipedia busy, waiting {wait} s")
        time.sleep(wait)
    return r

def wikipedia(artist, session):
    """Returns (photo_url, extract) for the artist's English Wikipedia page, or (None, None).
    Tries likely page titles directly - usually one or two requests per artist."""
    for suffix in ("", " (band)", " (musician)", " (singer)", " (rapper)", " (group)"):
        title = (artist + suffix).replace(" ", "_")
        r = wiki_get(session, "https://en.wikipedia.org/api/rest_v1/page/summary/" +
                     urllib.parse.quote(title, safe="()"))
        if r.status_code == 404:
            continue
        r.raise_for_status()
        p = r.json()
        desc = (p.get("description") or "").lower()
        if p.get("type") == "disambiguation" or not any(w in desc for w in MUSIC_WORDS):
            continue                                   # e.g. "Dijon": "City in Côte-d'Or, France"
        return (p.get("originalimage") or {}).get("source"), (wiki_summary(p.get("title") or title, session) or p.get("extract"))
    return None, None

COVER_NAMES = ("cover", "folder", "front", "albumart")

def album_cover(folders):
    """Largest cover image in the artist's album folders, or embedded art from a track."""
    best = None
    for d in folders:
        for p in d.iterdir():
            if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.stem.lower().startswith(COVER_NAMES):
                try:
                    with Image.open(p) as im:
                        area = im.size[0] * im.size[1]
                    if not best or area > best[0]:
                        best = (area, p)
                except Exception:
                    pass
    if best:
        return best[1].read_bytes(), str(best[1])
    try:                                               # no cover file: try embedded art
        import mutagen
        for d in folders:
            for p in sorted(d.iterdir()):
                if p.suffix.lower() not in (".mp3", ".flac", ".m4a", ".ogg", ".opus"):
                    continue
                f = mutagen.File(p)
                if f is None:
                    continue
                pics = getattr(f, "pictures", None) or []
                if pics:
                    return pics[0].data, str(p) + " (embedded)"
                for k in (f.tags or {}).keys():
                    if str(k).startswith("APIC") or k == "covr":
                        v = f.tags[k]
                        return (v.data if hasattr(v, "data") else bytes(v[0])), str(p) + " (embedded)"
    except ImportError:
        pass
    return None, None

MB_UA = {"User-Agent": "ipod-artist-photos/0.1 ( https://github.com/Polytracker/ipod-artist-photos )",
         "Accept": "application/json"}

_mb_last = [0.0]

_mb_pace = [1.2]

def mb_get(session, url, params=None):
    """MusicBrainz allows about one request per second; when it's busy (503) it asks
    clients to slow down, so back off and retry rather than skipping the artist."""
    for attempt in range(6):
        wait = _mb_pace[0] - (time.time() - _mb_last[0])
        if wait > 0:
            time.sleep(wait)
        r = session.get(url, params=params, headers=MB_UA, timeout=20)
        _mb_last[0] = time.time()
        if r.status_code not in (503, 429):
            break
        _mb_pace[0] = min(4.0, _mb_pace[0] + 0.8)       # stay slower from now on
        pause = int(r.headers.get("Retry-After", "0") or 0) or 2 ** (attempt + 1)
        print(f"     musicbrainz busy, waiting {pause} s")
        time.sleep(pause)
    r.raise_for_status()
    return r.json()

def album_titles(folders, artist=""):
    """Album names from album folder names: "OK Computer" from Artist/OK Computer, or from a
    folder named "Artist - OK Computer". Edition notes like "(Remastered)" and a leading year dropped."""
    out = []
    for d in folders:
        title = d.name if hasattr(d, "name") else str(d)
        if " - " in title:
            left, right = title.split(" - ", 1)
            if artist and norm(clean_artist(left)) == norm(artist) or re.fullmatch(r"\d{4}", left.strip()):
                title = right
        title = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*$", "", title).strip() or title   # "(Remastered)", "[Deluxe]"
        rest = re.sub(r"^[\(\[]?\d{4}[\)\]]?\s*[-–.:_]?\s+", "", title)          # "2007 - ", "2007. ", "(2007) "
        title = rest.strip() or title              # but an album called "1999" keeps its name
        if title:
            out.append(title)
    return out

def musicbrainz(artist, session, albums=(), mbid=None):
    """The MusicBrainz artist this really is. With same-named artists (Love, Yes, Dijon...),
    picks the one whose discography contains your albums. Returns dict incl. 'verified'.
    With a known mbid (saved from an earlier run) it's a single lookup."""
    if mbid:
        best, best_overlap, hits, mine = {"id": mbid}, 1, [None], set()
    else:
        plain = re.sub(r"\s*\([^)]*\)\s*$", "", artist) or artist     # "Ugly (UK)" -> "Ugly"
        res = mb_get(session, "https://musicbrainz.org/ws/2/artist/",
                     {"query": f'artist:"{plain}"', "fmt": "json", "limit": 8})
        found = res.get("artists", [])
        hits = [a for a in found if norm(a.get("name")) == norm(plain)
                or any(norm(x.get("name")) == norm(plain) for x in a.get("aliases") or [])]
        if not hits:
            hits = [a for a in found if a.get("score", 0) == 100][:1]
        if not hits:
            return None
        hits.sort(key=lambda a: -a.get("score", 0))
        mine = {norm(a) for a in albums}
        best, best_overlap = hits[0], 0
        if mine and len(hits) > 1:            # only when the name is shared
            for h in hits[:4]:
                rg = mb_get(session, "https://musicbrainz.org/ws/2/release-group",
                            {"artist": h["id"], "limit": 100, "fmt": "json"})
                titles = {norm(g.get("title")) for g in rg.get("release-groups", [])}
                overlap = sum(1 for a in mine if a in titles)
                if overlap > best_overlap:
                    best, best_overlap = h, overlap
    a = mb_get(session, f"https://musicbrainz.org/ws/2/artist/{best['id']}",
               {"inc": "url-rels+tags", "fmt": "json"})
    wd = None
    for rel in a.get("relations") or []:
        if rel.get("type") == "wikidata":
            wd = rel["url"]["resource"].rstrip("/").rsplit("/", 1)[-1]
    tags = [t["name"] for t in sorted(a.get("tags") or [], key=lambda t: -t.get("count", 0))][:3]
    span = a.get("life-span") or {}
    return {"id": a["id"], "name": a.get("name"), "type": a.get("type"),
            "country": (a.get("area") or {}).get("name"),
            "begin": (span.get("begin") or "")[:4], "end": (span.get("end") or "")[:4],
            "tags": tags, "wikidata": wd, "disambiguation": a.get("disambiguation"),
            "verified": best_overlap > 0 or len(hits) == 1,     # matched albums, or the only artist with the name
            "matched_albums": best_overlap}

def wiki_summary(title, session):
    """The article's whole introduction as plain text, one paragraph per line."""
    r = wiki_get(session, "https://en.wikipedia.org/w/api.php",
                 {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                  "redirects": 1, "format": "json", "titles": title})
    if not r.ok:
        return None
    pages = (r.json().get("query") or {}).get("pages") or {}
    for p in pages.values():
        if p.get("extract"):
            return p["extract"].strip()
    return None

def summary_line(mb, desc):
    """Last resort: one or two sentences built from MusicBrainz and Wikidata facts."""
    if not mb:
        return ""
    bits = []
    what = desc or (mb.get("disambiguation") or "").strip()
    bits.append(f"{mb['name']}: {what}." if what else f"{mb['name']}.")
    if mb.get("begin"):
        active = "Active " + mb["begin"] + ("–" + mb["end"] if mb.get("end") else " onwards")
        bits.append(active + (f", {mb['country']}." if mb.get("country") else "."))
    if mb.get("tags"):
        bits.append("Genres: " + ", ".join(mb["tags"]) + ".")
    return " ".join(bits) if len(bits) > 1 or what else ""

WD_API = "https://www.wikidata.org/w/api.php"

WD_GROUP = {"Q215380", "Q5741069", "Q2088357", "Q9212979", "Q281643", "Q14628581", "Q56816954",
            "Q105815710", "Q109940"}   # musical group, rock band, musical ensemble, duo, trio, ...

WD_MUSIC_JOBS = {"Q177220", "Q639669", "Q36834", "Q488205", "Q753110", "Q183945", "Q130857",
                 "Q2252262", "Q855091", "Q386854", "Q486748", "Q1259917", "Q158852", "Q584301",
                 "Q2643890", "Q1198887", "Q806349", "Q1415090", "Q12800682", "Q1075651", "Q13219637"}
    # singer, musician, composer, singer-songwriter, songwriter, record producer, DJ, rapper,
    # guitarist, drummer, pianist, recording artist, conductor, ...

def wd_claim_ids(ent, prop):
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out

def wd_string(ent, prop):
    """The first plain-string value of a claim, e.g. P434, the MusicBrainz artist ID."""
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, str) and v:
            return v
    return None

def wd_year(ent, prop):
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("time"):
            return year(v["time"].lstrip("+"))
    return ""

def wd_entities(ids, session, props="claims|sitelinks|labels|aliases|descriptions"):
    if not ids:
        return {}
    r = wiki_get(session, WD_API, {"action": "wbgetentities", "ids": "|".join(ids), "props": props,
                                   "languages": "en|mul", "sitefilter": "enwiki", "format": "json"})
    r.raise_for_status()
    return r.json().get("entities") or {}

def wd_is_music(ent):
    kinds = set(wd_claim_ids(ent, "P31"))
    if kinds & WD_GROUP:
        return "Group"
    if "Q5" in kinds and set(wd_claim_ids(ent, "P106")) & WD_MUSIC_JOBS:
        return "Person"
    # Description as a last hint, but only for people and groups - never songs, albums or
    # "discography" pages, whose descriptions also mention artists.
    desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "").lower()
    if "Q5" in kinds and re.search(r"\b(" + "|".join(MUSIC_WORDS) + r")\b", desc):
        return "Person"
    return None

def wd_names(ent):
    """English and multilingual-default ("mul") labels and aliases. Many artists' names are
    now stored only as "mul" labels, e.g. Frank Ocean."""
    names = []
    for lang in ("en", "mul"):
        names.append(((ent.get("labels") or {}).get(lang) or {}).get("value", ""))
        names += [a.get("value", "") for a in ((ent.get("aliases") or {}).get(lang) or [])]
    return {norm(n) for n in names if n}

def wd_record(ent, kind, session, verified, how):
    """Turn a Wikidata entity into the same shape the MusicBrainz lookup returns."""
    person = kind == "Person"
    begin = wd_year(ent, "P569" if person else "P571") or wd_year(ent, "P2031")
    end = wd_year(ent, "P570" if person else "P576") or wd_year(ent, "P2032")
    genre_id = (wd_claim_ids(ent, "P136") or [None])[0]
    place_id = (wd_claim_ids(ent, "P740") or wd_claim_ids(ent, "P19") or [None])[0]
    labels = {}
    try:
        labels = wd_entities([i for i in (genre_id, place_id) if i], session, "labels")
    except Exception:
        pass
    def lab(i):
        if not i:
            return ""
        ls = (labels.get(i) or {}).get("labels") or {}
        return ((ls.get("en") or ls.get("mul")) or {}).get("value", "")
    return {"id": wd_string(ent, "P434"), "wikidata": ent["id"], "name": lab_name(ent), "type": kind,
            "begin": begin, "end": end, "tags": [lab(genre_id).title()] if lab(genre_id) else [],
            "country": lab(place_id),
            "enwiki": ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title"),
            "disambiguation": ((ent.get("descriptions") or {}).get("en") or {}).get("value", ""),
            "verified": verified, "how": how}

def lab_name(ent):
    labels = ent.get("labels") or {}
    return ((labels.get("en") or labels.get("mul")) or {}).get("value", "")

def identify(artist, session, albums=(), known=None):
    """Who this artist really is. Accuracy first, but only does the slow check when needed:
      1. a saved Wikidata ID from an earlier run -> one quick lookup;
      2. Wikidata search: exactly one musician/band with this exact name -> confirmed;
      3. several musicians/bands share the name (Love, Yes...), or none found on Wikidata
         -> MusicBrainz, which picks the one whose discography matches your albums.
    Returns a dict (type, begin, end, wikidata, enwiki, tags, country, verified, how) or None."""
    known = known or {}
    if known.get("wikidata"):
        ent = wd_entities([known["wikidata"]], session).get(known["wikidata"])
        kind = ent and wd_is_music(ent)
        if kind:
            return wd_record(ent, kind, session, known.get("verified", True), "saved id")
    plain = re.sub(r"\s*\([^)]*\)\s*$", "", artist) or artist          # "Ugly (UK)" -> "Ugly"
    r = wiki_get(session, WD_API, {"action": "wbsearchentities", "search": plain, "language": "en",
                                   "uselang": "en", "type": "item", "limit": 20, "format": "json"})
    r.raise_for_status()
    ids = [h["id"] for h in r.json().get("search", [])]
    ents = wd_entities(ids, session) if ids else {}
    music = [(ents[i], wd_is_music(ents[i])) for i in ids if i in ents and wd_is_music(ents[i])]
    exact = [(e, k) for e, k in music if norm(plain) in wd_names(e)]
    if not exact:
        # The name may be swamped by other meanings (Muse -> museums): search musicians/bands only.
        types = "|".join([f"P31={q}" for q in sorted(WD_GROUP)] + [f"P106={q}" for q in sorted(WD_MUSIC_JOBS)])
        r2 = wiki_get(session, WD_API, {"action": "query", "list": "search", "srnamespace": 0,
                                        "srlimit": 10, "format": "json",
                                        "srsearch": f'"{plain}" haswbstatement:{types}'})
        if r2.ok:
            more = [h["title"] for h in (r2.json().get("query") or {}).get("search", []) if h["title"] not in ents]
            ents.update(wd_entities(more, session) if more else {})
            music = [(ents[i], wd_is_music(ents[i])) for i in more if i in ents and wd_is_music(ents[i])]
            exact = [(e, k) for e, k in music if norm(plain) in wd_names(e)]
    if len(exact) == 1:
        return wd_record(exact[0][0], exact[0][1], session, True, "wikidata: only musician with this name")
    # Ambiguous (or not on Wikidata): the careful check against your albums.
    reason = f"{len(exact)} musicians called {plain}" if exact else "not found on Wikidata"
    print(f"     checking with MusicBrainz ({reason})")
    try:
        mb = musicbrainz(artist, session, albums, known.get("mbid"))
    except Exception as e:
        print(f"     musicbrainz unavailable ({e}), using the best match without it")
        mb = None
    if mb and mb.get("wikidata"):
        ent = wd_entities([mb["wikidata"]], session).get(mb["wikidata"])
        if ent:
            rec = wd_record(ent, mb.get("type") or wd_is_music(ent) or "Group", session,
                            mb["verified"], "musicbrainz: matched your albums" if mb["verified"] else "musicbrainz")
            rec["id"] = mb["id"]
            rec["begin"] = rec["begin"] or mb.get("begin")
            rec["end"] = rec["end"] or mb.get("end")
            rec["tags"] = rec["tags"] or mb.get("tags")
            rec["country"] = rec["country"] or mb.get("country")
            return rec
    if mb:
        mb.update(enwiki=None, how="musicbrainz")
        return mb
    if exact:      # MusicBrainz unavailable: best Wikidata guess, marked unconfirmed
        e, k = max(exact, key=lambda ek: len(ek[0].get("sitelinks") or {}))
        return wd_record(e, k, session, False, "wikidata guess")
    return None

LONG_BIO = 3000      # above this, compare with the other sources; switch only if one is 25%+ shorter

MIN_BIO = 400        # "proper": shorter than this counts as a stub and can't win the comparison

def other_bios(artist, session, args, mb, used):
    """Every other source's bio for the same artist (the MusicBrainz ID ties them together)."""
    out = []
    def add(src, fn):
        if src == used:
            return
        try:
            b = fn()
        except Exception as e:
            print(f"     {src}: {e}")
            return
        if b:
            out.append((b, src))
    if mb and mb.get("enwiki"):
        add("wikipedia", lambda: wiki_summary(mb["enwiki"], session))
    if not (mb and mb.get("verified")):
        add("wikipedia by title", lambda: (wikipedia(artist, session) or (None, None))[1])
    if args.lastfm_key:
        add("lastfm", lambda: lastfm_bio(artist, session, args.lastfm_key, mb and mb.get("id")))
    if args.discogs_token:
        add("discogs", lambda: (discogs_artist(artist, session, args.discogs_token) or (None, None))[1])
    return out

def find_bio(artist, session, args, albums=(), facts=None):
    """find_bio_first(), plus the long-bio rule: if the bio is over LONG_BIO characters,
    compare with the other sources and keep the shortest that is still a proper bio."""
    facts = {} if facts is None else facts
    bio, src, sure = find_bio_first(artist, session, args, albums, facts)
    if bio and len(bio) > args.long_bio:
        options = [(bio, src)] + other_bios(artist, session, args, facts.get("mb"), src)
        proper = [o for o in options if len(trim_bio(o[0])) >= MIN_BIO]
        best = min(proper or options, key=lambda o: len(trim_bio(o[0])))
        if best[1] != src and len(trim_bio(best[0])) <= 0.75 * len(trim_bio(bio)):
            print(f"     long bio: {src} {len(bio):,} -> {best[1]} {len(best[0]):,}")
            bio, src = best
    return bio, src, sure

def find_bio_first(artist, session, args, albums=(), facts=None):
    """Bio for the artist identify() settled on, so a same-named page can't slip in.
    Order: that artist's English Wikipedia introduction; Wikipedia by page title (only if the
    artist couldn't be confirmed); Last.fm; Discogs; a short line of facts.
    Returns (bio, source, verified)."""
    def attempt(name, fn):
        try:
            return fn()
        except Exception as e:
            print(f"     {name}: {e}")
            return None
    facts = {} if facts is None else facts
    who = attempt("identify", lambda: identify(artist, session, albums, facts.get("known")))
    facts["mb"] = who
    sure = bool(who and who["verified"])
    if who and who.get("enwiki"):
        b = attempt("wikipedia", lambda: wiki_summary(who["enwiki"], session))
        if b:
            return b, "wikipedia", sure
    if not sure:
        w = attempt("wikipedia", lambda: wikipedia(artist, session))
        if w and w[1]:
            return w[1], "wikipedia by title", False
    if args.lastfm_key:
        b = attempt("last.fm", lambda: lastfm_bio(artist, session, args.lastfm_key, who and who.get("id")))
        if b:
            return b, "lastfm", bool(who)
    if args.discogs_token:
        d = attempt("discogs", lambda: discogs_artist(artist, session, args.discogs_token))
        if d and d[1] and len(d[1]) > 40:
            return d[1], "discogs", False
    line = summary_line(who, who and who.get("disambiguation"))
    if line:
        return line, "facts", sure
    return "", "", False

def remember(meta, who):
    """Save the identity so later runs skip the search."""
    if who:
        meta["wikidata"] = who.get("wikidata") or meta.get("wikidata")
        meta["mbid"] = who.get("id") or meta.get("mbid")
        meta["identity_verified"] = bool(who.get("verified"))
        meta["identified_by"] = who.get("how", "")

SKIP_FOLDERS = {"compilations", "various", "various artists", "soundtracks", "podcasts", "audiobooks"}

AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aiff", ".aif", ".wma", ".alac", ".ape")

def clean_artist(name):
    name = re.split(r"\s*;\s*", name)[0]                 # "Headache; Vegyn" -> "Headache"
    name = re.sub(r",\s*[^\x00-\u024F]+$", "", name)       # "Ryo Fukui, 福居良" -> "Ryo Fukui"
    m = re.match(r"^(.*),\s*(The|A|An)$", name, re.I)
    if m:                                                  # "Strokes, The" -> "The Strokes"
        name = f"{m.group(2)} {m.group(1)}"
    return name.strip()

def scan_library(lib):
    """{artist name: [album folders]}. Handles artist folders with album folders inside
    (Artist/Album), and flat "Artist - Album" folders."""
    names = {}
    for d in lib.iterdir():
        if not d.is_dir() or d.name.lower() in SKIP_FOLDERS or d.name.startswith((".", "_")):
            continue
        try:
            subdirs = [x for x in d.iterdir() if x.is_dir()]
            has_audio = any(x.suffix.lower() in AUDIO for x in d.iterdir() if x.is_file())
        except OSError:
            continue
        if subdirs and not has_audio:                      # Artist/Album/
            name, albums = d.name, subdirs
        elif " - " in d.name:                              # "Artist - Album"
            name, albums = d.name.split(" - ", 1)[0].strip(), [d]
        else:
            name, albums = d.name, [d]
        name = clean_artist(name)
        if name.lower() in SKIP_FOLDERS or not re.search(r"\w", name) or name.startswith(("_", "library")):
            continue
        names.setdefault(name, []).extend(albums)
    return names

# ---------------------------------------------------------------- photos
_adb_last = [0.0]

def audiodb(artist, session, mbid=None):
    """TheAudioDB's record for the artist: by MusicBrainz ID when known, else by name.
    A name search that finds someone with a different MusicBrainz ID is not them."""
    def get(path):
        for attempt in range(3):
            wait = 2.1 - (time.time() - _adb_last[0])     # stay under the free limit
            if wait > 0:
                time.sleep(wait)
            r = session.get(AUDIODB + path, headers=UA, timeout=20)
            _adb_last[0] = time.time()
            if r.status_code == 429:
                print("     theaudiodb busy, waiting 60 s")
                time.sleep(60)
                continue
            r.raise_for_status()
            return (r.json() or {}).get("artists") or []
        return []
    if mbid:
        arts = get("artist-mb.php?i=" + urllib.parse.quote(mbid))
        if arts:
            return arts[0]
    for a in get("search.php?s=" + urllib.parse.quote(artist)):
        theirs = a.get("strMusicBrainzID")
        if mbid and theirs and theirs != mbid:
            continue
        if not mbid and norm(a.get("strArtist")) != norm(artist):
            continue
        return a
    return None

def download_image(url, session):
    r = session.get(url, headers=UA, timeout=30)
    if r.ok and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN"):
        return r.content
    return None

def find_photo(artist, who, adb, folders, session, args):
    """(image bytes, source) from the first source that has one, else (None, "")."""
    tries = []
    if adb:
        kind, url = pick_image(adb)
        if url:
            tries.append(("theaudiodb " + kind, lambda url=url: url))
    def deezer():
        # art_fetch's lookup: a same-named artist is used only if their albums match yours
        limiter = af.RateLimiter(argparse.Namespace(**{k: 0.3 for k in (
            "lastfm_rate_limit", "fanart_rate_limit", "musicbrainz_rate_limit",
            "coverartarchive_rate_limit", "theaudiodb_rate_limit", "image_rate_limit",
            "deezer_rate_limit")}))
        found = af.lookup_deezer_artist_candidates(artist, album_titles(folders, artist),
                                                   session, limiter)
        return found[0].image_url if found else None
    tries.append(("deezer", deezer))
    if args.discogs_token:
        tries.append(("discogs", lambda: discogs_artist(artist, session, args.discogs_token)[0]))
    tries.append(("wikipedia", lambda: wikipedia(artist, session)[0]))
    for source, find in tries:
        try:
            url = find()
            data = url and download_image(url, session)
        except Exception as e:
            print(f"     {source}: {e}")
            continue
        if data:
            return data, source
    data, _ = album_cover(folders)
    return (data, "album cover") if data else (None, "")


# ---------------------------------------------------------------- one artist
def fetch(artist, folders, session, args, known):
    """Who the artist is, their bio, subtitle and photo. Returns (meta, photo bytes)."""
    albums = album_titles(folders, artist)
    facts = {"known": known}
    bio, src, sure = find_bio(artist, session, args, albums, facts)
    who = facts.get("mb")
    adb = None
    try:
        adb = audiodb(artist, session, who and who.get("id"))
    except Exception as e:
        print(f"     theaudiodb: {e}")
    meta = {"artist": artist, "bio": trim_bio(bio), "bio_source": src, "bio_verified": sure,
            "subtitle": join_subtitle(genre_place(adb) if adb else mb_genre_place(who),
                                      mb_dates(who) or (audiodb_dates(adb) if adb else "")),
            "fetched": time.strftime("%Y-%m-%d")}
    remember(meta, who)
    photo, meta["photo_source"] = (None, "")
    if not args.no_banners and (meta["bio"] or meta["subtitle"]):
        photo, meta["photo_source"] = find_photo(artist, who, adb, folders, session, args)
    return meta, photo

def finished(meta):
    """Whether the artist has died or the band has split, read off the dates line:
    "1947–2016", "d. 2016" or "until 2007". Their bio no longer changes much."""
    dates = (meta.get("subtitle") or "").rsplit("·", 1)[-1].strip()
    return bool(re.fullmatch(r"\d{4}–\d{4}|d\. \d{4}|until \d{4}", dates))

def stale(meta, days):
    """Fetched more than `days` ago, for an artist who is still active."""
    if not days or finished(meta):
        return False
    try:
        age = time.time() - time.mktime(time.strptime(meta.get("fetched", ""), "%Y-%m-%d"))
    except ValueError:
        return True
    return age > days * 86400

def sha1(path):
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.exists() else None

def write_if_ours(path, data, meta, key):
    """Writes data unless the file there is not the one this script last wrote.
    Returns "written", "same" or "kept"."""
    have = sha1(path)
    if have and meta.get(key) and have != meta[key]:
        return "kept"
    if have and not meta.get(key):          # there before this script: someone's own
        return "kept"
    new = hashlib.sha1(data).hexdigest()
    if have == new:
        return "same"
    path.write_bytes(data)
    meta[key] = new
    return "written"

def banner_bytes(photo, centre):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(photo))).convert("RGB")
    faces, _ = find_faces_any_way_up(img)
    banner, _ = make_banner(img, faces, centre=centre)
    out = io.BytesIO()
    banner.save(out, "JPEG", quality=90, progressive=False)   # baseline: quickest on the iPod
    return out.getvalue()

def write_files(meta, out_dir, args):
    """The .txt and .jpg for one artist. Returns how each went."""
    name = safe_name(meta["artist"])
    text = f"{meta['artist']}\n{meta.get('subtitle', '')}\n\n{meta['bio']}\n"
    res = [write_if_ours(out_dir / f"{name}.txt", text.encode("utf-8"), meta, "txt_sha1")]
    photo = CACHE / f"{name}.jpg"
    if not args.no_banners and photo.exists():
        data = banner_bytes(photo.read_bytes(), meta.get("photo_source") == "album cover")
        res.append(write_if_ours(out_dir / f"{name}.jpg", data, meta, "jpg_sha1"))
    return res


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_root", help="the iPod's music folder, one folder per artist")
    ap.add_argument("--ipod", help="the iPod's own folder (default: the folder holding the music folder)")
    ap.add_argument("--refresh", action="store_true", help="fetch every artist's bio and photo again")
    ap.add_argument("--retry-not-found", action="store_true", help="look again for artists nothing was found for")
    ap.add_argument("--refresh-after", type=int, default=365, metavar="DAYS",
                    help="fetch an active artist's bio again once it is this old (default 365; 0 = never). "
                         "Artists who have died and bands that have split are not refreshed")
    ap.add_argument("--only", action="append", default=[], help="just this artist (can be given more than once)")
    ap.add_argument("--no-banners", action="store_true", help="bios only, no photos")
    ap.add_argument("--discogs-token", default=os.environ.get("DISCOGS_TOKEN"),
                    help="Discogs personal token, an extra source (or set DISCOGS_TOKEN)")
    ap.add_argument("--long-bio", type=int, default=LONG_BIO,
                    help=f"a bio longer than this is compared with the other sources, and a much "
                         f"shorter proper one used instead (default {LONG_BIO})")
    args = ap.parse_args(argv)
    args.lastfm_key = af.load_credentials().lastfm_api_key or None

    music = Path(args.music_root)
    if not music.is_dir():
        print(f"Can't find {music}")
        return 1
    out_dir = Path(args.ipod) / "Artwork" / "Bios" if args.ipod else music.resolve().parent / "Artwork" / "Bios"
    out_dir.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"Writing bios to {out_dir}")
    if args.lastfm_key:
        print("Using the Last.fm key saved by art_fetch")

    artists = scan_library(music)
    only = {norm(a) for a in args.only}
    names = sorted((a for a in artists if not only or norm(a) in only), key=str.casefold)
    print(f"{len(names)} artists\n")

    session = requests.Session()
    counts = {"written": 0, "same": 0, "kept": 0, "none": 0, "error": 0}
    missing = []
    try:
        for i, artist in enumerate(names, 1):
            name = safe_name(artist)
            mp = CACHE / f"{name}.json"
            meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
            nothing = meta is not None and not (meta.get("bio") or meta.get("subtitle"))
            need = (meta is None or args.refresh or (nothing and args.retry_not_found)
                    or (not nothing and stale(meta, args.refresh_after))
                    or (not args.no_banners and meta.get("photo_source") is None))
            try:
                if need:
                    print(f"{i:4d}/{len(names)} {artist}")
                    known = {"wikidata": meta.get("wikidata"), "mbid": meta.get("mbid"),
                             "verified": meta.get("identity_verified", True)} if meta else {}
                    new, photo = fetch(artist, artists[artist], session, args, known)
                    if meta:                          # keep the record of what was written
                        new.update({k: meta[k] for k in ("txt_sha1", "jpg_sha1") if k in meta})
                        if meta.get("bio") and not new["bio"]:
                            # a source being down never costs a bio already found
                            new.update({k: meta[k] for k in ("bio", "bio_source", "bio_verified")})
                        if meta.get("subtitle") and not new["subtitle"]:
                            new["subtitle"] = meta["subtitle"]
                        if meta.get("photo_source") and not photo:
                            new["photo_source"] = meta["photo_source"]
                    meta = new
                    if photo:
                        (CACHE / f"{name}.jpg").write_bytes(photo)
                    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(f"     bio: {meta['bio_source'] or 'none'}"
                          f"{' (not confirmed)' if meta['bio'] and not meta['bio_verified'] else ''}, "
                          f"photo: {meta['photo_source'] or 'none'}")
                if not (meta.get("bio") or meta.get("subtitle")):
                    counts["none"] += 1
                    missing.append(artist)
                    continue
                res = write_files(meta, out_dir, args)
                mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                if "kept" in res:
                    print(f"     {artist}: kept your own {'bio' if res[0] == 'kept' else 'banner'}")
                counts["written" if "written" in res else "kept" if "kept" in res else "same"] += 1
            except Exception as e:
                counts["error"] += 1
                print(f"  !! {artist}: {e}")
    except KeyboardInterrupt:
        print("\nStopped. Run again to carry on where it left off.")

    MISSING_LIST.write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")
    print(f"\nBios written or updated: {counts['written']}, unchanged: {counts['same']}, "
          f"kept as you left them: {counts['kept']}, none found: {counts['none']}"
          + (f", failed: {counts['error']}" if counts["error"] else ""))
    if missing:
        print(f"Artists with no bio are listed in \"{MISSING_LIST.name}\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
