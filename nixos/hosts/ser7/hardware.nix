# nixos/hosts/ser7/hardware.nix
{ inputs, config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
  ] ++ (with inputs.nixos-hardware.nixosModules; [
    common-cpu-amd
    common-pc-ssd
  ]);

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxKernel.packages.linux_zen;
  boot.kernelModules = [ "iwlwifi" ]; # wi-fi
  hardware.enableRedistributableFirmware = true;

  # 内蔵 Intel Bluetooth (8087:0029) を無効化し、USB 外付けアダプタ (TP-Link 2357:0604) のみ使用する
  services.udev.extraRules = ''
    SUBSYSTEM=="usb", ATTRS{idVendor}=="8087", ATTRS{idProduct}=="0029", ATTR{authorized}="0"
  '';

  # Enable CUPS to print documents.
  services.printing.enable = true;

  fileSystems."/mnt/ugreen" = {
    device = "//192.168.0.222/personal_folder";
    fsType = "cifs";
    options = [
      "credentials=/etc/nixos/.smbcredentials"
      "uid=1000"
      "gid=1000"
      "file_mode=0644"
      "dir_mode=0755"
      "iocharset=utf8"
      "_netdev"
      "nofail"
      "nobrl"
    ];
  };
}
