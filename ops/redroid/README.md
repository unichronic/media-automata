# ReDroid host setup

ReDroid needs the Linux `binder_linux` kernel module loaded before the Android container can boot. Without it, ADB stays `offline` after every host reboot.

## One-time install (Linux host)

From the repo root on the machine that runs ReDroid:

```bash
sudo bash ops/redroid/install-systemd.sh
```

This installs:

- `/etc/modules-load.d/binder-linux.conf` — load `binder_linux` on boot
- `/etc/modprobe.d/binder-linux.conf` — binder device nodes
- `media-automata-redroid.service` — start ReDroid after Docker and wait for ADB

The existing `media-automata-redroid` container is updated to `--restart unless-stopped`.

## Create container (first time only)

If the container does not exist yet:

```bash
bash ops/redroid/create-container.sh
sudo bash ops/redroid/install-systemd.sh
```

## Manual check

```bash
sudo systemctl status media-automata-redroid
/home/unichronic/.android-sdk/platform-tools/adb devices
```

Expected: `127.0.0.1:5555 device` and `sys.boot_completed=1`.
