// PM2 process list for the WSL-hosted side of the hua-mcp fleet.
// (win-agents:8001 runs on the Windows host — see win_agents/install-autostart.ps1.)
// Each app launches its dir's run.sh, which ensures a uv venv + deps, then serves
// streamable-http on its registry port. Topology of record: ../registry.json.
module.exports = {
  apps: [
    {
      name: "mcp-wsl-8002",
      script: "./run.sh",
      cwd: "./wsl_agents",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_memory_restart: "500M",
      env: { NODE_ENV: "production" }
    },
    {
      name: "mcp-api-8003",
      script: "./run.sh",
      cwd: "./cloud_api_agents",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_memory_restart: "500M",
      env: { NODE_ENV: "production" }
    },
    {
      // Heavy / isolated server (8010+ tier): own process so a wedged or
      // memory-hungry Chromium can't take down the 8002 tool fleet.
      name: "mcp-md2pdf-8010",
      script: "./run.sh",
      cwd: "./servers/md2pdf",
      interpreter: "none", // run.sh enters `nix develop` itself
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production"
        // MD2PDF_TOKEN: "<set to require Bearer auth on REST /pdf when public>"
      }
    }
  ]
};
