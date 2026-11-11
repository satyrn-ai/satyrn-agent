{ config, pkgs, lib, ... }:

let
  # CUDA 12.9 is what the pinned nixpkgs provides and the toolchain the dense
  # qwen35 CUDA path is written against. Darwin has no CUDA, so the Metal build
  # must not see these packages.
  cuda = pkgs.cudaPackages;
  hasCuda = pkgs.stdenv.hostPlatform.isLinux;
  # The merged cudatoolkit drags in the whole redistrib (cuobjdump, gdb,
  # profiler APIs). nvcc needs the compiler, the runtime headers and CCCL.
  cudaDev = pkgs.symlinkJoin {
    name = "cuda-dev";
    paths = [ cuda.cuda_nvcc cuda.cuda_cudart cuda.cuda_cccl ];
  };
in
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
    package = pkgs.python314;
    uv.enable = true;
  };

  packages = with pkgs; [
    actionlint
    coreutils
    curl
    git
    gnumake
    unzip
  ] ++ lib.optionals hasCuda [
    cuda.cuda_nvcc
    cuda.cuda_cudart
    cuda.cuda_cccl
    cuda.libcublas
  ];

  # String interpolation is evaluated eagerly, so the CUDA environment must be
  # appended only where the packages exist; Darwin has no CUDA attribute set.
  enterShell = ''
    if [[ "$(uname -s)" == "Darwin" ]]; then
      export MACOSX_DEPLOYMENT_TARGET=15.0
    fi
  '' + lib.optionalString hasCuda ''
    export CUDA_PATH="${cudaDev}"
    export CUDA_HOME="$CUDA_PATH"
    # cuda_cudart ships a link-time libcuda.so.1 stub that shadows the real
    # driver at run time; the driver directory must come first.
    export LD_LIBRARY_PATH="${cudaDev}/lib:${cuda.libcublas}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    if [[ -d /run/opengl-driver/lib ]]; then
      export LD_LIBRARY_PATH="/run/opengl-driver/lib:$LD_LIBRARY_PATH"
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
