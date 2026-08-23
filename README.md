<img width="1308" height="1025" alt="image" src="https://github.com/user-attachments/assets/8820ab77-545d-4a87-b93d-e47d4e33ad87" />

This is for system settings only, *not* to "tweak the look and feel of Hyprland"

- WiFi
    - requires nmcli (NetworkManager)
    - connect / disconnect / forget known networks
    - autoconnect
    - shows IP, subnet, gateway, and DNS when connected
- Bluetooth
    - requires bluetoothctl
    - connect / disconnect / pair / unpair devices
    - toggle trusted flag per device
- Displays
    - requires hyprctl (Hyprland)
    - visual drag-to-arrange monitor layout
    - set position and mirror targets per display and remember them
    - set workspace rules for displays on the fly
    - apply changes live
- Sound
    - requires pipewire + wpctl
    - per-device output and input volume with mute
    - per-application stream volume with mute
- Apps
    - set default apps
    - configure autostart
- Appearance
    - toggle system dark/light mode
    - choose GTK icon/cursor theme 
    - choose GTK font 
- System Info
    - hostname, OS, kernel, uptime
    - CPU model, core count, memory usage
    - GPU (via lspci)

Run script
```bash
  ./run
```

Run script support installing/uninstalling on NixOS only
```bash
./run --install
./run --uninstall
```

