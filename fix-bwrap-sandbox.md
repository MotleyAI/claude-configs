# Fix bwrap sandbox on Ubuntu 24.04+

Ubuntu restricts unprivileged user namespaces via AppArmor, which breaks
bubblewrap's network isolation. Grant bwrap permission to create user namespaces:

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
