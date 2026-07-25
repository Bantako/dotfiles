{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
  auditPython = pkgs.python3.withPackages (ps: [ ps.jsonschema ]);
  auditScript = ../../../tools/hermes_operations_audit.py;
  contract = ../../../docs/hermes-operations-contract.json;
  contractSchema = ../../../docs/schema/hermes-operations-contract.schema.json;
  reportSchema = ../../../docs/schema/hermes-operations-audit.schema.json;
  glanceConfig = ./hermes-operations-glance.yml;
  stateDir = "${config.xdg.stateHome}/hermes-operations";
  auditEnvironment = "${lib.makeBinPath [
    hermesPkg
    pkgs.systemd
  ]}";

  auditCommand = pkgs.writeShellScript "hermes-operations-audit" ''
    set -euo pipefail
    exec ${pkgs.coreutils}/bin/env \
      -u PYTHONPATH \
      -u PYTHONHOME \
      PATH=${auditEnvironment} \
      ${auditPython}/bin/python ${auditScript} audit \
      --contract ${contract} \
      --contract-schema ${contractSchema} \
      --report-schema ${reportSchema} \
      --output ${stateDir}/audit-result.json \
      --allow-drift
  '';

  apiCommand = pkgs.writeShellScript "hermes-operations-api" ''
    set -euo pipefail
    exec ${pkgs.coreutils}/bin/env \
      -u PYTHONPATH \
      -u PYTHONHOME \
      ${auditPython}/bin/python ${auditScript} serve \
      --result ${stateDir}/audit-result.json \
      --report-schema ${reportSchema} \
      --host 127.0.0.1 --port 8791
  '';
in
{
  home.packages = [ pkgs.glance ];

  systemd.user.services.hermes-operations-audit = {
    Unit = {
      Description = "Audit Hermes entry-surface contracts";
      OnFailure = [ "hermes-failure-notify@%N.service" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = auditCommand;
      UMask = "0077";
      StateDirectory = "hermes-operations";
      StateDirectoryMode = "0700";
      TimeoutStartSec = "2m";
      NoNewPrivileges = true;
      # PrivateTmp makes another user unit's /proc/<pid>/environ unreadable.
      # The auditor needs that file only to allowlist HERMES_PROFILE.
    };
  };

  systemd.user.timers.hermes-operations-audit = {
    Unit.Description = "Refresh Hermes operations audit every five minutes";
    Timer = {
      OnCalendar = "*:0/5";
      Persistent = true;
      AccuracySec = "30s";
    };
    Install.WantedBy = [ "timers.target" ];
  };

  systemd.user.services.hermes-operations-api = {
    Unit = {
      Description = "Read-only Hermes operations audit API";
      Wants = [ "hermes-operations-audit.service" ];
      After = [ "hermes-operations-audit.service" ];
      OnFailure = [ "hermes-failure-notify@%N.service" ];
    };
    Service = {
      Type = "exec";
      ExecStart = apiCommand;
      Restart = "always";
      RestartSec = "10s";
      UMask = "0077";
      StateDirectory = "hermes-operations";
      StateDirectoryMode = "0700";
      NoNewPrivileges = true;
      PrivateTmp = true;
    };
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.services.hermes-operations-glance = {
    Unit = {
      Description = "Glance dashboard for Hermes operations contracts";
      Wants = [ "hermes-operations-api.service" ];
      After = [ "hermes-operations-api.service" ];
      OnFailure = [ "hermes-failure-notify@%N.service" ];
    };
    Service = {
      Type = "exec";
      ExecStart = "${pkgs.glance}/bin/glance -config ${glanceConfig}";
      Restart = "always";
      RestartSec = "10s";
      NoNewPrivileges = true;
      PrivateTmp = true;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
