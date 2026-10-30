#!/usr/bin/env bash
# Download the two public datasets used for independent evaluation, into the Sentinel state folder.
#   Microsoft Cloud Monitoring Dataset  (MIT licence, about 10 MB)   -> $DATA/msds
#   RCAEval RE1                         (CC-BY 4.0, about 390 MB)    -> $DATA/RE1.zip   (read in place, never extracted)
# The Unisphere request log is private and is NOT downloaded: the repository already contains its anonymous profile.
set -euo pipefail

DATA="${SENTINEL_DATA:-/srv/sentinel/data}"
mkdir -p "$DATA"

if [[ ! -d "$DATA/msds/data" ]]; then
  echo "==> Microsoft Cloud Monitoring Dataset"
  git clone --depth 1 https://github.com/microsoft/cloud-monitoring-dataset "$DATA/msds"
fi

if [[ ! -s "$DATA/RE1.zip" ]]; then
  echo "==> RCAEval RE1 (about 390 MB)"
  curl -fL --retry 3 -o "$DATA/RE1.zip.part" "https://zenodo.org/records/14504481/files/RE1.zip?download=1"
  mv "$DATA/RE1.zip.part" "$DATA/RE1.zip"
fi

echo "==> done"
du -sh "$DATA/msds" "$DATA/RE1.zip"
