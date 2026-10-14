# Public-repository security & robot safety

This repository is public. Email addresses in author metadata are acceptable, but avoid all other personal data.

## Never commit

API tokens, passwords, SSH keys, client certificates, Wi-Fi passwords, Tailscale identifiers or auth keys, public/private IPs tied to real hardware, serial numbers, device identities, private repository URLs, exact lab/home floorplans, camera recordings, faces, license-protected datasets, weights requiring acceptance, or training logs containing private paths.

Use `.env` or other ignored local config and documented `.example` files; review git diff before commit. Never publish raw ROS bags or observation logs by default. Do not make a network listener public by accident. Example addresses should use RFC 5737 documentation IPs or localhost.

## Runtime boundary

- GPU server never talks directly to motor drivers.
- ROS bridge is the only motor-command issuer; `dry_run=true` is default.
- E-stop, timeout/hold, command limits, collision checks and workspace bounds are independent of policy output.
- Unknown model or action schema => reject without motion.
- Do not let API request specify arbitrary adapter code, checkpoint URI or filesystem paths.
- Local service bound to `127.0.0.1` by default; remote LAN requires explicit firewall/auth decisions.
- Physical robots require review and signoff by an operator; software-only passing tests are insufficient.
- User-supplied natural-language commands are untrusted from a physical safety perspective; preflight limits always apply.

## Dependencies & licensing

Pin versions and check licenses for LeRobot, OpenPI, pretrained checkpoints, Gemma family and datasets before distribution. Do not copy copyrighted upstream code without preserving notices.

## Before each PR

Review changed and untracked files, scan for secrets, ensure fixtures are synthetic, check images/logs for identifying details, run tests, and include a short security note in PR description.
