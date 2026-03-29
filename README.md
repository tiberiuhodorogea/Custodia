# Custodia

Automatic file backup service for Windows with a browser-based dashboard, accessible from any device on your local network.

---

## Features

- **Scheduled backups** — runs automatically at a configurable time and interval
- **Multiple sources and destinations** — back up any number of folders to any number of drives or UNC paths
- **Incremental copies** — skips files that haven't changed (compares size and modification time)
- **Versioned archives** — keeps a configurable number of dated snapshots per destination
- **Web dashboard** — manage everything from a browser; no remote desktop required
- **LAN access** — dashboard reachable from any PC on the same network
- **Runs as a Windows Service** — starts automatically on boot, no login required
- **Zero dependencies** — the release package includes a self-contained Python runtime

---

## Installation

> **Requirements:** Windows 10 or 11, 64-bit. No Python or other software needed on the target machine.

1. Download `custodia-release.zip` from the [latest release](../../releases/latest)
2. Extract the zip
3. Right-click `install.bat` → **Run as administrator**
4. Open a browser and go to `http://localhost:8550`

The service starts immediately and will restart automatically on every boot.

---

## Getting Started

1. Open the dashboard at `http://localhost:8550` (or `http://<computer-name>:8550` from another machine on the network)
2. Under **Sources** — add the folders you want to back up
3. Under **Destinations** — add where backups should go (local drive, USB, or UNC path like `\\NAS\backup`)
4. Under **Settings** — set frequency, backup time, and how many snapshots to keep
5. Click **Save Settings**
6. Optionally click **Run Now** for an immediate backup

---

## Uninstall

Right-click `uninstall.bat` → **Run as administrator**.

This removes the service and deletes `C:\Custodia`. Backup archives on destination drives are not touched.

---

## Building from Source

Run on the development machine (internet required):

```powershell
.\build_release.ps1
```

This produces a `Release\` folder and `custodia-release.zip` containing a fully self-contained build. Copy either to the target machine and run `install.bat`.

---

## License

MIT
