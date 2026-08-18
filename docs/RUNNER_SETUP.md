# Self-hosted GitHub Actions runner

Heavy model jobs (state re-estimation, Zweitstimme federal MCMC) exceed GitHub-hosted runner limits (~6 h, limited CPU/RAM). Register a self-hosted runner on the forecasts server.

## Requirements

- Ubuntu 22.04+ (matches existing `/mnt/cerfort/forecasts` host)
- R 4.4+ with Stan toolchain (`rstan`, `rstanarm` for state model)
- Python 3.8+ (election date scraper)
- ≥20 CPU cores, ~64 GB RAM recommended for full federal MCMC

## Register runner

1. In GitHub: **zweitstimme-org** → Settings → Actions → Runners → New self-hosted runner
2. On the server:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64-2.320.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.320.0/actions-runner-linux-x64-2.320.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.320.0.tar.gz
./config.sh --url https://github.com/zweitstimme-org --token <TOKEN> --labels heavy-r,self-hosted
sudo ./svc.sh install
sudo ./svc.sh start
```

3. Install R dependencies once:

```bash
cd /mnt/cerfort/forecasts/website-pipeline
Rscript R/install.R
INSTALL_STATE_MODEL_DEPS=true Rscript R/install.R
```

4. Clone model repos the workflows expect:

```bash
git clone https://github.com/zweitstimme-org/state-models-jelst.git vendor/state-models-jelst
# Federal model (already on server):
# /mnt/cerfort/forecasts/prediction-2025
```

## Repository secret

Add `WEBSITE_DEPLOY_TOKEN` to **website-pipeline** repo secrets:

- Fine-grained PAT scoped to `website-source` with **Contents: Read and write**
- Used by publish script to commit JSON to `static/data/`

## Workflow labels

Workflows use `runs-on: [self-hosted, heavy-r]`. Ensure the runner is registered with the `heavy-r` label.

## Monitoring

```bash
sudo ./svc.sh status
journalctl -u actions.runner.* -f
make status   # in website-pipeline checkout
```
