<img width="1260" height="1080" alt="image" src="https://github.com/user-attachments/assets/d3e09459-55d8-41cb-a650-a1dddd44a93a" />

A PySide6 settings GUI for Hyprland / Wayland desktops. 

- WiFi
  - Requires nmcli (NetworkManager)
  - Connect / disconnect / forget known networks
  - Connect to new or hidden networks
  - Toggle auto-connect per network
  - Shows IP, subnet, gateway, and DNS when connected
- Bluetooth
  - Requires bluetoothctl
  - Connect / disconnect / pair / unpair devices
  - Scan for new devices
  - Toggle trusted flag per device
- Displays
  - Requires hyprctl (Hyprland)
  - Visual drag-to-arrange monitor layout
  - Set position and mirror targets per display
  - Apply changes live
- Sound
  - Requires pipewire + wpctl
  - Per-device output and input volume with mute
  - Per-application stream volume with mute
  - Reset all application streams to 100%
- System Info
  - Hostname, OS, kernel, uptime
  - CPU model, core count, memory usage
  - GPU (via lspci)

Running
```bash
  ./run
```

Requires nix-shell with pyside6 available (see shell.nix)

