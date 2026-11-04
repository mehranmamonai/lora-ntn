#!/usr/bin/env bash
# Fixed run contract: builds the pinned ns-3 + lorawan once on the host, then runs sim/run_matrix.sh.
set -euo pipefail
NS3_TAG=ns-3.48
LORAWAN_COMMIT=e45b4af
ROOT="$HOME/lora-ntn-sim"
NS3="$ROOT/ns-3"
REPO="$PWD"
mkdir -p "$ROOT" results/bin

(
  flock 9
  if [ ! -d "$NS3/.git" ]; then
    git clone --depth 1 --branch "$NS3_TAG" https://gitlab.com/nsnam/ns-3-dev.git "$NS3"
  fi
  if [ ! -d "$NS3/src/lorawan/.git" ]; then
    git clone https://github.com/signetlabdei/lorawan "$NS3/src/lorawan"
    git -C "$NS3/src/lorawan" checkout -q "$LORAWAN_COMMIT"
  fi
  cd "$NS3"
  if [ ! -f "$ROOT/.configured" ]; then
    ./ns3 configure --build-profile=optimized --enable-modules lorawan \
      --disable-tests --disable-examples --disable-werror
    touch "$ROOT/.configured"
  fi
  mkdir -p scratch
  cp "$REPO"/sim/*.cc scratch/
  ./ns3 build
  for src in "$REPO"/sim/*.cc; do
    name=$(basename "$src" .cc)
    cp "build/scratch/ns3.48-$name-optimized" "$REPO/results/bin/$name"
  done
) 9>"$ROOT/.build.lock"

export LD_LIBRARY_PATH="$NS3/build/lib:${LD_LIBRARY_PATH:-}"
echo "ENV ns3=$NS3_TAG lorawan=$LORAWAN_COMMIT commit=${ORX_COMMIT:-unknown} cores=$(nproc)"
bash sim/run_matrix.sh
