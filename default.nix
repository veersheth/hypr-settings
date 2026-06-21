{ pkgs ? import <nixpkgs> {} }:

let
  python = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);
in
pkgs.writeShellScriptBin "hypr-settings" ''
  exec ${python}/bin/python ${builtins.toString ./.}/main.py "$@"
''
