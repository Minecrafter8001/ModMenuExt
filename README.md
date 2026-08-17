
# ModMenuExt


External Delta-V mod manager built in Python.


Features:

- Steam library autodiscovery for the Delta-V install directory.

- Installed mod scanning from the game's `mods` folder.

- Toggle mods on and off without deleting archives.

- Download and install mods from direct zip URLs or GitHub repository/release URLs.

- Fully [ModMenu2](https://github.com/rwqfsfasxc100/ModMenu2) and [dv_update_database](https://github.com/rwqfsfasxc100/dv_update_database) compatible (thanks hev_ :3)
  

## Autodetected Paths

  

- Windows Delta-V user data: `AppData\Roaming\dV`

- Linux Delta-V user data: `~/.local/share/dV/`

- Linux Flatpak Steam user data: `~/.var/app/com.valvesoftware.Steam/data/dV/`

- Windows Steam Library file: `C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf`

- Linux Steam library file: `~/.local/share/Steam/steamapps/libraryfolders.vdf`

- Linux Flatpak Steam library file: `~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf`


## Setup

  

```powershell

python -m venv .venv

.venv\Scripts\Activate.ps1

pip install -e .

```

  

## Run

  

```powershell

python -m modmenuext

```

  

## Build An EXE

  

```powershell

pip install pyinstaller

pyinstaller --noconfirm --onefile --windowed --name ModMenuExt --paths src src\modmenuext\__main__.py

```

  

The built executable will be written to `dist\ModMenuExt.exe`.
