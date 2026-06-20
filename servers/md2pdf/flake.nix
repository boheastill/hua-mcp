{
  description = "md2pdf — self-contained Chromium + CJK fonts + Node env for markdown→PDF";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python312
            python312Packages.pip
            python312Packages.virtualenv

            # Native libs Chromium / rendering need.
            pango cairo gobject-introspection glib fontconfig freetype pkg-config

            # Node for mermaid-cli + the headless browser engine.
            nodejs_22
            chromium

            # CJK fonts — no tofu boxes under headless Chromium.
            noto-fonts
            noto-fonts-cjk-sans
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.pango pkgs.cairo pkgs.glib ]}:$LD_LIBRARY_PATH"
            # Force the supply-chain-clean Nix Chromium (used by both mmdc and the PDF print step).
            export PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
            export PUPPETEER_EXECUTABLE_PATH="${pkgs.chromium}/bin/chromium"
            export FONTCONFIG_FILE=${pkgs.makeFontsConf { fontDirectories = [ pkgs.noto-fonts pkgs.noto-fonts-cjk-sans ]; }}
            echo "🖨️  md2pdf env ready — $(python --version), Node $(node --version), $(${pkgs.chromium}/bin/chromium --version)"
          '';
        };
      }
    );
}
