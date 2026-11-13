"""Build assets/audio from the Ninja Adventure pack (CC0, by Pixel-boy and AAA) as listed in tools/audio.json.

python tools/build_audio.py [--src DIR]   (DIR: the pack's Audio folder; needs ffmpeg on the PATH)

Music is re-encoded as Ogg Vorbis at quality 1 (about 80 kbps, a third of the originals' size; Ogg loops without a gap, unlike
mp3). It needs an ffmpeg with libvorbis. Each track's loudness is
measured, and manifest.json holds a gain (at most 1) that brings every track down to the quietest one, so the game can play
them at one volume. Sound effects and jingles become mp3 with their peak at -3 dB. CREDITS_AUDIO.csv lists every source file.
"""
import argparse, csv, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "audio")
PACK = "https://pixel-boy.itch.io/ninja-adventure-asset-pack"


def levels(path):
    """(mean, max) volume in dB, from ffmpeg's volumedetect."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean, peak = (re.search(rf"{k}_volume: (-?[\d.]+) dB", r.stderr) for k in ("mean", "max"))
    return float(mean.group(1)), float(peak.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "..", "..", "..", "..", "_assets_dl", "ninja", "x", "Ninja Adventure - Asset Pack", "Audio"))
    src = ap.parse_args().src
    cfg = {k: v for k, v in json.load(open(os.path.join(HERE, "audio.json"), encoding="utf8")).items() if not k.startswith("_")}
    for sub in ("music", "sfx"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
        for f in os.listdir(os.path.join(OUT, sub)):  # clear the files, not the folder (Windows will not delete a folder another process has open)
            os.remove(os.path.join(OUT, sub, f))
    manifest, credits = {"music": {}, "sfx": {}}, []

    means = {}
    for key, rel in cfg["music"].items():
        dst = os.path.join(OUT, "music", key + ".ogg")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", os.path.join(src, rel), "-vn", "-c:a", "libvorbis", "-q:a", "1", dst], check=True)
        means[key] = levels(dst)[0]
        credits.append([f"music/{key}.ogg", rel, "Pixel-boy; AAA", "CC0", PACK])
    quietest = min(means.values())
    for key, mean in means.items():
        manifest["music"][key] = {"file": f"music/{key}.ogg", "gain": round(max(0.25, 10 ** ((quietest - mean) / 20)), 3)}

    for key, rel in cfg["sfx"].items():
        wav = os.path.join(src, rel)
        gain = -3 - levels(wav)[1]
        dst = os.path.join(OUT, "sfx", key + ".mp3")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav, "-af", f"volume={gain:.2f}dB", "-c:a", "libmp3lame", "-q:a", "4", dst], check=True)
        manifest["sfx"][key] = {"file": f"sfx/{key}.mp3"}
        credits.append([f"sfx/{key}.mp3", rel, "Pixel-boy; AAA", "CC0", PACK])

    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    with open(os.path.join(OUT, "..", "CREDITS_AUDIO.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["file", "source file in the pack", "authors", "licence", "url"])
        w.writerows(credits)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
    print(f"{len(manifest['music'])} tracks and {len(manifest['sfx'])} effects, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
