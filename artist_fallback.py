"""
artist_fallback.py -- fill in missing artist photos with an album cover.

Run after art_fetch.py. For every artist folder that still has no folder.jpg,
it takes the cover art embedded in that artist's albums and saves it as the
artist's folder.jpg (square, baseline JPEG, same size as art_fetch makes).

Which cover: the album with the most tracks that has embedded art. If no
track has embedded art, an album's own folder.jpg / cover.jpg is used.

It also writes two lists next to this script:
  Artists using album cover.txt  -- artists given an album cover by this run
                                    (or an earlier one)
  Artists without photos.txt     -- artists with no photo and no cover at all

Usage:
  python artist_fallback.py "G:\\Music"
  python artist_fallback.py "G:\\Music" --remove
      deletes the album covers this script put in place (only ones it can
      tell are unchanged), so art_fetch can look for real photos again.
"""
from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from PIL import Image
    import art_fetch as af
except ModuleNotFoundError as e:
    print(f"Missing something: {e}")
    print("Put this file next to art_fetch.py, and run: pip install mutagen pillow requests")
    sys.exit(1)

OUTPUT_NAME = "folder.jpg"
OUTPUT_SIZE = 300          # art_fetch's default --max-size
MIN_SIZE = 200             # ignore tiny thumbnails
FILES_PER_ALBUM = 5        # tracks checked per album for embedded art
FALLBACK_LIST = HERE / "Artists using album cover.txt"
MISSING_LIST = HERE / "Artists without photos.txt"
STATE_FILE = HERE / "album-cover-fallbacks.json"   # artist -> hash of the cover we saved
ALBUM_IMAGE_NAMES = ("folder.jpg", "cover.jpg", "folder.jpeg", "cover.jpeg", "front.jpg")


def count_audio(folder: Path) -> int:
    return sum(1 for _ in af.iter_audio_files(folder))


def open_image(data: bytes):
    try:
        img = Image.open(BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except Exception:
        return None
    if img.width < MIN_SIZE or img.height < MIN_SIZE:
        return None
    return img


def embedded_from(folder: Path, recursive: bool):
    files = af.iter_audio_files(folder) if recursive else (
        p for p in sorted(folder.iterdir(), key=lambda x: x.name.casefold())
        if p.is_file() and p.suffix.casefold() in af.AUDIO_EXTS)
    best = None
    for i, f in enumerate(files, 1):
        data = af.extract_embedded_art_bytes(f)
        if data and (best is None or len(data) > len(best)):
            best = data
        if i >= FILES_PER_ALBUM:
            break
    return open_image(best) if best else None


def image_file_in(folder: Path):
    for name in ALBUM_IMAGE_NAMES:
        p = folder / name
        if p.is_file():
            img = open_image(p.read_bytes())
            if img:
                return img
    return None


def cover_for_artist(artist: Path):
    albums = [d for d in artist.iterdir() if d.is_dir() and not d.name.startswith(".")]
    albums = [(count_audio(d), d) for d in albums]
    albums = [a for a in albums if a[0] > 0]
    albums.sort(key=lambda a: (-a[0], a[1].name.casefold()))

    # 1. embedded art, biggest album first
    for _, album in albums:
        img = embedded_from(album, recursive=True)
        if img:
            return img, f"embedded art from '{album.name}'"
    # tracks sitting directly in the artist folder
    img = embedded_from(artist, recursive=False)
    if img:
        return img, "embedded art from loose tracks"
    # 2. an album's own image file
    for _, album in albums:
        img = image_file_in(album)
        if img:
            return img, f"cover image file in '{album.name}'"
    return None, ""


def file_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def load_state() -> dict[str, str]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def still_ours(root: Path, artist: str, digest: str) -> bool:
    p = root / artist / OUTPUT_NAME
    try:
        return p.is_file() and file_hash(p) == digest
    except OSError:
        return False


def remove(root: Path) -> int:
    state = load_state()
    removed = 0
    for artist, digest in sorted(state.items()):
        if still_ours(root, artist, digest):
            (root / artist / OUTPUT_NAME).unlink()
            removed += 1
    save_state({})
    print(f"Removed {removed} album cover(s) used as artist photos, so they can be retried.")
    return 0


def write_list(path: Path, title: str, names) -> None:
    lines = [title, ""] + sorted(names, key=str.casefold)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print('Usage: python artist_fallback.py "G:\\Music" [--remove]')
        return 1
    root = Path(args[0])
    if not root.is_dir():
        print(f"Can't find {root}")
        return 1
    if "--remove" in sys.argv:
        return remove(root)

    # Artists given a cover by earlier runs, as long as it is still that cover
    # (replace it with a real photo and the artist drops off the list).
    state = {a: d for a, d in load_state().items() if still_ours(root, a, d)}
    missing = set()
    made = 0

    for artist in af.get_artist_folders(root):
        if (artist / OUTPUT_NAME).exists():
            continue
        print(f"[{artist.name}]")
        img, how = cover_for_artist(artist)
        if not img:
            print("  no album art found either")
            missing.add(artist.name)
            continue
        af.save_square_jpeg(img, artist / OUTPUT_NAME, OUTPUT_SIZE)
        print(f"  saved album cover as artist photo ({how})")
        state[artist.name] = file_hash(artist / OUTPUT_NAME)
        made += 1

    save_state(state)
    fallback = set(state)
    write_list(FALLBACK_LIST, f"Artists in {root} using an album cover instead of a photo:", fallback)
    write_list(MISSING_LIST, f"Artists in {root} with no photo and no album art:", missing)

    print()
    print(f"Album covers used this run      : {made}")
    print(f"Artists using an album cover    : {len(fallback)}")
    print(f"Artists with nothing at all     : {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
