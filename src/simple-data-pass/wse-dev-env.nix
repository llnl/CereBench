{
  description = "Cerebras SDK & Simulator Development Environment";

  inputs = {
    # pinned to a stable release to avoid upstream python/sphinx breakages
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
  };

  outputs = { self, nixpkgs }: 
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};

    # FHS wrapper to provide standard Linux paths and libraries
    cerebras-fhs = pkgs.buildFHSEnv {
      name = "cerebras-dev-env";
      targetPkgs = pkgs: with pkgs; [
        # base python
        python311
        
        # container runtime and its dependencies
        apptainer 
        gocryptfs  # added to silence the Apptainer encryption warning
        
        # common C libraries for proprietary ML binaries
        stdenv.cc.cc.lib
        zlib
        glib
        xorg.libX11
        libGL
      ];
      
      profile = ''
        export VENV_DIR=".venv"
        if [ ! -d "$VENV_DIR" ]; then
          python -m venv $VENV_DIR
        fi
        source $VENV_DIR/bin/activate
        export PYTHONPATH=$VENV_DIR/lib/python3.11/site-packages:$PYTHONPATH
        
        # capture the project root dynamically at boot (all the cerebras stuffs)
        export PATH="$PWD:$PATH"
        
        # set default import path to silence compiler warnings
        export CSL_IMPORT_PATH="$PWD"
        
	fish
        echo "Hello Cerebras! :D"
      '';

      runScript = "bash";
    };

  in {
    devShells.${system}.default = cerebras-fhs.env;
  };
}
