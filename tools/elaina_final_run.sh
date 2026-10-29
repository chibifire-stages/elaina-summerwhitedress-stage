set -e
cd ./.hermes/cache/scratch
Q=7.932246821337585e-05
python3 usd_strip_shells.py --src elaina_retry/Elaina.usdc --dst elaina_retry/Elaina_v5.usdc \
  --manifest elaina_retry/manifest_v5.json --report elaina_retry/report_v5.json \
  --under /root/char_grp/rig --quantum $Q --remove-cs-gizmos --remove-empty-xforms
echo "--- control arm (must FAIL) ---"
python3 usd_paired_check.py --file elaina_retry/Elaina.usdc --quantum $Q 2>&1 | tail -5 || true
echo "--- result arm ---"
python3 usd_paired_check.py --file elaina_retry/Elaina_v5.usdc --reference elaina_retry/Elaina.usdc \
  --manifest elaina_retry/manifest_v5.json --quantum $Q 2>&1 | tail -8 || true
python3 usd_rename_english.py --src elaina_retry/Elaina_v5.usdc --dst elaina_retry/Elaina_en5.usdc 2>&1 | tail -3
python3 usd_package3.py elaina_retry/Elaina_en5.usdc elaina_retry/textures ./Desktop/Elaina_clean.usdz ./elaina_pkg_out 2>&1 | tail -3
echo "--- packaged deliverable ---"
python3 usd_paired_check.py --file ./Desktop/Elaina_clean.usdz --quantum $Q 2>&1 | tail -5 || true
usdchecker ./Desktop/Elaina_clean.usdz 2>&1 | tail -2
