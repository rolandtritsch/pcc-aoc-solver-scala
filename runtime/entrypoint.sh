#!/bin/sh
set -eu
: "${AOC_SSH_PUBLIC_KEY:?Provide the controller's SSH public key}"
mkdir -p /workspaces/.ssh-host /workspaces/.cache /workspaces/.sbt /workspaces/.ivy2
chmod 700 /workspaces/.ssh-host
chown paperclip:paperclip /workspaces /workspaces/.cache /workspaces/.sbt /workspaces/.ivy2
for name in .cache .sbt .ivy2; do
    if [ ! -e "/home/paperclip/$name" ]; then
        ln -s "/workspaces/$name" "/home/paperclip/$name"
    fi
done
if [ ! -f /workspaces/.ssh-host/ssh_host_ed25519_key ]; then
    ssh-keygen -q -t ed25519 -N '' -f /workspaces/.ssh-host/ssh_host_ed25519_key
fi
printf '%s\n' "$AOC_SSH_PUBLIC_KEY" > /etc/ssh/authorized_keys/paperclip
chmod 644 /etc/ssh/authorized_keys/paperclip
unset AOC_SSH_PUBLIC_KEY
exec /usr/sbin/sshd -D -e
