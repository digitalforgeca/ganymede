# CI/CD & Build Pipeline Mandate

To preserve proprietary build logic and maintain security, the Ganymede project enforces a strict policy regarding continuous integration, continuous delivery, and release orchestration.

## 1. Mandate Against GitHub Actions (GHA)
*   **No GHA Workflows**: The use of GitHub Actions is strictly prohibited. Under no circumstances should a `.github` or `.github/workflows` directory be committed or used in the Ganymede repositories.
*   **No Public CI/CD Runners**: All builds, unit testing, and artifact compilations must be run locally or within the private infrastructure mesh.

## 2. Hephaestus CI/CD Integration
*   **Build Engine**: All automated build pipelines are managed via **Hephaestus**, a private Rust-based build service running in a secure container on the VPS network (**The Forge**).
*   **Git Monitoring**: Hephaestus is configured via `/opt/forge/services/hephaestus/hephaestus-monitor.toml` on the host VPS. It automatically watches our GitHub repositories and pulls changes to trigger builds.
*   **Project Manifests**: Any build pipeline definitions or compilation targets for Ganymede must be declared in a `forge-manifest.toml` file matching Hephaestus standards.

## 3. Deployments & Release Verification
*   **Forge Deployment**: Deployments to VPS nodes (e.g. Dionysus reverse proxy, Keycloak Cerberus bridge, or active sidecars) must be triggered via the `forge-deploy.sh` script.
*   **Verification**: All releases must run pre-deploy and post-deploy health checks against target container statuses rather than relying on external public web checks.
