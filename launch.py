import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

version_id = "1.21.11"
manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
fallback_client_url = "https://piston-data.mojang.com/v1/objects/ba2df812c2d12e0219c489c4cd9a5e1f0760f5bd/client.jar"
app_folder_name = "minecraft_1_21_11"

print("          .....=+++--.....          ")
print("    .....-==-=-===--++===--.....    ")
print("....++==++=++--+++++++====++++++....")
print("====-++-+==+=++=-==++-+==+++==-==+**")
print("===+++++=+=--===+==+=++=-=+=-=*#####")
print("=#-===++=======++++++=--==***#*####%")
print("#*#+++#+++=+++---==+++##*###***#%%%#")
print("**++*=#*#====++++=*****#%*%*#*%%##%#")
print("=#++*#+*#+#=-*#=++***###%%%#%%#%####")
print("+**=++**=***#**+#*%##*%##%#*#*####%#")
print("+*#+**+****=+*****#%########%####*##")
print("++*+**#*#**++****+*%######%#######*%")
print("***+++*=*********+*#*####%##**#%%##*")
print("**+***+*+#+=*+=+#*##%##%#*##########")
print("+***##++**++#*++*+###**#*##%##%%#*##")
print("**==+*#+*****##+**#######*##%#%%###%")
print("...-++**#*#+#***=*#%##%%##%##%##-.. ")
print("    ...:****#**=+*###*#%%*##....    ")
print("        ....**+*++##%###..          ")
print("              ..*###..              ")
print("tool by alwaysgoober - powering piracy")


def line(text=""):
    print(text, flush=True)


def pick_drive():
    if os.name != "nt":
        return Path.home()

    mask = ctypes.windll.kernel32.GetLogicalDrives()
    best = None

    for i in range(26):
        if not mask & (1 << i):
            continue

        root = Path(f"{chr(65 + i)}:\\")

        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue

        if best is None or usage.free > best[1]:
            best = (root, usage.free)

    return best[0] if best else Path.cwd().anchor


drive = pick_drive()
base = Path(drive) / app_folder_name
versions = base / "versions" / version_id
client = base / "client.jar"
mods = base / "mods"
libraries = base / "libraries"
assets = base / "assets"
natives = versions / "natives"
version_json_path = versions / f"{version_id}.json"
log_configs = assets / "log_configs"


def bar(label, done, total):
    width = 30

    if total:
        filled = int(width * done / total)
        percent = int(done * 100 / total)
        current = done / 1024 / 1024
        size = total / 1024 / 1024
        sys.stdout.write(f"\r{label}: [{'#' * filled}{'.' * (width - filled)}] {percent}% {current:.2f}/{size:.2f} mb")
    else:
        sys.stdout.write(f"\r{label}: {done / 1024 / 1024:.2f} mb")

    sys.stdout.flush()


def sha1(path):
    h = hashlib.sha1()

    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)

    return h.hexdigest()


def good(path, size=None, digest=None):
    if not path.exists() or path.stat().st_size == 0:
        return False

    if size and path.stat().st_size != size:
        return False

    if digest and sha1(path).lower() != digest.lower():
        return False

    return True


def download(url, path, label, size=None, digest=None, quiet=False, verify_existing=True):
    path.parent.mkdir(parents=True, exist_ok=True)

    if good(path, size, digest if verify_existing else None):
        if not quiet:
            line(f"{label} already exists")
        return

    temp = path.with_suffix(path.suffix + ".tmp")

    if temp.exists():
        temp.unlink()

    req = urllib.request.Request(url, headers={"User-Agent": "python-launcher"})

    with urllib.request.urlopen(req) as res, open(temp, "wb") as out:
        total = size or int(res.headers.get("Content-Length", "0"))
        done = 0

        while True:
            chunk = res.read(1024 * 128)
            if not chunk:
                break

            out.write(chunk)
            done += len(chunk)
            if not quiet:
                bar(label, done, total)

    if not quiet:
        sys.stdout.write("\n")

    temp.replace(path)

    if not good(path, size, digest):
        path.unlink(missing_ok=True)
        raise RuntimeError(f"{label} downloaded but did not verify")


def progress(label, done, total):
    width = 30
    filled = int(width * done / total) if total else width
    percent = int(done * 100 / total) if total else 100
    sys.stdout.write(f"\r{label}: [{'#' * filled}{'.' * (width - filled)}] {percent}% {done}/{total}")
    sys.stdout.flush()


def download_many(tasks, label, workers=32):
    pending = []
    seen = set()

    for url, path, size, digest in tasks:
        key = str(path).lower()

        if key in seen:
            continue

        seen.add(key)

        if good(path, size, None):
            continue

        pending.append((url, path, size, digest))

    total = len(pending)

    if not total:
        line(f"{label} ready")
        return

    line(f"{label}: downloading {total} file(s)")
    done = 0
    progress(label, done, total)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(download, url, path, path.name, size, digest, True, False)
            for url, path, size, digest in pending
        ]

        for future in as_completed(futures):
            future.result()
            done += 1

            if done == total or done % 25 == 0:
                progress(label, done, total)

    sys.stdout.write("\n")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "python-launcher"})

    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))


def version_url():
    manifest = get_json(manifest_url)

    for item in manifest["versions"]:
        if item["id"] == version_id:
            return item["url"], item.get("sha1")

    raise RuntimeError(f"{version_id} was not found in mojang's version manifest")


def load_version():
    url, digest = version_url()
    download(url, version_json_path, f"{version_id}.json", digest=digest)

    with open(version_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def os_name():
    system = platform.system().lower()

    if system == "windows":
        return "windows"
    if system == "darwin":
        return "osx"
    return "linux"


def os_arch():
    arch = platform.machine().lower()
    return "x64" if "64" in arch or arch in {"amd64", "x86_64"} else "x86"


def rules_allowed(rules, features=None):
    if not rules:
        return True

    allowed = False
    current = os_name()
    features = features or {}

    for rule in rules:
        action = rule.get("action") == "allow"
        target = rule.get("os")
        wanted_features = rule.get("features")

        if wanted_features:
            matched = True

            for key, value in wanted_features.items():
                if bool(features.get(key, False)) != bool(value):
                    matched = False
                    break

            if not matched:
                continue

        if not target:
            allowed = action
            continue

        name = target.get("name")
        arch = target.get("arch")

        if name and name != current:
            continue

        if arch and arch != os_arch():
            continue

        allowed = action

    return allowed


def library_files(data):
    files = []
    native_files = []
    tasks = []
    native_key = f"natives-{os_name()}"

    for lib in data.get("libraries", []):
        if not rules_allowed(lib.get("rules")):
            continue

        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")

        if artifact:
            path = libraries / artifact["path"]
            tasks.append((artifact["url"], path, artifact.get("size"), artifact.get("sha1")))
            files.append(path)

        classifiers = downloads.get("classifiers", {})
        native = classifiers.get(native_key)

        if native:
            path = libraries / native["path"]
            tasks.append((native["url"], path, native.get("size"), native.get("sha1")))
            native_files.append(path)

    download_many(tasks, "libraries", 24)

    return files, native_files


def extract_natives(native_files):
    natives.mkdir(parents=True, exist_ok=True)

    for jar in native_files:
        marker = natives / f".{jar.stem}.done"

        if marker.exists():
            continue

        line(f"extracting {jar.name}")

        with zipfile.ZipFile(jar) as z:
            for item in z.infolist():
                name = item.filename

                if name.endswith("/") or name.startswith("META-INF/"):
                    continue

                z.extract(item, natives)

        marker.write_text("done", encoding="utf-8")


def install_assets(data):
    index = data["assetIndex"]
    index_path = assets / "indexes" / f"{index['id']}.json"
    download(index["url"], index_path, f"assets {index['id']}", index.get("size"), index.get("sha1"))

    with open(index_path, "r", encoding="utf-8") as f:
        asset_data = json.load(f)

    objects = asset_data.get("objects", {})
    tasks = []

    for info in objects.values():
        h = info["hash"]
        path = assets / "objects" / h[:2] / h

        tasks.append((f"https://resources.download.minecraft.net/{h[:2]}/{h}", path, info.get("size"), h))

    download_many(tasks, "assets", 48)

    line(f"assets ready ({len(objects)} files)")


def install_logging(data):
    logging = data.get("logging", {}).get("client")

    if not logging:
        return []

    info = logging.get("file", {})
    path = log_configs / info["id"]
    download(info["url"], path, info["id"], info.get("size"), info.get("sha1"))

    arg = logging.get("argument")
    if not arg:
        return []

    return [arg.replace("${path}", str(path))]


def install_client(data):
    info = data.get("downloads", {}).get("client")

    if info:
        download(info["url"], client, "client.jar", info.get("size"), info.get("sha1"))
        return

    download(fallback_client_url, client, "client.jar")


def java_path():
    found = shutil.which("java")

    if found:
        return found

    raise RuntimeError("java was not found in path, install java 21 and try again")


def mod_jars():
    mods.mkdir(parents=True, exist_ok=True)
    return [p for p in sorted(mods.glob("*.jar")) if p.is_file()]


def expand(value, values):
    for key, val in values.items():
        value = value.replace("${" + key + "}", str(val))

    return value


def collect_args(items, values, features=None):
    out = []

    for item in items:
        if isinstance(item, str):
            out.append(expand(item, values))
            continue

        if not rules_allowed(item.get("rules"), features):
            continue

        value = item.get("value")

        if isinstance(value, list):
            out.extend(expand(str(v), values) for v in value)
        elif value is not None:
            out.append(expand(str(value), values))

    return out


def stable_uuid(name):
    return str(uuid.uuid3(uuid.NAMESPACE_DNS, "offline:" + name))


def fabric_installer_path():
    return base / "fabric-installer.jar"


def check_fabric():
    installer = fabric_installer_path()

    if installer.exists():
        line("fabric installer already exists, skipping download")
        return

    line("")
    line("do you want to install fabric? (y/n)")
    line("fabric lets you load fabric mods, skip if you just want vanilla or forge mods")
    answer = input("> ").strip().lower()

    if answer != "y":
        line("skipping fabric")
        return

    line("fetching fabric installer info...")

    try:
        installer_list = get_json("https://meta.fabricmc.net/v2/versions/installer")
        latest = installer_list[0]
        url = latest["url"]
        line(f"downloading fabric installer {latest['version']}")
        download(url, installer, "fabric-installer.jar")
        line("running fabric installer for " + version_id)
        java = java_path()
        result = subprocess.run(
            [java, "-jar", str(installer), "client", "-mcversion", version_id, "-dir", str(base), "-noprofile"],
            cwd=base
        )
        if result.returncode == 0:
            line("fabric installed successfully")
        else:
            line("fabric installer exited with an error, you may need to run it manually")
    except Exception as e:
        line(f"fabric install failed: {e}")
        line("continuing without fabric")


def resolution_prompt():
    line("")
    line("type fs for fullscreen, otherwise input a resolution (1920x1080 is common)")
    line("press enter to skip and use default window size")
    raw = input("> ").strip().lower()

    if raw == "fs":
        return [], True

    if not raw:
        return [], False

    parts = raw.replace("x", " ").replace(",", " ").split()

    if len(parts) == 2 and all(p.isdigit() for p in parts):
        w, h = parts
        return ["--width", w, "--height", h], False

    line(f"could not parse '{raw}', using default window size")
    return [], False


def extra_jvm_prompt():
    line("")
    line("enter any extra jvm arguments to pass (leave blank to skip)")
    line("example: -XX:+UseG1GC -Dfml.ignoreInvalidMinecraftCertificates=true")
    raw = input("> ").strip()

    if not raw:
        return []

    return raw.split()


def username_prompt():
    while True:
        name = input("Enter your username (symbols & spaces may not work on servers):\n").strip()

        if name:
            return name

        line("username cannot be empty")


def launch(data, libs, logging_args, username, resolution_args, fullscreen, extra_jvm):
    found_mods = mod_jars()
    classpath_items = [str(p) for p in libs] + [str(p) for p in found_mods] + [str(client)]
    classpath = os.pathsep.join(classpath_items)

    values = {
        "auth_player_name": username,
        "version_name": version_id,
        "game_directory": str(base),
        "assets_root": str(assets),
        "assets_index_name": data["assetIndex"]["id"],
        "auth_uuid": stable_uuid(username),
        "auth_access_token": "0",
        "clientid": "0",
        "auth_xuid": "0",
        "user_type": "legacy",
        "version_type": data.get("type", "release"),
        "natives_directory": str(natives),
        "launcher_name": "python",
        "launcher_version": "1",
        "classpath": classpath,
        "classpath_separator": os.pathsep,
        "library_directory": str(libraries),
    }

    features = {
        "is_demo_user": False,
        "has_custom_resolution": len(resolution_args) > 0,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }

    jvm_args = collect_args(data.get("arguments", {}).get("jvm", []), values, features)
    game_args = collect_args(data.get("arguments", {}).get("game", []), values, features)

    if "minecraftArguments" in data:
        game_args += [expand(arg, values) for arg in data["minecraftArguments"].split()]

    if fullscreen:
        game_args += ["--fullscreen"]

    game_args += resolution_args

    command = [java_path(), "-Xmx2G", "-Xms1G"] + extra_jvm + logging_args + jvm_args + [data["mainClass"]] + game_args

    line("launching")
    line(f"install folder: {base}")
    line(f"mods folder: {mods}")
    line(f"mods loaded into classpath: {len(found_mods)}")
    line("terminal will stay open while the game is running")
    line("")

    proc = subprocess.Popen(command, cwd=base, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")

    try:
        for output in proc.stdout:
            print(output, end="")
    except KeyboardInterrupt:
        line("\nstopping")
        proc.terminate()

    code = proc.wait()
    line("")
    line(f"minecraft closed with code {code}")
    input("press enter to close")


def install():
    base.mkdir(parents=True, exist_ok=True)
    mods.mkdir(parents=True, exist_ok=True)
    versions.mkdir(parents=True, exist_ok=True)

    line(f"using biggest drive: {drive}")
    line(f"installing to: {base}")

    data = load_version()
    install_client(data)
    libs, native_files = library_files(data)
    extract_natives(native_files)
    install_assets(data)
    logging_args = install_logging(data)

    return data, libs, logging_args


def main():
    try:
        data, libs, logging_args = install()
        check_fabric()
        resolution_args, fullscreen = resolution_prompt()
        extra_jvm = extra_jvm_prompt()
        username = username_prompt()
        launch(data, libs, logging_args, username, resolution_args, fullscreen, extra_jvm)
    except Exception as e:
        line(str(e))
        input("press enter to close")


if __name__ == "__main__":
    main()