# Setting up Claude Code sandbox on Ubuntu 24.04+

## 1. Install dependencies

```bash
sudo apt install bubblewrap socat
```

## 2. Fix AppArmor permissions

Ubuntu restricts unprivileged user namespaces via AppArmor, which breaks
bubblewrap's network isolation. The workaround below uses `flags=(unconfined)`
which disables AppArmor confinement for bwrap entirely, not just userns.
This is the standard fix (no narrower profile exists yet), but be aware it
removes AppArmor restrictions on anything bwrap launches:

```bash
sudo tee /etc/apparmor.d/bwrap << 'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,

  include if exists <local/bwrap>
}
EOF

sudo systemctl reload apparmor
```

Restart Claude Code after applying.
