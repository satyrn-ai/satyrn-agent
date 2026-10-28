{ config, pkgs, ... }:

{
  languages.c.enable = true;

  languages.python = {
    enable = true;
    package = pkgs.python3;
    uv.enable = true;
  };

  packages = with pkgs; [
    actionlint
    coreutils
    curl
    git
    gnumake
    unzip
  ];

  env.UV_PYTHON = "${config.languages.python.package}/bin/python3";
  env.UV_PYTHON_DOWNLOADS = "never";

  scripts = {
    ds4-sync.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-sync.bash" "$@"
    '';
    ds4-export.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-export.bash" "$@"
    '';
    ds4-check.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-check.bash" "$@"
    '';
  };
}
