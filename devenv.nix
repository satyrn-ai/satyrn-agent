{ config, pkgs, ... }:

{
  languages.c.enable = true;

  # The pinned ds4 source uses macOS 15 Metal APIs; the Metal build needs the
  # matching SDK (the default clang SDK is older and lacks them).
  apple.sdk =
    if pkgs.stdenv.hostPlatform.isDarwin
    then pkgs.apple-sdk_15
    else null;

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

  enterShell = ''
    if [[ "$(uname -s)" == "Darwin" ]]; then
      export MACOSX_DEPLOYMENT_TARGET=15.0
    fi
  '';

  env.UV_PYTHON = "${config.languages.python.package}/bin/python3";
  env.UV_PYTHON_DOWNLOADS = "never";

  scripts = {
    ds4-sync.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-sync.sh" "$@"
    '';
    ds4-export.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-export.sh" "$@"
    '';
    ds4-check.exec = ''
      exec bash "${config.devenv.root}/tools/ds4-check.sh" "$@"
    '';
  };
}
